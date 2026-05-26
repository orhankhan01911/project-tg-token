"""Unit tests for app.chains.solana.spl_balance.

All HTTP calls are mocked via respx — no real network traffic.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.chains.solana import spl_balance

pytestmark = pytest.mark.unit

# ── helpers ──────────────────────────────────────────────────────────────────

TEST_API_KEY = "test-key"
HELIUS_URL = f"https://mainnet.helius-rpc.com/?api-key={TEST_API_KEY}"


def _mock_response(accounts: list[dict]) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"value": accounts},
    }


def _account(amount: str, decimals: int) -> dict:
    return {
        "account": {
            "data": {
                "parsed": {
                    "info": {
                        "tokenAmount": {
                            "amount": amount,
                            "decimals": decimals,
                        }
                    }
                }
            }
        }
    }


# ── tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_spl_balance_happy_path(monkeypatch):
    """Single token account → returns (amount, decimals)."""
    monkeypatch.setattr("app.chains.solana.settings.helius_api_key", TEST_API_KEY)
    payload = _mock_response([_account("5000000", 6)])

    with respx.mock:
        respx.post(HELIUS_URL).mock(return_value=httpx.Response(200, json=payload))
        async with httpx.AsyncClient() as http:
            bal, dec = await spl_balance(http, owner_address="ownerABC", mint="mintXYZ")

    assert bal == 5_000_000
    assert dec == 6


@pytest.mark.asyncio
async def test_spl_balance_multiple_accounts(monkeypatch):
    """Multiple token accounts for same mint → amounts are summed."""
    monkeypatch.setattr("app.chains.solana.settings.helius_api_key", TEST_API_KEY)
    payload = _mock_response(
        [
            _account("3000000", 6),
            _account("2000000", 6),
        ]
    )

    with respx.mock:
        respx.post(HELIUS_URL).mock(return_value=httpx.Response(200, json=payload))
        async with httpx.AsyncClient() as http:
            bal, dec = await spl_balance(http, owner_address="ownerABC", mint="mintXYZ")

    assert bal == 5_000_000
    assert dec == 6


@pytest.mark.asyncio
async def test_spl_balance_empty_value(monkeypatch):
    """Empty value list (owner holds no tokens) → (0, 0)."""
    monkeypatch.setattr("app.chains.solana.settings.helius_api_key", TEST_API_KEY)
    payload = _mock_response([])

    with respx.mock:
        respx.post(HELIUS_URL).mock(return_value=httpx.Response(200, json=payload))
        async with httpx.AsyncClient() as http:
            bal, dec = await spl_balance(http, owner_address="ownerABC", mint="mintXYZ")

    assert bal == 0
    assert dec == 0


@pytest.mark.asyncio
async def test_spl_balance_rpc_error(monkeypatch):
    """RPC-level error in response body → (0, 0)."""
    monkeypatch.setattr("app.chains.solana.settings.helius_api_key", TEST_API_KEY)
    error_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {"code": -32602, "message": "Invalid params"},
    }

    with respx.mock:
        respx.post(HELIUS_URL).mock(return_value=httpx.Response(200, json=error_payload))
        async with httpx.AsyncClient() as http:
            bal, dec = await spl_balance(http, owner_address="ownerABC", mint="mintXYZ")

    assert bal == 0
    assert dec == 0


@pytest.mark.asyncio
async def test_spl_balance_network_error(monkeypatch):
    """ConnectError (network down) → (0, 0) without raising."""
    monkeypatch.setattr("app.chains.solana.settings.helius_api_key", TEST_API_KEY)

    with respx.mock:
        respx.post(HELIUS_URL).mock(side_effect=httpx.ConnectError("connection refused"))
        async with httpx.AsyncClient() as http:
            bal, dec = await spl_balance(http, owner_address="ownerABC", mint="mintXYZ")

    assert bal == 0
    assert dec == 0
