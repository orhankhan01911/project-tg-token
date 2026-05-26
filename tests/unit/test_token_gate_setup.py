"""Unit tests for /settokengate command."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.bot import on_set_token_gate

pytestmark = pytest.mark.unit


@pytest.fixture
def db():
    client = AsyncMongoMockClient()
    return client["tg_token_test"]


def _make_message(user_id: int = 42) -> MagicMock:
    msg = AsyncMock()
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.answer = AsyncMock()
    return msg


async def _seed_chat(db, chat_id: int = -1001, owner_id: int = 42) -> None:
    await db.chats.insert_one(
        {
            "_id": chat_id,
            "owner_tg_id": owner_id,
            "title": "Test Chat",
        }
    )


@pytest.mark.asyncio
async def test_settokengate_saves_correct_document(db):
    """Handler should upsert a token_gates document with the 4-token basket."""
    await _seed_chat(db, chat_id=-1001, owner_id=42)
    msg = _make_message(user_id=42)

    await on_set_token_gate(msg, db)

    # Confirm the gate was written.
    doc = await db.token_gates.find_one({"chat_id": -1001})
    assert doc is not None, "token_gate document should have been created"
    assert doc["min_usd_value"] == "10"

    token_names = [t["name"] for t in doc["tokens"]]
    assert "Brett" in token_names
    assert "Wojak" in token_names
    assert "Utya" in token_names
    assert "Troll" in token_names
    assert len(doc["tokens"]) == 4

    # Contracts are correct.
    by_name = {t["name"]: t for t in doc["tokens"]}
    assert by_name["Brett"]["chain"] == "base"
    assert by_name["Brett"]["contract"] == "0x532f27101965dd16442e59d40670faf5ebb142e4"
    assert by_name["Wojak"]["chain"] == "eth"
    assert by_name["Troll"]["chain"] == "solana"
    assert by_name["Utya"]["chain"] == "ton"

    # User got a success message.
    msg.answer.assert_called_once()
    reply_text = msg.answer.call_args[0][0]
    assert "Token gate configured" in reply_text
    assert "Brett" in reply_text


@pytest.mark.asyncio
async def test_settokengate_no_chat_returns_error(db):
    """When caller owns no registered chat, handler should return an error message."""
    msg = _make_message(user_id=99)  # no chat seeded for this user

    await on_set_token_gate(msg, db)

    msg.answer.assert_called_once()
    reply_text = msg.answer.call_args[0][0]
    assert "No registered group" in reply_text

    # No gate should have been written.
    count = await db.token_gates.count_documents({})
    assert count == 0


@pytest.mark.asyncio
async def test_settokengate_upserts_on_second_call(db):
    """Calling /settokengate twice should upsert, not create a duplicate."""
    await _seed_chat(db, chat_id=-1001, owner_id=42)
    msg = _make_message(user_id=42)

    await on_set_token_gate(msg, db)
    await on_set_token_gate(msg, db)

    count = await db.token_gates.count_documents({"chat_id": -1001})
    assert count == 1, "second call should upsert, not insert a second document"
