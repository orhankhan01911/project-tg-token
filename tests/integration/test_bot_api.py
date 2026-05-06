"""Integration test: a real call to the Telegram Bot API.

Skipped unless `BOT_TOKEN` is set in the environment. This is the one network
crossing the unit suite cannot replace — it proves the token is valid, the
host can reach api.telegram.org, and aiogram constructs the call correctly.

Per the production-quality bar in the build plan, every chain / external
service has at least one real-boundary integration test.
"""

from __future__ import annotations

import os

import pytest
from aiogram import Bot

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.environ.get("BOT_TOKEN"), reason="BOT_TOKEN not set"),
]


async def test_get_me_returns_bot_user() -> None:
    bot = Bot(token=os.environ["BOT_TOKEN"])
    try:
        me = await bot.get_me()
    finally:
        await bot.session.close()

    assert me.is_bot is True
    assert me.id > 0
    assert me.username  # bots always have usernames
