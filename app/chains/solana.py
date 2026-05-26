"""Solana SPL token balance reader using Helius JSON-RPC.

Uses getTokenAccountsByOwner to find all token accounts for a given
mint and sums their amounts (a wallet can technically have multiple
token accounts for the same mint, though rare in practice).

Requires HELIUS_API_KEY in settings.
"""

from __future__ import annotations

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
from app.settings import settings

log = get_logger(__name__)

_HELIUS_BASE = "https://mainnet.helius-rpc.com"


def _retry() -> AsyncRetrying:
    return AsyncRetrying(
        retry=retry_if_exception_type(
            (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError)
        ),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.4, min=0.4, max=4.0),
        reraise=True,
    )


async def spl_balance(
    http: httpx.AsyncClient,
    *,
    owner_address: str,
    mint: str,
) -> tuple[int, int]:
    """Return (raw_amount, decimals) for the given Solana SPL token.

    Queries all token accounts owned by owner_address for the specified mint
    and sums their raw amounts. Returns (0, 0) if the owner holds no tokens
    or on error.
    """
    url = f"{_HELIUS_BASE}/?api-key={settings.helius_api_key}"
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTokenAccountsByOwner",
        "params": [
            owner_address,
            {"mint": mint},
            {"encoding": "jsonParsed"},
        ],
    }
    try:
        async for attempt in _retry():
            with attempt:
                resp = await http.post(url, json=body, timeout=10.0)
                resp.raise_for_status()
                data: dict[str, Any] = resp.json()
    except Exception as exc:
        log.warning("helius_fetch_failed", owner=owner_address, mint=mint, err=repr(exc))
        return (0, 0)

    if "error" in data:
        log.warning("helius_rpc_error", err=data["error"])
        return (0, 0)

    accounts = (data.get("result") or {}).get("value") or []
    if not accounts:
        return (0, 0)

    total_raw = 0
    decimals = 0
    for acc in accounts:
        token_amount = (
            acc.get("account", {})
            .get("data", {})
            .get("parsed", {})
            .get("info", {})
            .get("tokenAmount", {})
        )
        try:
            total_raw += int(token_amount.get("amount", 0))
            decimals = int(token_amount.get("decimals", 0))
        except (ValueError, TypeError):
            continue

    return (total_raw, decimals)


# ── Solana transaction scanner ────────────────────────────────────────────────


@dataclass(frozen=True)
class SolanaTxRecord:
    signature: str
    slot: int
    lamports: int  # native SOL amount transferred


async def get_solana_current_slot(http: httpx.AsyncClient) -> int:
    """Return the current Solana slot number (freshness cursor).

    Used when issuing a dust request: any tx with slot < this value was
    confirmed before the request was created and must be rejected.
    Returns 0 on error (no freshness gate -- safe fallback).
    """
    url = f"{_HELIUS_BASE}/?api-key={settings.helius_api_key}"
    body = {"jsonrpc": "2.0", "id": 1, "method": "getSlot", "params": []}
    try:
        async for attempt in _retry():
            with attempt:
                resp = await http.post(url, json=body, timeout=8.0)
                resp.raise_for_status()
                data = resp.json()
        return int(data.get("result", 0))
    except Exception as exc:
        log.warning("helius_slot_fetch_failed", err=repr(exc))
        return 0


async def find_solana_self_transfer(
    http: httpx.AsyncClient,
    *,
    address: str,
    expected_lamports: int,
    tolerance_lamports: int = 0,
    min_slot: int = 0,
) -> SolanaTxRecord | None:
    """Scan recent Solana transactions for a native SOL self-transfer.

    A self-transfer is a system 'transfer' instruction where source == destination
    == address and lamports is within tolerance of expected_lamports.

    min_slot is the freshness gate: txs with slot < min_slot are skipped.

    Strategy: fetch up to 50 recent signatures, skip stale ones, fetch each
    transaction and check instructions. Returns the first match.
    """
    url = f"{_HELIUS_BASE}/?api-key={settings.helius_api_key}"

    # Step 1: get recent signatures
    sigs_body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getSignaturesForAddress",
        "params": [address, {"limit": 50}],
    }
    try:
        async for attempt in _retry():
            with attempt:
                resp = await http.post(url, json=sigs_body, timeout=10.0)
                resp.raise_for_status()
                sigs_data = resp.json()
    except Exception as exc:
        log.warning("helius_sigs_fetch_failed", address=address, err=repr(exc))
        return None

    if "error" in sigs_data:
        log.warning("helius_sigs_rpc_error", err=sigs_data["error"])
        return None

    sigs = sigs_data.get("result") or []

    # Step 2: check each signature
    for sig_info in sigs:
        if sig_info.get("err") is not None:
            continue  # failed tx -- skip
        slot = int(sig_info.get("slot", 0))
        if slot < min_slot:
            # Signatures are newest-first; below min_slot means all remaining are older.
            break
        signature = sig_info["signature"]

        # Fetch full transaction
        tx_body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTransaction",
            "params": [signature, {"encoding": "jsonParsed", "commitment": "finalized"}],
        }
        try:
            async for attempt in _retry():
                with attempt:
                    tx_resp = await http.post(url, json=tx_body, timeout=10.0)
                    tx_resp.raise_for_status()
                    tx_data = tx_resp.json()
        except Exception as exc:
            log.warning("helius_tx_fetch_failed", sig=signature, err=repr(exc))
            continue

        result = tx_data.get("result")
        if result is None:
            continue

        tx_slot = int(result.get("slot", slot))
        instructions = result.get("transaction", {}).get("message", {}).get("instructions", [])

        for ix in instructions:
            if ix.get("program") != "system":
                continue
            parsed = ix.get("parsed") or {}
            if parsed.get("type") != "transfer":
                continue
            info = parsed.get("info") or {}
            src = info.get("source", "")
            dst = info.get("destination", "")
            lamps = int(info.get("lamports", 0))

            if src != address or dst != address:
                continue
            if abs(lamps - expected_lamports) > tolerance_lamports:
                continue

            return SolanaTxRecord(signature=signature, slot=tx_slot, lamports=lamps)

    return None
