"""USD price lookup via DexScreener (no API key required).

Supports EVM chains and Solana. TON also covered by DexScreener
under chainId='ton'.

DexScreener endpoint:
  GET https://api.dexscreener.com/latest/dex/tokens/{contract_or_mint}
Returns a list of pairs. We pick the pair with the highest liquidity.usd
for the requested chain — this is the most reliable price signal.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.logging_conf import get_logger

log = get_logger(__name__)

_DEXSCREENER_BASE = "https://api.dexscreener.com/latest/dex/tokens"

# Map our internal chain slug → DexScreener chainId value
_CHAIN_SLUG_MAP = {
    "eth": "ethereum",
    "base": "base",
    "base-sepolia": "base",  # treated as base for pricing
    "solana": "solana",
    "ton": "ton",
}


def _retry() -> AsyncRetrying:
    return AsyncRetrying(
        retry=retry_if_exception_type(
            (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError)
        ),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.4, min=0.4, max=4.0),
        reraise=True,
    )


async def get_token_price_usd(
    http: httpx.AsyncClient,
    *,
    chain_slug: str,
    contract_or_mint: str,
) -> Decimal | None:
    """Return the token's USD price from DexScreener.

    Picks the trading pair with the highest liquidity.usd on the requested chain.
    Returns None if no pairs exist, priceUsd is null/missing, or on error.
    """
    dex_chain = _CHAIN_SLUG_MAP.get(chain_slug, chain_slug)
    url = f"{_DEXSCREENER_BASE}/{contract_or_mint}"
    try:
        async for attempt in _retry():
            with attempt:
                resp = await http.get(url, timeout=8.0)
                resp.raise_for_status()
                data: dict[str, Any] = resp.json()
    except Exception as exc:
        log.warning(
            "dexscreener_fetch_failed", chain=chain_slug, contract=contract_or_mint, err=repr(exc)
        )
        return None

    pairs = data.get("pairs") or []
    # filter to the requested chain
    chain_pairs = [p for p in pairs if p.get("chainId") == dex_chain]
    if not chain_pairs:
        log.info(
            "dexscreener_no_pairs", chain=chain_slug, dex_chain=dex_chain, contract=contract_or_mint
        )
        return None

    # pick highest liquidity pair
    def _liq(p: dict[str, Any]) -> float:
        liq = p.get("liquidity") or {}
        return float(liq.get("usd") or 0)

    best = max(chain_pairs, key=_liq)
    price_str = best.get("priceUsd")
    if not price_str:
        return None
    try:
        return Decimal(str(price_str))
    except Exception:
        return None
