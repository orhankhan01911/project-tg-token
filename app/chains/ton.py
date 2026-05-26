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
