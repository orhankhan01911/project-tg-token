"""Unit tests for app.pricing — DexScreener USD price lookup."""

from decimal import Decimal

import httpx
import pytest
import respx

from app.pricing import get_token_price_usd

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_returns_highest_liquidity_price():
    """Two pairs on 'base' chain with different liquidities → price from highest-liquidity pair."""
    with respx.mock:
        respx.get("https://api.dexscreener.com/latest/dex/tokens/0xabc").mock(
            return_value=httpx.Response(
                200,
                json={
                    "pairs": [
                        {"chainId": "base", "priceUsd": "0.005", "liquidity": {"usd": 100000}},
                        {"chainId": "base", "priceUsd": "0.008", "liquidity": {"usd": 50000}},
                    ]
                },
            )
        )
        async with httpx.AsyncClient() as http:
            price = await get_token_price_usd(http, chain_slug="base", contract_or_mint="0xabc")
        assert price == Decimal("0.005")  # highest liquidity pair


@pytest.mark.asyncio
async def test_wrong_chain_filtered_out():
    """Pairs exist but all on 'ethereum', queried as 'base' → returns None."""
    with respx.mock:
        respx.get("https://api.dexscreener.com/latest/dex/tokens/0xdef").mock(
            return_value=httpx.Response(
                200,
                json={
                    "pairs": [
                        {"chainId": "ethereum", "priceUsd": "1.23", "liquidity": {"usd": 500000}},
                        {"chainId": "ethereum", "priceUsd": "1.24", "liquidity": {"usd": 200000}},
                    ]
                },
            )
        )
        async with httpx.AsyncClient() as http:
            price = await get_token_price_usd(http, chain_slug="base", contract_or_mint="0xdef")
        assert price is None


@pytest.mark.asyncio
async def test_empty_pairs_list():
    """DexScreener returns empty pairs list → returns None."""
    with respx.mock:
        respx.get("https://api.dexscreener.com/latest/dex/tokens/0xghi").mock(
            return_value=httpx.Response(200, json={"pairs": []})
        )
        async with httpx.AsyncClient() as http:
            price = await get_token_price_usd(http, chain_slug="base", contract_or_mint="0xghi")
        assert price is None


@pytest.mark.asyncio
async def test_price_usd_missing_returns_none():
    """Best pair has priceUsd as None/missing → returns None."""
    with respx.mock:
        respx.get("https://api.dexscreener.com/latest/dex/tokens/0xjkl").mock(
            return_value=httpx.Response(
                200,
                json={
                    "pairs": [
                        {"chainId": "base", "priceUsd": None, "liquidity": {"usd": 100000}},
                    ]
                },
            )
        )
        async with httpx.AsyncClient() as http:
            price = await get_token_price_usd(http, chain_slug="base", contract_or_mint="0xjkl")
        assert price is None


@pytest.mark.asyncio
async def test_http_error_returns_none():
    """ConnectError → returns None (does not raise)."""
    with respx.mock:
        respx.get("https://api.dexscreener.com/latest/dex/tokens/0xmno").mock(
            side_effect=httpx.ConnectError("connection refused")
        )
        async with httpx.AsyncClient() as http:
            price = await get_token_price_usd(http, chain_slug="base", contract_or_mint="0xmno")
        assert price is None
