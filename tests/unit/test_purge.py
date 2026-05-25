# tests/unit/test_purge.py
"""Unit tests for the daily purge engine."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.gates import Approve, Decline, NeedsVerify

pytestmark = pytest.mark.unit


@pytest.fixture
def db():
    client = AsyncMongoMockClient()
    return client["tg_token_test"]


@pytest.fixture
def bot():
    b = AsyncMock()
    b.ban_chat_member = AsyncMock()
    return b


@pytest.fixture
def http():
    return AsyncMock()


async def _seed(db, *, chat_id=-1001, purge_enabled=True, members=None):
    await db.chats.insert_one(
        {
            "_id": chat_id,
            "owner_tg_id": 999,
            "title": "Test",
            "purge_enabled": purge_enabled,
        }
    )
    for m in members or []:
        await db.verifications.insert_one(
            {
                "tg_user_id": m,
                "chat_id": chat_id,
                "address": f"0xaddr{m}",
                "chain": "base",
                "verified_at": datetime.now(tz=UTC),
            }
        )


# ── purge_chat ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_purge_chat_bans_failing_members(db, bot, http):
    await _seed(db, members=[1, 2, 3])
    # user 1 passes, user 2 fails, user 3 fails
    side_effects = [
        Approve(reason="token_gate_passed"),
        Decline(reason="insufficient_balance"),
        Decline(reason="insufficient_balance"),
    ]
    with patch("app.purge.evaluate", new=AsyncMock(side_effect=side_effects)):
        from app.purge import purge_chat

        result = await purge_chat(bot, db, http, chat_id=-1001)
    assert result.banned == 2
    assert result.checked == 3
    assert bot.ban_chat_member.call_count == 2


@pytest.mark.asyncio
async def test_purge_chat_skips_needs_verify(db, bot, http):
    """NeedsVerify (unverified) — do NOT ban; wallet proof expired, not insufficient balance."""
    await _seed(db, members=[1])
    with patch(
        "app.purge.evaluate",
        new=AsyncMock(return_value=NeedsVerify(reason="requires_verification")),
    ):
        from app.purge import purge_chat

        result = await purge_chat(bot, db, http, chat_id=-1001)
    assert result.banned == 0
    bot.ban_chat_member.assert_not_called()


@pytest.mark.asyncio
async def test_purge_chat_no_members_is_noop(db, bot, http):
    await _seed(db, members=[])
    from app.purge import purge_chat

    result = await purge_chat(bot, db, http, chat_id=-1001)
    assert result.banned == 0
    assert result.checked == 0
    bot.ban_chat_member.assert_not_called()


@pytest.mark.asyncio
async def test_purge_chat_handles_retry_after(db, bot, http):
    """On TelegramRetryAfter, sleep and retry the ban."""
    from aiogram.exceptions import TelegramRetryAfter

    await _seed(db, members=[1])

    # Build a minimal TelegramRetryAfter — the constructor wants (method, message, retry_after).
    # We use MagicMock for method since we only care about .retry_after in the handler.
    retry_exc = TelegramRetryAfter(method=MagicMock(), message="Too Many Requests", retry_after=0)

    with patch(
        "app.purge.evaluate", new=AsyncMock(return_value=Decline(reason="insufficient_balance"))
    ):
        # First ban raises RetryAfter, second succeeds
        bot.ban_chat_member.side_effect = [retry_exc, None]
        with patch("app.purge.asyncio.sleep", new=AsyncMock()):
            from app.purge import purge_chat

            result = await purge_chat(bot, db, http, chat_id=-1001)
    assert result.banned == 1


# ── run_purge_all_chats ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_purge_skips_disabled_chats(db, bot, http):
    await _seed(db, chat_id=-1001, purge_enabled=False, members=[1])
    from app.purge import run_purge_all_chats

    with patch(
        "app.purge.evaluate", new=AsyncMock(return_value=Decline(reason="insufficient_balance"))
    ):
        await run_purge_all_chats(bot, db, http)
    bot.ban_chat_member.assert_not_called()


@pytest.mark.asyncio
async def test_run_purge_processes_enabled_chats(db, bot, http):
    await _seed(db, chat_id=-1001, purge_enabled=True, members=[1])
    with patch(
        "app.purge.evaluate", new=AsyncMock(return_value=Decline(reason="insufficient_balance"))
    ):
        from app.purge import run_purge_all_chats

        await run_purge_all_chats(bot, db, http)
    assert bot.ban_chat_member.call_count == 1
