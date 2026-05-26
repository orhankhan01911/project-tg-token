"""Unit tests for OR-logic token balance gate evaluator."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.balance_gate import evaluate_token_gate
from app.models.gate import Chain
from app.models.token_gate import TokenGate, TokenSpec

pytestmark = pytest.mark.unit


def _make_gate(min_usd: str = "10") -> TokenGate:
    return TokenGate(
        chat_id=-1001,
        min_usd_value=min_usd,
        tokens=[
            TokenSpec(name="Brett", chain=Chain.BASE, contract="0xBrett"),
            TokenSpec(name="Wojak", chain=Chain.ETH, contract="0xWojak"),
            TokenSpec(name="Troll", chain=Chain.SOLANA, contract="TrollMint"),
        ],
    )


ADDRESSES = {"evm": "0xuser", "ton": "EQuser", "solana": "SolUser"}


@pytest.mark.asyncio
async def test_first_token_passes() -> None:
    """Brett has $15 → return True immediately; Wojak/Troll should never be evaluated."""
    gate = _make_gate()
    http = AsyncMock(spec=httpx.AsyncClient)

    with (
        patch("app.balance_gate.erc20_balance_of", new_callable=AsyncMock) as mock_bal,
        patch("app.balance_gate.erc20_decimals", new_callable=AsyncMock) as mock_dec,
        patch("app.balance_gate.get_token_price_usd", new_callable=AsyncMock) as mock_price,
        patch("app.balance_gate.spl_balance", new_callable=AsyncMock) as mock_sol,
    ):
        # 1 500 tokens with 18 decimals x $0.01 = $15
        mock_bal.return_value = 1_500_000_000_000_000_000_000  # 1500 tokens
        mock_dec.return_value = 18
        mock_price.return_value = Decimal("0.01")  # $0.01/token → $15 total

        result = await evaluate_token_gate(http, gate=gate, addresses=ADDRESSES)

    assert result is True
    # Only one token (Brett on BASE) should have been evaluated — erc20_balance_of called once
    assert mock_bal.call_count == 1
    mock_sol.assert_not_called()


@pytest.mark.asyncio
async def test_only_last_token_passes() -> None:
    """Brett=0, Wojak=0, Troll=$12 → True."""
    gate = _make_gate()
    http = AsyncMock(spec=httpx.AsyncClient)

    with (
        patch("app.balance_gate.erc20_balance_of", new_callable=AsyncMock) as mock_bal,
        patch("app.balance_gate.erc20_decimals", new_callable=AsyncMock) as mock_dec,
        patch("app.balance_gate.get_token_price_usd", new_callable=AsyncMock) as mock_price,
        patch("app.balance_gate.spl_balance", new_callable=AsyncMock) as mock_sol,
    ):
        mock_bal.return_value = 0  # Brett + Wojak both 0
        mock_dec.return_value = 18
        # 12_000_000 raw at 6 decimals = 12 tokens x $1.00 = $12
        mock_sol.return_value = (12_000_000, 6)
        mock_price.return_value = Decimal("1.00")

        result = await evaluate_token_gate(http, gate=gate, addresses=ADDRESSES)

    assert result is True
    # get_token_price_usd not called for EVM tokens (balance=0 short-circuits),
    # but IS called for Troll
    mock_sol.assert_called_once()


@pytest.mark.asyncio
async def test_all_fail() -> None:
    """All balances zero → False."""
    gate = _make_gate()
    http = AsyncMock(spec=httpx.AsyncClient)

    with (
        patch("app.balance_gate.erc20_balance_of", new_callable=AsyncMock) as mock_bal,
        patch("app.balance_gate.erc20_decimals", new_callable=AsyncMock) as mock_dec,
        patch("app.balance_gate.get_token_price_usd", new_callable=AsyncMock) as mock_price,
        patch("app.balance_gate.spl_balance", new_callable=AsyncMock) as mock_sol,
    ):
        mock_bal.return_value = 0
        mock_dec.return_value = 18
        mock_sol.return_value = (0, 6)
        mock_price.return_value = Decimal("100.00")

        result = await evaluate_token_gate(http, gate=gate, addresses=ADDRESSES)

    assert result is False
    mock_price.assert_not_called()  # price never fetched — all balances zero


@pytest.mark.asyncio
async def test_price_unavailable_for_some_but_another_passes() -> None:
    """Wojak price=None (fails gracefully), Brett has $20 → True."""
    gate = _make_gate()
    http = AsyncMock(spec=httpx.AsyncClient)

    call_count = 0

    async def price_side_effect(
        http_client: object, *, chain_slug: str, contract_or_mint: str
    ) -> Decimal | None:
        nonlocal call_count
        call_count += 1
        if contract_or_mint == "0xBrett":
            return Decimal("0.02")  # $0.02 x 1000 tokens = $20
        return None  # Wojak price unavailable

    with (
        patch("app.balance_gate.erc20_balance_of", new_callable=AsyncMock) as mock_bal,
        patch("app.balance_gate.erc20_decimals", new_callable=AsyncMock) as mock_dec,
        patch("app.balance_gate.get_token_price_usd", side_effect=price_side_effect),
        patch("app.balance_gate.spl_balance", new_callable=AsyncMock),
    ):
        mock_bal.return_value = 1_000_000_000_000_000_000_000  # 1000 tokens (18 dec)
        mock_dec.return_value = 18

        result = await evaluate_token_gate(http, gate=gate, addresses=ADDRESSES)

    assert result is True


@pytest.mark.asyncio
async def test_all_prices_unavailable() -> None:
    """All tokens have non-zero balance but all prices return None → False."""
    gate = _make_gate()
    http = AsyncMock(spec=httpx.AsyncClient)

    with (
        patch("app.balance_gate.erc20_balance_of", new_callable=AsyncMock) as mock_bal,
        patch("app.balance_gate.erc20_decimals", new_callable=AsyncMock) as mock_dec,
        patch("app.balance_gate.get_token_price_usd", new_callable=AsyncMock) as mock_price,
        patch("app.balance_gate.spl_balance", new_callable=AsyncMock) as mock_sol,
    ):
        mock_bal.return_value = 999_000_000_000_000_000_000  # non-zero
        mock_dec.return_value = 18
        mock_sol.return_value = (999_000_000, 6)
        mock_price.return_value = None  # no price for any token

        result = await evaluate_token_gate(http, gate=gate, addresses=ADDRESSES)

    assert result is False


@pytest.mark.asyncio
async def test_no_evm_address_solana_still_checked() -> None:
    """No EVM address provided — Brett/Wojak skipped, Troll qualifies → True."""
    gate = _make_gate()
    http = AsyncMock(spec=httpx.AsyncClient)
    addresses_no_evm = {"ton": "EQuser", "solana": "SolUser"}  # no "evm" key

    with (
        patch("app.balance_gate.erc20_balance_of", new_callable=AsyncMock) as mock_bal,
        patch("app.balance_gate.erc20_decimals", new_callable=AsyncMock) as mock_dec,
        patch("app.balance_gate.get_token_price_usd", new_callable=AsyncMock) as mock_price,
        patch("app.balance_gate.spl_balance", new_callable=AsyncMock) as mock_sol,
    ):
        mock_sol.return_value = (500_000_000, 6)  # 500 tokens
        mock_price.return_value = Decimal("1.00")  # $1/token → $500

        result = await evaluate_token_gate(http, gate=gate, addresses=addresses_no_evm)

    assert result is True
    mock_bal.assert_not_called()
    mock_dec.assert_not_called()
    mock_sol.assert_called_once()


@pytest.mark.asyncio
async def test_min_usd_not_met() -> None:
    """Brett has $8 (below $10 threshold) → False."""
    gate = _make_gate(min_usd="10")
    http = AsyncMock(spec=httpx.AsyncClient)

    with (
        patch("app.balance_gate.erc20_balance_of", new_callable=AsyncMock) as mock_bal,
        patch("app.balance_gate.erc20_decimals", new_callable=AsyncMock) as mock_dec,
        patch("app.balance_gate.get_token_price_usd", new_callable=AsyncMock) as mock_price,
        patch("app.balance_gate.spl_balance", new_callable=AsyncMock) as mock_sol,
    ):
        # 800 tokens x $0.01 = $8 < $10
        mock_bal.return_value = 800_000_000_000_000_000_000  # 800 tokens at 18 dec
        mock_dec.return_value = 18
        mock_price.return_value = Decimal("0.01")
        mock_sol.return_value = (0, 6)

        result = await evaluate_token_gate(http, gate=gate, addresses=ADDRESSES)

    assert result is False
