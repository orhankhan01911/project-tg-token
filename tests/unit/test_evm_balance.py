# tests/unit/test_evm_balance.py
"""Unit tests for ERC-20 and native balance reader functions."""

from __future__ import annotations

import httpx
import pytest
import respx

pytestmark = pytest.mark.unit

RPC_URL = "https://sepolia.base.org"  # Base Sepolia public RPC (no ALCHEMY_API_KEY in test env)
CONTRACT = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
ADDRESS = "0xd8da6bf26964af9d7eed9e03e53415d37aa96045"


def _rpc_ok(result: str) -> httpx.Response:
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})


# ── erc20_balance_of ─────────────────────────────────────────────────────────


@respx.mock
@pytest.mark.asyncio
async def test_erc20_balance_of_returns_raw_int():
    from app.chains.evm import erc20_balance_of

    # 100 USDC in raw units (6 decimals) = 100_000_000 = 0x5F5E100
    respx.post(RPC_URL).mock(
        return_value=_rpc_ok("0x0000000000000000000000000000000000000000000000000000000005F5E100")
    )
    async with httpx.AsyncClient() as http:
        bal = await erc20_balance_of(http, chain_id=84532, contract=CONTRACT, address=ADDRESS)
    assert bal == 100_000_000


@respx.mock
@pytest.mark.asyncio
async def test_erc20_balance_of_zero_returns_zero():
    from app.chains.evm import erc20_balance_of

    respx.post(RPC_URL).mock(return_value=_rpc_ok("0x" + "00" * 32))
    async with httpx.AsyncClient() as http:
        bal = await erc20_balance_of(http, chain_id=84532, contract=CONTRACT, address=ADDRESS)
    assert bal == 0


@respx.mock
@pytest.mark.asyncio
async def test_erc20_balance_of_empty_result_returns_zero():
    from app.chains.evm import erc20_balance_of

    respx.post(RPC_URL).mock(return_value=_rpc_ok("0x"))
    async with httpx.AsyncClient() as http:
        bal = await erc20_balance_of(http, chain_id=84532, contract=CONTRACT, address=ADDRESS)
    assert bal == 0


# ── eth_balance_of ───────────────────────────────────────────────────────────


@respx.mock
@pytest.mark.asyncio
async def test_eth_balance_of_returns_wei():
    from app.chains.evm import eth_balance_of

    # 1 ETH = 1e18 wei = 0xDE0B6B3A7640000
    respx.post(RPC_URL).mock(return_value=_rpc_ok("0xDE0B6B3A7640000"))
    async with httpx.AsyncClient() as http:
        bal = await eth_balance_of(http, chain_id=84532, address=ADDRESS)
    assert bal == 10**18


# ── erc20_decimals ───────────────────────────────────────────────────────────


@respx.mock
@pytest.mark.asyncio
async def test_erc20_decimals_returns_int():
    from app.chains.evm import erc20_decimals

    # USDC has 6 decimals = 0x6
    respx.post(RPC_URL).mock(
        return_value=_rpc_ok("0x0000000000000000000000000000000000000000000000000000000000000006")
    )
    async with httpx.AsyncClient() as http:
        d = await erc20_decimals(http, chain_id=84532, contract=CONTRACT)
    assert d == 6


@respx.mock
@pytest.mark.asyncio
async def test_erc20_decimals_falls_back_to_18_on_empty():
    from app.chains.evm import erc20_decimals

    respx.post(RPC_URL).mock(return_value=_rpc_ok("0x"))
    async with httpx.AsyncClient() as http:
        d = await erc20_decimals(http, chain_id=84532, contract=CONTRACT)
    assert d == 18


# ── chain_id_for ─────────────────────────────────────────────────────────────


def test_chain_id_for_known_chains():
    from app.chains.evm import chain_id_for

    assert chain_id_for("eth") == 1
    assert chain_id_for("base") == 8453
    assert chain_id_for("base-sepolia") == 84532


def test_chain_id_for_non_evm_returns_none():
    from app.chains.evm import chain_id_for

    assert chain_id_for("solana") is None
    assert chain_id_for("ton") is None
    assert chain_id_for("bnb") is None
