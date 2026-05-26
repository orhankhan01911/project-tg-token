# tests/unit/test_gates_token_basket.py
"""Unit tests for the token-balance OR-gate branch in evaluate()."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from mongomock_motor import AsyncMongoMockClient

from app.gates import Approve, Decline, NeedsVerify, evaluate
from app.models.gate import Chain
from app.models.token_gate import TokenGate, TokenSpec

pytestmark = pytest.mark.unit


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _make_gate(chat_id: int = -1001) -> TokenGate:
    return TokenGate(
        chat_id=chat_id,
        min_usd_value="10",
        tokens=[
            TokenSpec(name="Brett", chain=Chain.BASE, contract="0xbrettpill"),
        ],
    )


@pytest.fixture
def db():
    client = AsyncMongoMockClient()
    return client["tg_token_test"]


@pytest.fixture
def http():
    return AsyncMock(spec=httpx.AsyncClient)


async def _seed(
    db,
    *,
    owner_id: int = 999,
    user_id: int = 1,
    chat_id: int = -1001,
    verified: bool = True,
    address: str = "0xdeadbeef",
) -> None:
    """Insert a registered chat and optional verification (no AND-logic gates)."""
    await db.chats.insert_one({"_id": chat_id, "owner_tg_id": owner_id, "title": "Test"})
    if verified:
        await db.verifications.insert_one(
            {
                "tg_user_id": user_id,
                "chat_id": chat_id,
                "address": address,
                "chain": "base",
                "verified_at": _now(),
            }
        )


# ── token gate passes → Approve ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_token_gate_passes_approve(db, http):
    """When load_token_gate returns a gate and evaluate_token_gate returns True → Approve."""
    await _seed(db)
    gate = _make_gate()

    with (
        patch("app.gates.load_token_gate", new=AsyncMock(return_value=gate)),
        patch("app.gates.evaluate_token_gate", new=AsyncMock(return_value=True)),
    ):
        result = await evaluate(db, http, chat_id=-1001, tg_user_id=1)

    assert isinstance(result, Approve)
    assert result.reason == "token_balance_gate_passed"


# ── token gate fails → Decline ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_token_gate_fails_decline(db, http):
    """When evaluate_token_gate returns False → Decline(insufficient_token_balance)."""
    await _seed(db)
    gate = _make_gate()

    with (
        patch("app.gates.load_token_gate", new=AsyncMock(return_value=gate)),
        patch("app.gates.evaluate_token_gate", new=AsyncMock(return_value=False)),
    ):
        result = await evaluate(db, http, chat_id=-1001, tg_user_id=1)

    assert isinstance(result, Decline)
    assert result.reason == "insufficient_token_balance"
    assert result.message is not None
    assert "/verify" in result.message


# ── no token_gate doc → falls through to AND-logic gates ─────────────────────


@pytest.mark.asyncio
async def test_no_token_gate_falls_through_to_and_gates(db, http):
    """When load_token_gate returns None the AND-gate path (_check_gates) is used."""
    await _seed(db)
    # No AND-logic gates either → wallet_verified
    with patch("app.gates.load_token_gate", new=AsyncMock(return_value=None)):
        result = await evaluate(db, http, chat_id=-1001, tg_user_id=1)

    assert isinstance(result, Approve)
    assert result.reason == "wallet_verified"


@pytest.mark.asyncio
async def test_no_token_gate_and_gate_decline(db, http):
    """load_token_gate=None + AND-gate balance too low → Decline from _check_gates."""
    await _seed(db)
    # Insert an AND-logic gate in db.gates
    await db.gates.insert_one(
        {
            "_id": "g1",
            "chat_id": -1001,
            "kind": "token",
            "chain": "base",
            "contract": "0xusdc",
            "threshold": "1000000",
        }
    )

    with (
        patch("app.gates.load_token_gate", new=AsyncMock(return_value=None)),
        patch("app.gates.erc20_balance_of", new=AsyncMock(return_value=0)),
    ):
        result = await evaluate(db, http, chat_id=-1001, tg_user_id=1)

    assert isinstance(result, Decline)
    assert result.reason == "insufficient_balance"


# ── user has no verified wallet → Decline with /verify prompt ─────────────────


@pytest.mark.asyncio
async def test_token_gate_no_verification_decline(db, http):
    """User has no dust-verified wallet → NeedsVerify (not yet past verification step)."""
    await _seed(db, verified=False)
    gate = _make_gate()

    with patch("app.gates.load_token_gate", new=AsyncMock(return_value=gate)):
        result = await evaluate(db, http, chat_id=-1001, tg_user_id=1)

    # Verification check runs before the token gate branch — so NeedsVerify fires.
    assert isinstance(result, NeedsVerify)
    assert result.reason == "requires_verification"


@pytest.mark.asyncio
async def test_token_gate_verified_but_no_address_decline(db, http):
    """Verified row exists but has no 'address' field → Decline(no_verified_wallet)."""
    # Insert chat + a verification row without an address field
    await db.chats.insert_one({"_id": -1001, "owner_tg_id": 999, "title": "Test"})
    await db.verifications.insert_one(
        {
            "tg_user_id": 1,
            "chat_id": -1001,
            # deliberately omit "address"
            "chain": "base",
            "verified_at": _now(),
        }
    )
    gate = _make_gate()

    with (
        patch("app.gates.load_token_gate", new=AsyncMock(return_value=gate)),
        patch("app.gates.evaluate_token_gate", new=AsyncMock(return_value=True)),
    ):
        result = await evaluate(db, http, chat_id=-1001, tg_user_id=1)

    assert isinstance(result, Decline)
    assert result.reason == "no_verified_wallet"
    assert result.message is not None
    assert "/verify" in result.message
