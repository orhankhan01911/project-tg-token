"""Unit tests for the bot's chat_join_request handler + /verify command.

Mocks the Bot — these run fast on every save and pre-push. Real Bot API
integration test lives in tests/integration/test_bot_api.py.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from aiogram.exceptions import TelegramNetworkError
from aiogram.filters import CommandObject
from aiogram.types import Chat, ChatJoinRequest, Message, User
from mongomock_motor import AsyncMongoMockClient

from app.bot import on_cancel, on_chat_join_request, on_verify
from app.models import DustRequest, DustRequestStatus
from app.settings import settings

pytestmark = pytest.mark.unit


def _make_join(*, chat_id: int, user_id: int, title: str = "test") -> ChatJoinRequest:
    return ChatJoinRequest.model_construct(
        chat=Chat(id=chat_id, type="supergroup", title=title),
        from_user=User(id=user_id, is_bot=False, first_name="Tester"),
        user_chat_id=user_id,
        date=datetime.now(tz=UTC),
    )


def _make_message(*, user_id: int) -> Mock:
    msg = Mock(spec=Message)
    msg.from_user = User(id=user_id, is_bot=False, first_name="Tester")
    msg.answer = AsyncMock()
    return msg


def _make_bot() -> Mock:
    bot = Mock()
    bot.approve_chat_join_request = AsyncMock()
    bot.decline_chat_join_request = AsyncMock()
    bot.send_message = AsyncMock()
    return bot


@pytest.fixture
def db():
    client = AsyncMongoMockClient()
    return client["tg_token_test"]


@pytest.fixture
def http():
    return AsyncMock(spec=httpx.AsyncClient)


# --- chat_join_request handler ---


async def test_owner_join_request_is_approved(db, http) -> None:
    await db.chats.insert_one({"_id": -1001, "owner_tg_id": 42})
    bot = _make_bot()
    await on_chat_join_request(_make_join(chat_id=-1001, user_id=42), bot=bot, db=db, http=http)
    bot.approve_chat_join_request.assert_awaited_once_with(chat_id=-1001, user_id=42)
    bot.send_message.assert_not_awaited()


async def test_whitelisted_user_is_approved(db, http) -> None:
    await db.chats.insert_one({"_id": -1001, "owner_tg_id": 1})
    await db.whitelist.insert_one({"chat_id": -1001, "tg_user_id": 42})
    bot = _make_bot()
    await on_chat_join_request(_make_join(chat_id=-1001, user_id=42), bot=bot, db=db, http=http)
    bot.approve_chat_join_request.assert_awaited_once_with(chat_id=-1001, user_id=42)


async def test_stranger_gets_verify_dm_text_not_decline(db, http) -> None:
    """S2 (dust): stranger gets a TEXT DM with /verify instructions —
    no WebApp button, no Mini App link."""
    await db.chats.insert_one({"_id": -1001, "owner_tg_id": 1})
    bot = _make_bot()
    await on_chat_join_request(
        _make_join(chat_id=-1001, user_id=99, title="Demo"), bot=bot, db=db, http=http
    )

    bot.send_message.assert_awaited_once()
    call = bot.send_message.await_args
    assert call.kwargs["chat_id"] == 99
    body = call.kwargs["text"]
    assert "/verify" in body
    assert "Demo" in body
    assert "reply_markup" not in call.kwargs  # no buttons of any kind
    bot.approve_chat_join_request.assert_not_awaited()
    bot.decline_chat_join_request.assert_not_awaited()


async def test_fresh_dust_verification_is_approved(db, http) -> None:
    await db.chats.insert_one({"_id": -1001, "owner_tg_id": 1})
    await db.verifications.insert_one(
        {
            "tg_user_id": 42,
            "chat_id": -1001,
            "address": "0xabc",
            "chain": "base-sepolia",
            "method": "dust",
            "nonce": "",
            "sig_or_txhash": "0xtx",
            "verified_at": datetime.now(tz=UTC),
        }
    )
    bot = _make_bot()
    await on_chat_join_request(_make_join(chat_id=-1001, user_id=42), bot=bot, db=db, http=http)
    bot.approve_chat_join_request.assert_awaited_once_with(chat_id=-1001, user_id=42)


async def test_unregistered_chat_is_declined(db, http) -> None:
    bot = _make_bot()
    await on_chat_join_request(_make_join(chat_id=-9999, user_id=42), bot=bot, db=db, http=http)
    bot.decline_chat_join_request.assert_awaited_once_with(chat_id=-9999, user_id=42)


async def test_approve_retries_on_transient_network_error(db, http) -> None:
    await db.chats.insert_one({"_id": -1001, "owner_tg_id": 42})
    bot = _make_bot()
    bot.approve_chat_join_request = AsyncMock(
        side_effect=[
            TelegramNetworkError(method=Mock(), message="reset 1"),
            TelegramNetworkError(method=Mock(), message="reset 2"),
            None,
        ]
    )
    await on_chat_join_request(_make_join(chat_id=-1001, user_id=42), bot=bot, db=db, http=http)
    assert bot.approve_chat_join_request.await_count == 3


async def test_approve_gives_up_after_max_attempts(db, http) -> None:
    await db.chats.insert_one({"_id": -1001, "owner_tg_id": 42})
    bot = _make_bot()
    bot.approve_chat_join_request = AsyncMock(
        side_effect=TelegramNetworkError(method=Mock(), message="down")
    )
    with pytest.raises(TelegramNetworkError):
        await on_chat_join_request(_make_join(chat_id=-1001, user_id=42), bot=bot, db=db, http=http)
    assert bot.approve_chat_join_request.await_count == 5


async def test_stale_dust_verification_falls_through_to_dm(db, http) -> None:
    await db.chats.insert_one({"_id": -1001, "owner_tg_id": 1})
    stale = datetime.now(tz=UTC) - timedelta(seconds=settings.verification_ttl_seconds + 60)
    await db.verifications.insert_one(
        {
            "tg_user_id": 42,
            "chat_id": -1001,
            "address": "0xabc",
            "chain": "base-sepolia",
            "method": "dust",
            "nonce": "",
            "sig_or_txhash": "0xtx",
            "verified_at": stale,
        }
    )
    bot = _make_bot()
    await on_chat_join_request(_make_join(chat_id=-1001, user_id=42), bot=bot, db=db, http=http)
    bot.send_message.assert_awaited_once()
    bot.approve_chat_join_request.assert_not_awaited()


# --- /verify command ---


async def test_verify_rejects_missing_arg(db) -> None:
    await db.chats.insert_one({"_id": -1001, "owner_tg_id": 1})
    msg = _make_message(user_id=42)
    cmd = CommandObject(prefix="/", command="verify", mention=None, args=None)
    await on_verify(msg, cmd, bot=_make_bot(), db=db)
    msg.answer.assert_awaited_once()
    assert "Usage" in msg.answer.await_args.args[0]


async def test_verify_rejects_bad_address(db) -> None:
    await db.chats.insert_one({"_id": -1001, "owner_tg_id": 1})
    msg = _make_message(user_id=42)
    cmd = CommandObject(prefix="/", command="verify", mention=None, args="not-an-address")
    await on_verify(msg, cmd, bot=_make_bot(), db=db)
    msg.answer.assert_awaited_once()
    assert "0x-prefixed" in msg.answer.await_args.args[0]


async def test_verify_rejects_when_no_registered_chat(db) -> None:
    """After Patch 3, /verify with no pending join request returns a specific
    error — the old fallback (guess most-recent chat) is gone."""
    msg = _make_message(user_id=42)
    cmd = CommandObject(
        prefix="/",
        command="verify",
        mention=None,
        args="0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
    )
    await on_verify(msg, cmd, bot=_make_bot(), db=db)
    msg.answer.assert_awaited_once()
    body = msg.answer.await_args.args[0].lower()
    # Message must tell the user to click an invite link first.
    assert "no pending" in body or "click a group" in body or "click the invite" in body


async def test_verify_happy_path_creates_dust_request(db) -> None:
    """Happy path: user clicked an invite link (pending_join seeded), then
    calls /verify with a valid address. Patch 3 requires pending_join to exist."""
    await db.chats.insert_one({"_id": -1001, "owner_tg_id": 1})
    # Simulate on_chat_join_request having written a pending_join record.
    await db.pending_joins.insert_one(
        {
            "tg_user_id": 42,
            "chat_id": -1001,
            "created_at": datetime.now(tz=UTC),
        }
    )
    msg = _make_message(user_id=42)
    cmd = CommandObject(
        prefix="/",
        command="verify",
        mention=None,
        args="0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
    )
    await on_verify(msg, cmd, bot=_make_bot(), db=db)
    msg.answer.assert_awaited_once()
    body = msg.answer.await_args.args[0]
    assert "Amount" in body
    assert "From → To" in body or "From" in body

    raw = await db.dust_requests.find_one({"_id": "42:-1001"})
    assert raw is not None
    req = DustRequest.model_validate(raw)
    assert req.address == "0xd8da6bf26964af9d7eed9e03e53415d37aa96045"
    assert req.status is DustRequestStatus.PENDING


# --- /cancel command ---


async def test_cancel_with_no_pending_says_so(db) -> None:
    msg = _make_message(user_id=42)
    await on_cancel(msg, db=db)
    msg.answer.assert_awaited_once()
    assert "Nothing to cancel" in msg.answer.await_args.args[0]


async def test_cancel_existing_pending(db) -> None:
    await db.chats.insert_one({"_id": -1001, "owner_tg_id": 1})
    # Directly seed a pending dust_request (simulates the user having already
    # run /verify via a pending_join flow). Seeding directly avoids depending
    # on on_verify's internal logic in this cancel-focused test.
    await db.dust_requests.insert_one(
        {
            "_id": "42:-1001",
            "tg_user_id": 42,
            "chat_id": -1001,
            "address": "0xd8da6bf26964af9d7eed9e03e53415d37aa96045",
            "chain_id": 84532,
            "amount_wei": 40_001_234_567_890,
            "expires_at": datetime.now(tz=UTC) + timedelta(hours=1),
            "status": "pending",
        }
    )

    # Now cancel
    cancel_msg = _make_message(user_id=42)
    await on_cancel(cancel_msg, db=db)
    cancel_msg.answer.assert_awaited_once()
    assert "Cancelled" in cancel_msg.answer.await_args.args[0]
