"""Unit tests for /settings, /delgate, /whitelist, /purge_enable, /recheck commands."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from mongomock_motor import AsyncMongoMockClient

from app.gates import Approve, Decline

pytestmark = pytest.mark.unit


@pytest.fixture
def db():
    client = AsyncMongoMockClient()
    return client["tg_token_test"]


@pytest.fixture
def http():
    return AsyncMock(spec=httpx.AsyncClient)


def _make_message(text: str, user_id: int = 42) -> MagicMock:
    msg = AsyncMock()
    msg.text = text
    msg.from_user = MagicMock()
    msg.from_user.id = user_id
    msg.chat.type = "private"
    msg.answer = AsyncMock()
    return msg


async def _seed_chat(db, chat_id=-1001, owner_id=42):
    await db.chats.insert_one(
        {
            "_id": chat_id,
            "owner_tg_id": owner_id,
            "title": "Test Chat",
            "purge_enabled": False,
        }
    )


# ── /settings ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_settings_lists_gates(db):
    await _seed_chat(db)
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
    from app.bot import _cmd_settings_text

    text = await _cmd_settings_text(db, owner_id=42)
    assert "Test Chat" in text
    assert "base" in text
    assert "0xusdc" in text


@pytest.mark.asyncio
async def test_settings_no_chats(db):
    from app.bot import _cmd_settings_text

    text = await _cmd_settings_text(db, owner_id=42)
    assert "No registered" in text


# ── /delgate ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delgate_removes_gate(db):
    await _seed_chat(db)
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
    from app.bot import _delete_gate_by_index

    ok = await _delete_gate_by_index(db, owner_id=42, index=1)
    assert ok is True
    assert await db.gates.count_documents({"chat_id": -1001}) == 0


@pytest.mark.asyncio
async def test_delgate_invalid_index(db):
    await _seed_chat(db)
    from app.bot import _delete_gate_by_index

    ok = await _delete_gate_by_index(db, owner_id=42, index=99)
    assert ok is False


# ── /whitelist ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_whitelist_add(db):
    await _seed_chat(db)
    from app.bot import _whitelist_add

    await _whitelist_add(db, owner_id=42, target_user_id=999)
    doc = await db.whitelist.find_one({"chat_id": -1001, "tg_user_id": 999})
    assert doc is not None


@pytest.mark.asyncio
async def test_whitelist_remove(db):
    await _seed_chat(db)
    await db.whitelist.insert_one({"chat_id": -1001, "tg_user_id": 999})
    from app.bot import _whitelist_remove

    await _whitelist_remove(db, owner_id=42, target_user_id=999)
    assert await db.whitelist.count_documents({"chat_id": -1001, "tg_user_id": 999}) == 0


# ── /purge_enable / /purge_disable ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_purge_enable(db):
    await _seed_chat(db)
    from app.bot import _set_purge_enabled

    await _set_purge_enabled(db, owner_id=42, enabled=True)
    chat = await db.chats.find_one({"_id": -1001})
    assert chat["purge_enabled"] is True


@pytest.mark.asyncio
async def test_purge_disable(db):
    await _seed_chat(db, chat_id=-1001)
    await db.chats.update_one({"_id": -1001}, {"$set": {"purge_enabled": True}})
    from app.bot import _set_purge_enabled

    await _set_purge_enabled(db, owner_id=42, enabled=False)
    chat = await db.chats.find_one({"_id": -1001})
    assert chat["purge_enabled"] is False


# ── /recheck ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_recheck_approve(db, http):
    await _seed_chat(db)
    await db.verifications.insert_one(
        {
            "tg_user_id": 42,
            "chat_id": -1001,
            "address": "0xabc",
            "chain": "base",
            "verified_at": datetime.now(tz=UTC),
        }
    )
    from app.bot import _recheck_user

    with patch("app.bot.evaluate", new=AsyncMock(return_value=Approve(reason="token_gate_passed"))):
        result = await _recheck_user(db, http, tg_user_id=42)
    assert "✅" in result


@pytest.mark.asyncio
async def test_recheck_decline(db, http):
    await _seed_chat(db)
    await db.verifications.insert_one(
        {
            "tg_user_id": 42,
            "chat_id": -1001,
            "address": "0xabc",
            "chain": "base",
            "verified_at": datetime.now(tz=UTC),
        }
    )
    from app.bot import _recheck_user

    with patch(
        "app.bot.evaluate", new=AsyncMock(return_value=Decline(reason="insufficient_balance"))
    ):
        result = await _recheck_user(db, http, tg_user_id=42)
    assert "❌" in result


@pytest.mark.asyncio
async def test_recheck_no_verification(db, http):
    await _seed_chat(db)
    from app.bot import _recheck_user

    result = await _recheck_user(db, http, tg_user_id=42)
    assert "no verified wallet" in result.lower() or "no verification" in result.lower()
