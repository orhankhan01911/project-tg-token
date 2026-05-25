"""Unit tests for the gate evaluator. Backed by mongomock-motor so we
exercise real Mongo query semantics with no daemon."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from mongomock_motor import AsyncMongoMockClient

from app.gates import Approve, Decline, NeedsVerify, evaluate
from app.settings import settings

pytestmark = pytest.mark.unit


@pytest.fixture
def db():
    client = AsyncMongoMockClient()
    return client["tg_token_test"]


@pytest.fixture
def http():
    return AsyncMock(spec=httpx.AsyncClient)


async def test_unregistered_chat_declines(db, http) -> None:
    decision = await evaluate(db, http, chat_id=-100123, tg_user_id=42)
    assert isinstance(decision, Decline)
    assert decision.reason == "chat_not_registered"


async def test_owner_is_auto_approved(db, http) -> None:
    await db.chats.insert_one({"_id": -100123, "owner_tg_id": 42})
    decision = await evaluate(db, http, chat_id=-100123, tg_user_id=42)
    assert isinstance(decision, Approve)
    assert decision.reason == "chat_owner"


async def test_whitelisted_user_is_approved(db, http) -> None:
    await db.chats.insert_one({"_id": -100123, "owner_tg_id": 1})
    await db.whitelist.insert_one({"chat_id": -100123, "tg_user_id": 42})

    decision = await evaluate(db, http, chat_id=-100123, tg_user_id=42)

    assert isinstance(decision, Approve)
    assert decision.reason == "whitelist"


async def test_stranger_needs_verify(db, http) -> None:
    """S2 change: a stranger no longer Declines outright; they get the
    chance to verify a wallet via SIWE in the Mini App."""
    await db.chats.insert_one({"_id": -100123, "owner_tg_id": 1})

    decision = await evaluate(db, http, chat_id=-100123, tg_user_id=42)

    assert isinstance(decision, NeedsVerify)
    assert decision.reason == "requires_verification"


async def test_fresh_siwe_verification_approves(db, http) -> None:
    await db.chats.insert_one({"_id": -100123, "owner_tg_id": 1})
    await db.verifications.insert_one(
        {
            "tg_user_id": 42,
            "chat_id": -100123,
            "address": "0xabc",
            "chain": "base-sepolia",
            "method": "siwe",
            "nonce": "n",
            "sig_or_txhash": "0xsig",
            "verified_at": datetime.now(tz=UTC),
        }
    )
    decision = await evaluate(db, http, chat_id=-100123, tg_user_id=42)
    assert isinstance(decision, Approve)
    # No gates configured → wallet_verified
    assert decision.reason == "wallet_verified"


async def test_stale_siwe_verification_does_not_approve(db, http) -> None:
    await db.chats.insert_one({"_id": -100123, "owner_tg_id": 1})
    stale = datetime.now(tz=UTC) - timedelta(seconds=settings.verification_ttl_seconds + 60)
    await db.verifications.insert_one(
        {
            "tg_user_id": 42,
            "chat_id": -100123,
            "address": "0xabc",
            "chain": "base-sepolia",
            "method": "siwe",
            "nonce": "n",
            "sig_or_txhash": "0xsig",
            "verified_at": stale,
        }
    )
    decision = await evaluate(db, http, chat_id=-100123, tg_user_id=42)
    assert isinstance(decision, NeedsVerify)


async def test_whitelist_is_chat_scoped(db, http) -> None:
    """Being whitelisted in chat A does not approve in chat B."""
    await db.chats.insert_one({"_id": -100123, "owner_tg_id": 1})
    await db.chats.insert_one({"_id": -100456, "owner_tg_id": 2})
    await db.whitelist.insert_one({"chat_id": -100123, "tg_user_id": 42})

    other_chat = await evaluate(db, http, chat_id=-100456, tg_user_id=42)

    assert isinstance(other_chat, NeedsVerify)
    assert other_chat.reason == "requires_verification"
