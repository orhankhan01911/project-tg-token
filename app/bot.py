"""Aiogram 3 dispatcher + handlers for tg-token v2.

Session 2 (dust-only): no Mini App, no SIWE, no WalletConnect.
Verification is a self-transfer of a unique dust amount on-chain.

Flow:
  chat_join_request → bot DMs verify instructions
  /verify 0xAddress → bot issues a unique amount, persists DustRequest
  user makes self-transfer in their wallet
  background `dust_watcher` detects + confirms + approves

Decisions/Approvals call `bot.{approve,decline}_chat_join_request` with
bounded exponential-backoff retry on `TelegramNetworkError` — Telegram's
edge resets connections under load and "no silent failure" is the bar.
"""

from __future__ import annotations

import re
from typing import Any

from aiogram import Bot, Dispatcher, Router
from aiogram.exceptions import TelegramAPIError, TelegramNetworkError
from aiogram.filters import Command, CommandObject
from aiogram.types import ChatJoinRequest, Message
from motor.motor_asyncio import AsyncIOMotorDatabase
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.auth.dust import cancel_dust_request, format_amount_eth, issue_dust_request
from app.chains.evm import get_chain
from app.gates import Approve, Decline, NeedsVerify, evaluate
from app.logging_conf import get_logger
from app.settings import settings

log = get_logger(__name__)

router = Router(name="tg_token")

# 0x-prefixed 40-hex-char address. We don't enforce EIP-55 checksum since
# wallets often emit lowercase; we lowercase before storage.
_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def _telegram_retry() -> AsyncRetrying:
    return AsyncRetrying(
        retry=retry_if_exception_type(TelegramNetworkError),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=8.0),
        reraise=True,
    )


def _verify_instructions_dm(*, chat_title: str | None) -> str:
    title = chat_title or "this chat"
    return (
        f"Hi! To join <b>{title}</b> verify a wallet by sending yourself a "
        "tiny test transaction.\n\n"
        "<b>Step 1.</b> Reply with the wallet address you want to verify:\n"
        "<code>/verify 0xYourWalletAddress</code>\n\n"
        "I'll then give you an exact amount to send to yourself "
        "(no <i>connect wallet</i> popup, no signing — just a regular transaction). "
        "Detection is automatic.\n\n"
        "Send <code>/cancel</code> any time to stop."
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

    # NeedsVerify: DM the user instructions for the dust flow. Leave the
    # join request pending — the watcher approves it once they send the
    # self-transfer.
    assert isinstance(decision, NeedsVerify)
    text = _verify_instructions_dm(chat_title=event.chat.title)
    try:
        async for attempt in _telegram_retry():
            with attempt:
                await bot.send_message(chat_id=user_id, text=text)
        bind.info("verify_dm_sent", reason=decision.reason)
    except TelegramAPIError as e:
        # Most likely cause: user hasn't /start'd the bot. We can't
        # decline (the user can't take action either). Logged; they'll
        # have to /start the bot then re-tap the invite.
        bind.warning("verify_dm_failed", err=str(e))


@router.message(Command("verify"))
async def on_verify(
    message: Message,
    command: CommandObject,
    bot: Bot,
    db: AsyncIOMotorDatabase[Any],
) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id

    arg = (command.args or "").strip()
    if not arg or not _ADDRESS_RE.match(arg):
        await message.answer(
            "Usage: <code>/verify 0xYourWalletAddress</code>\n\n"
            "The address must be 0x-prefixed and 40 hex characters."
        )
        return
    address = arg.lower()

    # Find the most recent chat the user has a pending join_request for.
    # We don't track pending join requests in Mongo (Telegram is the
    # source of truth); but we DO know which chats this user has been
    # NeedsVerify'd against because the bot DMd them. v0 simplification:
    # require exactly one registered chat; if multiple, the owner needs
    # to scope per-chat (deferred to S3).
    chat_id = await _resolve_pending_chat(db, tg_user_id=user_id)
    if chat_id is None:
        await message.answer(
            "I don't see a pending join request from you on any registered chat. "
            "Click the invite link first, then run <code>/verify</code>."
        )
        return

    req = await issue_dust_request(
        db,
        tg_user_id=user_id,
        chat_id=chat_id,
        address=address,
        chain_id=settings.dust_chain_id,
    )
    chain = get_chain(req.chain_id)
    amount_eth = format_amount_eth(req.amount_wei)

    await message.answer(
        "✅ Got it. Now <b>send EXACTLY this amount from your wallet to itself</b>:\n\n"
        f"  <b>Amount:</b> <code>{amount_eth} ETH</code>\n"
        f"  <b>From → To:</b> <code>{address}</code> (yourself)\n"
        f"  <b>Network:</b> {chain.name}\n\n"
        f"In wei (for max precision): <code>{req.amount_wei}</code>\n\n"
        "I'll detect it automatically — usually within a minute of confirmation. "
        f"This expires in {settings.dust_request_ttl_seconds // 60} min. "
        "Send <code>/cancel</code> to abort."
    )
    log.info(
        "verify_command",
        tg_user_id=user_id,
        chat_id=chat_id,
        address=address,
        chain_id=req.chain_id,
        amount_wei=req.amount_wei,
    )


@router.message(Command("cancel"))
async def on_cancel(message: Message, db: AsyncIOMotorDatabase[Any]) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    chat_id = await _resolve_pending_chat(db, tg_user_id=user_id)
    if chat_id is None:
        await message.answer("Nothing to cancel — no pending verification.")
        return
    cancelled = await cancel_dust_request(db, tg_user_id=user_id, chat_id=chat_id)
    if cancelled:
        await message.answer("Cancelled. Send <code>/verify</code> again any time.")
    else:
        await message.answer("Nothing to cancel — no pending verification.")


@router.message(Command("start"))
async def on_start(message: Message) -> None:
    """Lets the user open a DM with the bot. Without a /start, the
    bot can't initiate DMs (TG enforces this), so the verify-DM from
    the join_request handler would silently fail."""
    log.info(
        "start_command",
        user_id=message.from_user.id if message.from_user else None,
    )
    await message.answer(
        "Hi! I'm tg-token v2. Click an invite link to a gated chat, then "
        "I'll DM you a quick wallet-verify flow."
    )


@router.message(Command("health"))
async def on_health(message: Message) -> None:
    log.info(
        "health_command",
        user_id=message.from_user.id if message.from_user else None,
    )
    await message.answer("ok")


async def _resolve_pending_chat(db: AsyncIOMotorDatabase[Any], *, tg_user_id: int) -> int | None:
    """Best-guess: the chat this user is currently being asked to verify
    against. v0 heuristic: the user is in the bot's DB as a NeedsVerify
    target — so the chat is the single chat that's registered. If there
    are multiple registered chats and the user has join requests in
    several, we'd need scoped commands (`/verify chat_id 0x...`); for
    v0 we pick the most-recently-created chat that they're not already
    approved in."""
    # If the user already has a non-expired pending dust request, prefer
    # that chat.
    from datetime import UTC, datetime

    existing = await db.dust_requests.find_one(  # type: ignore[union-attr]
        {"tg_user_id": tg_user_id, "expires_at": {"$gt": datetime.now(tz=UTC)}}
    )
    if existing:
        return int(existing["chat_id"])

    # Otherwise the most recent registered chat where the user isn't a
    # whitelisted owner.
    cursor = db.chats.find().sort("created_at", -1)  # type: ignore[union-attr]
    async for chat in cursor:
        if chat.get("owner_tg_id") != tg_user_id:
            return int(chat["_id"])
    return None


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(router)
    return dp
