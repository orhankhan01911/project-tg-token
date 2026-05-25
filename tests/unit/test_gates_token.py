# tests/unit/test_gates_token.py
"""Unit tests for token-gate balance checking in evaluate()."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from mongomock_motor import AsyncMongoMockClient

from app.gates import Approve, Decline, NeedsVerify, evaluate

pytestmark = pytest.mark.unit


def _now() -> datetime:
    return datetime.now(tz=UTC)


@pytest.fixture
def db():
    client = AsyncMongoMockClient()
    return client["tg_token_test"]


@pytest.fixture
def http():
    return AsyncMock(spec=httpx.AsyncClient)


async def _seed(db, *, owner_id=999, user_id=1, chat_id=-1001, verified=True, gates=None):
    """Insert a registered chat, optional verification, optional gates."""
    await db.chats.insert_one({"_id": chat_id, "owner_tg_id": owner_id, "title": "Test"})
    if verified:
        await db.verifications.insert_one(
            {
                "tg_user_id": user_id,
                "chat_id": chat_id,
                "address": "0xdeadbeef",
                "chain": "base-sepolia",
                "verified_at": _now(),
            }
        )
    for g in gates or []:
        await db.gates.insert_one(g)


# ── no gates ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_verified_no_gates_approves(db, http):
    await _seed(db, verified=True, gates=[])
    result = await evaluate(db, http, chat_id=-1001, tg_user_id=1)
    assert isinstance(result, Approve)
    assert result.reason == "wallet_verified"


# ── single ERC-20 gate ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gate_passes_when_balance_sufficient(db, http):
    await _seed(
        db,
        gates=[
            {
                "_id": "g1",
                "chat_id": -1001,
                "kind": "token",
                "chain": "base",
                "contract": "0xusdc",
                "threshold": "1000000",
            }
        ],
    )
    with patch("app.gates.erc20_balance_of", new=AsyncMock(return_value=5_000_000)):
        result = await evaluate(db, http, chat_id=-1001, tg_user_id=1)
    assert isinstance(result, Approve)
    assert result.reason == "token_gate_passed"


@pytest.mark.asyncio
async def test_gate_declines_when_balance_insufficient(db, http):
    await _seed(
        db,
        gates=[
            {
                "_id": "g1",
                "chat_id": -1001,
                "kind": "token",
                "chain": "base",
                "contract": "0xusdc",
                "threshold": "1000000",
            }
        ],
    )
    with patch("app.gates.erc20_balance_of", new=AsyncMock(return_value=500_000)):
        result = await evaluate(db, http, chat_id=-1001, tg_user_id=1)
    assert isinstance(result, Decline)
    assert result.reason == "insufficient_balance"


@pytest.mark.asyncio
async def test_gate_exact_threshold_approves(db, http):
    await _seed(
        db,
        gates=[
            {
                "_id": "g1",
                "chat_id": -1001,
                "kind": "token",
                "chain": "base",
                "contract": "0xusdc",
                "threshold": "1000000",
            }
        ],
    )
    with patch("app.gates.erc20_balance_of", new=AsyncMock(return_value=1_000_000)):
        result = await evaluate(db, http, chat_id=-1001, tg_user_id=1)
    assert isinstance(result, Approve)


# ── native ETH gate (no contract) ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_native_eth_gate_passes(db, http):
    await _seed(
        db,
        gates=[
            {
                "_id": "g1",
                "chat_id": -1001,
                "kind": "token",
                "chain": "eth",
                "contract": None,
                "threshold": str(10**17),  # 0.1 ETH
            }
        ],
    )
    with patch("app.gates.eth_balance_of", new=AsyncMock(return_value=10**18)):
        result = await evaluate(db, http, chat_id=-1001, tg_user_id=1)
    assert isinstance(result, Approve)


@pytest.mark.asyncio
async def test_native_eth_gate_declines(db, http):
    await _seed(
        db,
        gates=[
            {
                "_id": "g1",
                "chat_id": -1001,
                "kind": "token",
                "chain": "eth",
                "contract": None,
                "threshold": str(10**18),  # 1 ETH
            }
        ],
    )
    with patch("app.gates.eth_balance_of", new=AsyncMock(return_value=10**17)):
        result = await evaluate(db, http, chat_id=-1001, tg_user_id=1)
    assert isinstance(result, Decline)


# ── multiple gates (AND logic) ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_multiple_gates_all_pass(db, http):
    await _seed(
        db,
        gates=[
            {
                "_id": "g1",
                "chat_id": -1001,
                "kind": "token",
                "chain": "base",
                "contract": "0xusdc",
                "threshold": "1000000",
            },
            {
                "_id": "g2",
                "chat_id": -1001,
                "kind": "token",
                "chain": "eth",
                "contract": None,
                "threshold": str(10**17),
            },
        ],
    )
    with (
        patch("app.gates.erc20_balance_of", new=AsyncMock(return_value=5_000_000)),
        patch("app.gates.eth_balance_of", new=AsyncMock(return_value=10**18)),
    ):
        result = await evaluate(db, http, chat_id=-1001, tg_user_id=1)
    assert isinstance(result, Approve)


@pytest.mark.asyncio
async def test_multiple_gates_one_fails_declines(db, http):
    await _seed(
        db,
        gates=[
            {
                "_id": "g1",
                "chat_id": -1001,
                "kind": "token",
                "chain": "base",
                "contract": "0xusdc",
                "threshold": "1000000",
            },
            {
                "_id": "g2",
                "chat_id": -1001,
                "kind": "token",
                "chain": "eth",
                "contract": None,
                "threshold": str(10**18),
            },
        ],
    )
    with (
        patch("app.gates.erc20_balance_of", new=AsyncMock(return_value=5_000_000)),
        patch("app.gates.eth_balance_of", new=AsyncMock(return_value=10**14)),
    ):  # too low
        result = await evaluate(db, http, chat_id=-1001, tg_user_id=1)
    assert isinstance(result, Decline)


# ── non-EVM gate is skipped ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_solana_gate_skipped_approves(db, http):
    """Solana gates have no chain_id mapping yet — skip and approve."""
    await _seed(
        db,
        gates=[
            {
                "_id": "g1",
                "chat_id": -1001,
                "kind": "token",
                "chain": "solana",
                "contract": "So111...",
                "threshold": "1000000",
            }
        ],
    )
    result = await evaluate(db, http, chat_id=-1001, tg_user_id=1)
    assert isinstance(result, Approve)


# ── unverified user still hits NeedsVerify ───────────────────────────────────


@pytest.mark.asyncio
async def test_no_verification_needs_verify(db, http):
    await _seed(
        db,
        verified=False,
        gates=[
            {
                "_id": "g1",
                "chat_id": -1001,
                "kind": "token",
                "chain": "base",
                "contract": "0xusdc",
                "threshold": "1000000",
            }
        ],
    )
    result = await evaluate(db, http, chat_id=-1001, tg_user_id=1)
    assert isinstance(result, NeedsVerify)
