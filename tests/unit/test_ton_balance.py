"""Unit tests for app.chains.ton.jetton_balance.

All tests are offline — tonapi.io is mocked via respx.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.chains.ton import jetton_balance

pytestmark = pytest.mark.unit

_OWNER = "EQtest"
_MASTER = "EQmaster"
_URL = f"https://tonapi.io/v2/accounts/{_OWNER}/jettons/{_MASTER}"


@pytest.mark.asyncio
async def test_jetton_balance_happy_path():
    """Valid response → (balance, decimals) returned correctly."""
    with respx.mock:
        respx.get(_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "balance": "1000000000",
                    "jetton": {"decimals": 9, "symbol": "UTYA"},
                },
            )
        )
        async with httpx.AsyncClient() as http:
            bal, dec = await jetton_balance(http, owner_address=_OWNER, jetton_master=_MASTER)
    assert bal == 1_000_000_000
    assert dec == 9


@pytest.mark.asyncio
async def test_jetton_balance_404_returns_zero():
    """404 (no jetton wallet) → (0, 9) safe default, no exception."""
    with respx.mock:
        respx.get(_URL).mock(return_value=httpx.Response(404))
        async with httpx.AsyncClient() as http:
            bal, dec = await jetton_balance(http, owner_address=_OWNER, jetton_master=_MASTER)
    assert bal == 0
    assert dec == 9


@pytest.mark.asyncio
async def test_jetton_balance_zero_string():
    """balance field "0" → (0, decimals), not an error."""
    with respx.mock:
        respx.get(_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "balance": "0",
                    "jetton": {"decimals": 9, "symbol": "UTYA"},
                },
            )
        )
        async with httpx.AsyncClient() as http:
            bal, dec = await jetton_balance(http, owner_address=_OWNER, jetton_master=_MASTER)
    assert bal == 0
    assert dec == 9


@pytest.mark.asyncio
async def test_jetton_balance_custom_decimals():
    """decimals field from response is propagated correctly (e.g. 6 for USDT-like)."""
    with respx.mock:
        respx.get(_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "balance": "5000000",
                    "jetton": {"decimals": 6, "symbol": "jUSDT"},
                },
            )
        )
        async with httpx.AsyncClient() as http:
            bal, dec = await jetton_balance(http, owner_address=_OWNER, jetton_master=_MASTER)
    assert bal == 5_000_000
    assert dec == 6


@pytest.mark.asyncio
async def test_jetton_balance_network_error_returns_zero():
    """ConnectError → (0, 9) safe default, does not propagate the exception."""
    with respx.mock:
        respx.get(_URL).mock(side_effect=httpx.ConnectError("connection refused"))
        async with httpx.AsyncClient() as http:
            bal, dec = await jetton_balance(http, owner_address=_OWNER, jetton_master=_MASTER)
    assert bal == 0
    assert dec == 9
