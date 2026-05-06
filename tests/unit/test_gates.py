"""Unit tests for the whitelist-backed gate evaluator. Backed by
mongomock-motor so we exercise real Mongo query semantics with no daemon.
"""

from __future__ import annotations

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.gates import Approve, Decline, evaluate

pytestmark = pytest.mark.unit


@pytest.fixture
def db():
    client = AsyncMongoMockClient()
    return client["tg_token_test"]


async def test_unregistered_chat_declines(db) -> None:
    decision = await evaluate(db, chat_id=-100123, tg_user_id=42)
    assert isinstance(decision, Decline)
    assert decision.reason == "chat_not_registered"


async def test_owner_is_auto_approved(db) -> None:
    await db.chats.insert_one({"_id": -100123, "owner_tg_id": 42})
    decision = await evaluate(db, chat_id=-100123, tg_user_id=42)
    assert isinstance(decision, Approve)
    assert decision.reason == "chat_owner"


async def test_whitelisted_user_is_approved(db) -> None:
    await db.chats.insert_one({"_id": -100123, "owner_tg_id": 1})
    await db.whitelist.insert_one({"chat_id": -100123, "tg_user_id": 42})

    decision = await evaluate(db, chat_id=-100123, tg_user_id=42)

    assert isinstance(decision, Approve)
    assert decision.reason == "whitelist"


async def test_stranger_is_declined(db) -> None:
    await db.chats.insert_one({"_id": -100123, "owner_tg_id": 1})

    decision = await evaluate(db, chat_id=-100123, tg_user_id=42)

    assert isinstance(decision, Decline)
    assert decision.reason == "not_whitelisted"


async def test_whitelist_is_chat_scoped(db) -> None:
    """Being whitelisted in chat A does not approve in chat B."""
    await db.chats.insert_one({"_id": -100123, "owner_tg_id": 1})
    await db.chats.insert_one({"_id": -100456, "owner_tg_id": 2})
    await db.whitelist.insert_one({"chat_id": -100123, "tg_user_id": 42})

    other_chat = await evaluate(db, chat_id=-100456, tg_user_id=42)

    assert isinstance(other_chat, Decline)
    assert other_chat.reason == "not_whitelisted"
