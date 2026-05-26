"""Solana SPL token balance reader using Helius JSON-RPC.

Uses getTokenAccountsByOwner to find all token accounts for a given
mint and sums their amounts (a wallet can technically have multiple
token accounts for the same mint, though rare in practice).

Requires HELIUS_API_KEY in settings.
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
