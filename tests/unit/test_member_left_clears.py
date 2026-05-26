"""Unit tests for on_chat_member_left — verifications wiped on leave/kick."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from aiogram.types import Chat, ChatMemberUpdated, User
from mongomock_motor import AsyncMongoMockClient

pytestmark = pytest.mark.unit


def _make_db():
    return AsyncMongoMockClient()["tg_token_test"]


def _make_member_update(*, chat_id: int, user_id: int, new_status: str) -> MagicMock:
    update = MagicMock(spec=ChatMemberUpdated)
    update.chat = Chat(id=chat_id, type="supergroup")
    update.from_user = User(id=user_id, is_bot=False, first_name="Tester")
    update.new_chat_member = MagicMock()
    update.new_chat_member.status = new_status
    update.new_chat_member.user = User(id=user_id, is_bot=False, first_name="Tester")
    return update


async def test_member_left_clears_verification() -> None:
    """Voluntary leave wipes verifications, dust_requests, and pending_joins."""
    from app.bot import on_chat_member_left

    db = _make_db()
    await db.verifications.insert_one(
        {
            "tg_user_id": 42,
            "chat_id": -1001,
            "address": "0xabc",
            "chain": "base-sepolia",
            "verified_at": datetime.now(tz=UTC),
        }
    )
    await db.dust_requests.insert_one(
        {"_id": "42:-1001", "tg_user_id": 42, "chat_id": -1001, "status": "approved"}
    )
    await db.pending_joins.insert_one(
        {"tg_user_id": 42, "chat_id": -1001, "created_at": datetime.now(tz=UTC)}
    )

    await on_chat_member_left(
        _make_member_update(chat_id=-1001, user_id=42, new_status="left"), db=db
    )

    assert await db.verifications.count_documents({"tg_user_id": 42}) == 0
    assert await db.dust_requests.count_documents({"tg_user_id": 42}) == 0
    assert await db.pending_joins.count_documents({"tg_user_id": 42}) == 0


async def test_member_kicked_clears_verification() -> None:
    """Admin kick also wipes the user's records."""
    from app.bot import on_chat_member_left

    db = _make_db()
    await db.verifications.insert_one(
        {
            "tg_user_id": 42,
            "chat_id": -1001,
            "address": "0xabc",
            "chain": "base-sepolia",
            "verified_at": datetime.now(tz=UTC),
        }
    )

    await on_chat_member_left(
        _make_member_update(chat_id=-1001, user_id=42, new_status="kicked"), db=db
    )

    assert await db.verifications.count_documents({"tg_user_id": 42}) == 0


async def test_other_status_changes_do_not_clear() -> None:
    """Status changes other than left/kicked leave records untouched."""
    from app.bot import on_chat_member_left

    db = _make_db()
    await db.verifications.insert_one(
        {
            "tg_user_id": 42,
            "chat_id": -1001,
            "address": "0xabc",
            "chain": "base-sepolia",
            "verified_at": datetime.now(tz=UTC),
        }
    )

    await on_chat_member_left(
        _make_member_update(chat_id=-1001, user_id=42, new_status="member"), db=db
    )

    assert await db.verifications.count_documents({"tg_user_id": 42}) == 1


async def test_only_clears_matching_chat() -> None:
    """Records for a different chat are not touched when user leaves another chat."""
    from app.bot import on_chat_member_left

    db = _make_db()
    # User has verifications in two chats
    await db.verifications.insert_many(
        [
            {
                "tg_user_id": 42,
                "chat_id": -1001,
                "address": "0xabc",
                "chain": "base-sepolia",
                "verified_at": datetime.now(tz=UTC),
            },
            {
                "tg_user_id": 42,
                "chat_id": -2002,
                "address": "0xabc",
                "chain": "base-sepolia",
                "verified_at": datetime.now(tz=UTC),
            },
        ]
    )

    # User leaves chat -1001 only
    await on_chat_member_left(
        _make_member_update(chat_id=-1001, user_id=42, new_status="left"), db=db
    )

    # -1001 record gone, -2002 record intact
    assert await db.verifications.count_documents({"tg_user_id": 42, "chat_id": -1001}) == 0
    assert await db.verifications.count_documents({"tg_user_id": 42, "chat_id": -2002}) == 1
