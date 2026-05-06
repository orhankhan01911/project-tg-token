"""Aiogram 3 dispatcher + handlers for tg-token v2.

Session 0: subscribes to `chat_join_request`, evaluates the (stub) gate, and
either approves or declines. The handler is intentionally thin — future
sessions extend `app.gates.evaluate` rather than touching this file.

Approve / decline calls are wrapped with bounded exponential-backoff retry
on `TelegramNetworkError`. Telegram's edge will reset connections under
load and from some networks; the production-quality bar is "no silent
failure modes" — retries are the right primitive here.
"""

from __future__ import annotations

from typing import Any

from aiogram import Bot, Dispatcher, Router
from aiogram.exceptions import TelegramNetworkError
from aiogram.filters import Command
from aiogram.types import ChatJoinRequest, Message
from motor.motor_asyncio import AsyncIOMotorDatabase
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.gates import Approve, Decline, evaluate
from app.logging_conf import get_logger

log = get_logger(__name__)

router = Router(name="tg_token")


def _telegram_retry() -> AsyncRetrying:
    return AsyncRetrying(
        retry=retry_if_exception_type(TelegramNetworkError),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=8.0),
        reraise=True,
    )


@router.chat_join_request()
async def on_chat_join_request(
    event: ChatJoinRequest,
    bot: Bot,
    db: AsyncIOMotorDatabase[Any],
) -> None:
    chat_id = event.chat.id
    user_id = event.from_user.id
    bind = log.bind(chat_id=chat_id, tg_user_id=user_id, kind="chat_join_request")
    bind.info("join_request_received")

    decision = await evaluate(db, chat_id=chat_id, tg_user_id=user_id)
    if isinstance(decision, Approve):
        async for attempt in _telegram_retry():
            with attempt:
                await bot.approve_chat_join_request(chat_id=chat_id, user_id=user_id)
        bind.info("approved", reason=decision.reason)
    elif isinstance(decision, Decline):
        async for attempt in _telegram_retry():
            with attempt:
                await bot.decline_chat_join_request(chat_id=chat_id, user_id=user_id)
        bind.info("declined", reason=decision.reason)


@router.message(Command("health"))
async def on_health(message: Message) -> None:
    log.info("health_command", user_id=message.from_user.id if message.from_user else None)
    await message.answer("ok")


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(router)
    return dp
