"""TON jetton balance reader using tonapi.io (no API key required).

Reads the raw balance of a TON jetton (fungible token) for a given owner address.

API: GET https://tonapi.io/v2/accounts/{owner}/jettons/{jetton_master}
Response shape:
  {
    "balance": "123456789",
    "jetton": {"decimals": 9, "symbol": "UTYA", ...},
    ...
  }

On 404 (user has no wallet for this jetton) → returns (0, 9) safe default.
Owner address can be either "EQ..." (user-facing) or "0:..." (raw hex) format;
tonapi.io accepts both.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.logging_conf import get_logger

log = get_logger(__name__)

_TONAPI_BASE = "https://tonapi.io/v2"


def _retry() -> AsyncRetrying:
    return AsyncRetrying(
        retry=retry_if_exception_type(
            (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError)
        ),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.4, min=0.4, max=4.0),
        reraise=True,
    )


async def jetton_balance(
    http: httpx.AsyncClient,
    *,
    owner_address: str,
    jetton_master: str,
) -> tuple[int, int]:
    """Return (raw_balance, decimals) for the given TON jetton.

    Returns (0, 9) if the owner has no jetton wallet (404) or balance is 0.
    decimals defaults to 9 (standard for most TON jettons).
    """
    url = f"{_TONAPI_BASE}/accounts/{owner_address}/jettons/{jetton_master}"
    try:
        async for attempt in _retry():
            with attempt:
                resp = await http.get(url, timeout=8.0)
                if resp.status_code == 404:
                    return (0, 9)
                resp.raise_for_status()
                data: dict[str, Any] = resp.json()
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:
        log.warning(
            "tonapi_fetch_failed",
            owner=owner_address,
            jetton=jetton_master,
            err=repr(exc),
        )
        return (0, 9)

    balance_str = data.get("balance", "0")
    jetton_info = data.get("jetton") or {}
    decimals = int(jetton_info.get("decimals", 9))
    try:
        balance = int(balance_str)
    except (ValueError, TypeError):
        balance = 0
    return (balance, decimals)


# ── TON transaction scanner ───────────────────────────────────────────────────


@dataclass(frozen=True)
class TonTxRecord:
    hash: str
    lt: int  # logical time — monotonically increasing per account
    value: int  # nanoTON transferred


def ton_address_to_raw(address: str) -> str:
    """Convert a user-friendly TON address (EQ.../UQ...) to raw 0:hexstring form.

    TON user-friendly addresses are 48 base64url characters encoding:
      - byte 0: flags (tag + bounceable + testnet bits)
      - byte 1: workchain (-1=255 for masterchain, 0 for basechain)
      - bytes 2-33: 32-byte address
      - bytes 34-35: CRC16-CCITT checksum

    We extract the workchain and address bytes and format as "workchain:hex".
    Mainnet addresses (workchain 0) -> "0:hexstring".
    """
    # Pad to multiple of 4 for standard base64 decoding
    padded = address + "=" * ((4 - len(address) % 4) % 4)
    decoded = base64.urlsafe_b64decode(padded)
    # byte 1 is workchain as unsigned; convert to signed
    workchain = decoded[1] if decoded[1] < 128 else decoded[1] - 256
    addr_hex = decoded[2:34].hex()
    return f"{workchain}:{addr_hex}"


async def get_ton_latest_lt(http: httpx.AsyncClient, *, address: str) -> int:
    """Return the current logical time for an address (freshness cursor).

    Used when issuing a dust request: any tx with lt < this value was mined
    before the request was created and must be rejected.
    Returns 0 on error (no freshness gate -- safe fallback, just less secure).
    """
    url = f"{_TONAPI_BASE}/accounts/{address}"
    try:
        async for attempt in _retry():
            with attempt:
                resp = await http.get(url, timeout=8.0)
                resp.raise_for_status()
                data = resp.json()
        return int(data.get("last_transaction_lt", 0))
    except Exception as exc:
        log.warning("tonapi_lt_fetch_failed", address=address, err=repr(exc))
        return 0


async def find_ton_self_transfer(
    http: httpx.AsyncClient,
    *,
    address: str,
    expected_nanoton: int,
    tolerance_nanoton: int = 0,
    min_lt: int = 0,
) -> TonTxRecord | None:
    """Scan recent TON transactions for a self-transfer of expected_nanoton.

    A self-transfer is an in_msg where source == destination == address
    and value is within tolerance_nanoton of expected_nanoton.

    min_lt is the freshness gate: transactions with lt < min_lt are skipped
    (they were mined before the /verify request was created).

    Returns the first matching TonTxRecord, or None.
    """
    raw = ton_address_to_raw(address)
    url = f"{_TONAPI_BASE}/accounts/{address}/transactions"
    try:
        async for attempt in _retry():
            with attempt:
                resp = await http.get(url, params={"limit": 50}, timeout=10.0)
                resp.raise_for_status()
                data = resp.json()
    except Exception as exc:
        log.warning("tonapi_tx_fetch_failed", address=address, err=repr(exc))
        return None

    for tx in data.get("transactions", []):
        lt = int(tx.get("lt", 0))
        if lt < min_lt:
            # Transactions are returned newest-first; once we're below min_lt
            # all remaining are older -- stop scanning.
            break

        in_msg = tx.get("in_msg") or {}
        if in_msg.get("msg_type") != "int_msg":
            continue

        src = (in_msg.get("source") or {}).get("address", "")
        dst = (in_msg.get("destination") or {}).get("address", "")
        value = int(in_msg.get("value", 0))

        # Self-transfer: source and destination both normalize to our address.
        if src != raw or dst != raw:
            continue
        if abs(value - expected_nanoton) > tolerance_nanoton:
            continue

        return TonTxRecord(hash=str(tx["hash"]), lt=lt, value=value)

    return None
