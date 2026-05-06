"""Unit tests for the chat_join_request handler. Mocks the Bot — these run
fast on every save and pre-push. The real-Bot-API integration test lives
in tests/integration/test_bot_api.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest
from aiogram.exceptions import TelegramNetworkError
from aiogram.types import Chat, ChatJoinRequest, User
from mongomock_motor import AsyncMongoMockClient

from app.bot import on_chat_join_request

pytestmark = pytest.mark.unit


def _make_event(*, chat_id: int, user_id: int) -> ChatJoinRequest:
    return ChatJoinRequest.model_construct(
        chat=Chat(id=chat_id, type="supergroup", title="test"),
        from_user=User(id=user_id, is_bot=False, first_name="Tester"),
        user_chat_id=user_id,
        date=datetime.now(tz=UTC),
    )


def _make_bot() -> Mock:
    bot = Mock()
    bot.approve_chat_join_request = AsyncMock()
    bot.decline_chat_join_request = AsyncMock()
    return bot


@pytest.fixture
def db():
    client = AsyncMongoMockClient()
    return client["tg_token_test"]


async def test_owner_join_request_is_approved(db) -> None:
    await db.chats.insert_one({"_id": -1001, "owner_tg_id": 42})
    event = _make_event(chat_id=-1001, user_id=42)
    bot = _make_bot()

    await on_chat_join_request(event, bot=bot, db=db)

    bot.approve_chat_join_request.assert_awaited_once_with(chat_id=-1001, user_id=42)
    bot.decline_chat_join_request.assert_not_awaited()


async def test_whitelisted_user_is_approved(db) -> None:
    await db.chats.insert_one({"_id": -1001, "owner_tg_id": 1})
    await db.whitelist.insert_one({"chat_id": -1001, "tg_user_id": 42})
    event = _make_event(chat_id=-1001, user_id=42)
    bot = _make_bot()

    await on_chat_join_request(event, bot=bot, db=db)

    bot.approve_chat_join_request.assert_awaited_once_with(chat_id=-1001, user_id=42)


async def test_stranger_is_declined(db) -> None:
    await db.chats.insert_one({"_id": -1001, "owner_tg_id": 1})
    event = _make_event(chat_id=-1001, user_id=99)
    bot = _make_bot()

    await on_chat_join_request(event, bot=bot, db=db)

    bot.decline_chat_join_request.assert_awaited_once_with(chat_id=-1001, user_id=99)
    bot.approve_chat_join_request.assert_not_awaited()


async def test_unregistered_chat_is_declined(db) -> None:
    """Defense-in-depth: bot in a chat we never seeded → decline, do not
    silently approve."""
    event = _make_event(chat_id=-9999, user_id=42)
    bot = _make_bot()

    await on_chat_join_request(event, bot=bot, db=db)

    bot.decline_chat_join_request.assert_awaited_once_with(chat_id=-9999, user_id=42)


async def test_approve_retries_on_transient_network_error(db) -> None:
    """Two TelegramNetworkErrors then success — handler must persist."""
    await db.chats.insert_one({"_id": -1001, "owner_tg_id": 42})
    event = _make_event(chat_id=-1001, user_id=42)
    bot = _make_bot()
    bot.approve_chat_join_request = AsyncMock(
        side_effect=[
            TelegramNetworkError(method=Mock(), message="reset 1"),
            TelegramNetworkError(method=Mock(), message="reset 2"),
            None,
        ]
    )

    await on_chat_join_request(event, bot=bot, db=db)

    assert bot.approve_chat_join_request.await_count == 3


async def test_approve_gives_up_after_max_attempts(db) -> None:
    """Persistent network failure → after 5 attempts the exception escapes
    so aiogram's outer logger surfaces it; we don't swallow silently."""
    await db.chats.insert_one({"_id": -1001, "owner_tg_id": 42})
    event = _make_event(chat_id=-1001, user_id=42)
    bot = _make_bot()
    bot.approve_chat_join_request = AsyncMock(
        side_effect=TelegramNetworkError(method=Mock(), message="down")
    )

    with pytest.raises(TelegramNetworkError):
        await on_chat_join_request(event, bot=bot, db=db)

    assert bot.approve_chat_join_request.await_count == 5
