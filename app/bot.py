"""Aiogram 3 dispatcher + handlers for tg-token v2.

Session 0: hello-world auto-approve.
Session 1: Mongo-backed whitelist gate, decline path.
Session 2: SIWE verify path. Three outcomes from the gate:

- Approve → call `approve_chat_join_request`
- Decline → call `decline_chat_join_request`
- NeedsVerify → DM the user a "Verify your wallet" message with a
  WebApp button. Leave the join request pending. The Mini App calls
  `/siwe/verify` which, on success, approves the still-pending request.

Approve / decline calls are wrapped with bounded exponential-backoff
retry on `TelegramNetworkError` — Telegram's edge resets connections
under some networks; "no silent failure" is non-negotiable.
"""

from __future__ import annotations

from typing import Any

from aiogram import Bot, Dispatcher, Router
from aiogram.exceptions import TelegramAPIError, TelegramNetworkError
from aiogram.filters import Command
from aiogram.types import (
    ChatJoinRequest,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)
from motor.motor_asyncio import AsyncIOMotorDatabase
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.gates import Approve, Decline, NeedsVerify, evaluate
from app.logging_conf import get_logger
from app.settings import settings

log = get_logger(__name__)

router = Router(name="tg_token")


def _telegram_retry() -> AsyncRetrying:
    return AsyncRetrying(
        retry=retry_if_exception_type(TelegramNetworkError),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=8.0),
        reraise=True,
    )


def _verify_url(chat_id: int) -> str:
    """The Mini App URL the bot points users at. The chat_id is encoded
    in the query so the Mini App knows which chat the user is verifying
    for (one Mini App, many gated chats)."""
    base = settings.webapp_url.rstrip("/") if settings.webapp_url else ""
    if not base:
        return ""
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}chat_id={chat_id}"


def _verify_keyboard(chat_id: int) -> InlineKeyboardMarkup | None:
    url = _verify_url(chat_id)
    if not url:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Verify your wallet",
                    web_app=WebAppInfo(url=url),
                )
            ]
        ]
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
        return

    if isinstance(decision, Decline):
        async for attempt in _telegram_retry():
            with attempt:
                await bot.decline_chat_join_request(chat_id=chat_id, user_id=user_id)
        bind.info("declined", reason=decision.reason)
        return

    # NeedsVerify: DM the user, leave the join request pending. The
    # /siwe/verify endpoint approves the request when the Mini App
    # completes successfully.
    assert isinstance(decision, NeedsVerify)
    keyboard = _verify_keyboard(chat_id)
    if keyboard is None:
        # No webapp URL configured — fall back to Decline so we don't
        # leave the user stranded with a useless DM.
        bind.warning("needs_verify_no_webapp_url_falling_back_to_decline")
        async for attempt in _telegram_retry():
            with attempt:
                await bot.decline_chat_join_request(chat_id=chat_id, user_id=user_id)
        return

    text = (
        f"Hi {event.from_user.first_name}! To join <b>{event.chat.title}</b> you "
        "need to prove ownership of an eligible wallet. Tap the button below to open "
        "the verifier in Telegram."
    )
    try:
        async for attempt in _telegram_retry():
            with attempt:
                await bot.send_message(chat_id=user_id, text=text, reply_markup=keyboard)
        bind.info("verify_dm_sent", reason=decision.reason)
    except TelegramAPIError as e:
        # Most likely cause: the user hasn't started a DM with the bot,
        # so we can't message them. We don't decline — we just log.
        # The user can re-tap the invite link after starting the bot.
        bind.warning("verify_dm_failed", err=str(e))


@router.message(Command("start"))
async def on_start(message: Message) -> None:
    """Lets the user open a DM with the bot before clicking an invite link.
    Without this, `send_message(chat_id=user_id)` from the join-request
    handler would fail with `Forbidden: bot can't initiate conversation`."""
    log.info("start_command", user_id=message.from_user.id if message.from_user else None)
    await message.answer(
        "Hi! I'm tg-token v2. Click an invite link to a gated chat, then "
        "I'll DM you a verification button."
    )


@router.message(Command("health"))
async def on_health(message: Message) -> None:
    log.info("health_command", user_id=message.from_user.id if message.from_user else None)
    await message.answer("ok")


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(router)
    return dp
