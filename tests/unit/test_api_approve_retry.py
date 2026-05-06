"""Unit tests for `_try_approve_join` retry behaviour. Caught during
the S2 mobile smoke: Telegram's edge reset the approve_chat_join_request
TCP connection, our /api/siwe/verify reported approved_join=False even
though Telegram likely processed the request server-side. Retry now
distinguishes a real TG-side reject from a transient network blip.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError

from app.api import _try_approve_join

pytestmark = pytest.mark.unit


async def test_returns_false_when_bot_is_none() -> None:
    assert (await _try_approve_join(None, chat_id=-100, tg_user_id=1)) is False


async def test_succeeds_first_attempt() -> None:
    bot = Mock()
    bot.approve_chat_join_request = AsyncMock()
    ok = await _try_approve_join(bot, chat_id=-100, tg_user_id=1)
    assert ok is True
    assert bot.approve_chat_join_request.await_count == 1


async def test_retries_on_transient_network_error_then_succeeds() -> None:
    bot = Mock()
    bot.approve_chat_join_request = AsyncMock(
        side_effect=[
            TelegramNetworkError(method=Mock(), message="reset 1"),
            TelegramNetworkError(method=Mock(), message="reset 2"),
            None,
        ]
    )
    ok = await _try_approve_join(bot, chat_id=-100, tg_user_id=1)
    assert ok is True
    assert bot.approve_chat_join_request.await_count == 3


async def test_returns_false_after_max_network_failures() -> None:
    """5 transient network errors in a row → give up. Don't lie that we
    succeeded — caller's response will say approved_join=False."""
    bot = Mock()
    bot.approve_chat_join_request = AsyncMock(
        side_effect=TelegramNetworkError(method=Mock(), message="down")
    )
    ok = await _try_approve_join(bot, chat_id=-100, tg_user_id=1)
    assert ok is False
    assert bot.approve_chat_join_request.await_count == 5


async def test_bad_request_returns_false_without_retry() -> None:
    """A `TelegramBadRequest` (e.g. "user is already a participant",
    "request not found") is a final answer from TG — don't retry."""
    bot = Mock()
    bot.approve_chat_join_request = AsyncMock(
        side_effect=TelegramBadRequest(method=Mock(), message="HIDE_REQUESTER_MISSING")
    )
    ok = await _try_approve_join(bot, chat_id=-100, tg_user_id=1)
    assert ok is False
    assert bot.approve_chat_join_request.await_count == 1
