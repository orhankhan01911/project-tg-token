# app/purge.py
"""Monthly purge engine.

Iterates all chats with purge_enabled=True. For each chat, re-evaluates
every verified member. Members who Decline (insufficient_balance) are
banned. NeedsVerify is skipped — wallet expired, not token-insufficient.

Called by APScheduler on the 1st of each month. Also callable manually (admin command
or test). Never touches bot.py — purely a logic module.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import httpx
from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.gates import Decline, evaluate
from app.logging_conf import get_logger

log = get_logger(__name__)


@dataclass
class PurgeResult:
    chat_id: int
    checked: int = 0
    banned: int = 0
    errors: list[str] = field(default_factory=list)


async def _ban_with_retry(bot: Bot, *, chat_id: int, user_id: int) -> None:
    """Ban a user, honouring Telegram's retry_after flood control."""
    while True:
        try:
            await bot.ban_chat_member(chat_id, user_id)
            return
        except TelegramRetryAfter as e:
            log.warning(
                "purge_retry_after",
                chat_id=chat_id,
                user_id=user_id,
                retry_after=e.retry_after,
            )
            await asyncio.sleep(e.retry_after)


async def purge_chat(
    bot: Bot,
    db: AsyncIOMotorDatabase[Any],
    http: httpx.AsyncClient,
    *,
    chat_id: int,
) -> PurgeResult:
    """Evaluate every verified member of `chat_id`. Ban those who Decline.

    Only bans on `Decline` — `NeedsVerify` means the wallet proof expired,
    not that the user sold their tokens. We don't punish users whose
    verification TTL lapsed.
    """
    result = PurgeResult(chat_id=chat_id)
    verifications = await db.verifications.find({"chat_id": chat_id}).to_list(None)

    for verif in verifications:
        user_id: int = verif["tg_user_id"]
        result.checked += 1
        try:
            decision = await evaluate(db, http, chat_id=chat_id, tg_user_id=user_id)
        except Exception as e:
            log.error("purge_evaluate_error", chat_id=chat_id, user_id=user_id, err=str(e))
            result.errors.append(str(e))
            continue

        if isinstance(decision, Decline):
            log.info("purge_banning", chat_id=chat_id, user_id=user_id, reason=decision.reason)
            try:
                await _ban_with_retry(bot, chat_id=chat_id, user_id=user_id)
                result.banned += 1
            except Exception as e:
                log.error("purge_ban_error", chat_id=chat_id, user_id=user_id, err=str(e))
                result.errors.append(str(e))

    log.info("purge_chat_done", chat_id=chat_id, checked=result.checked, banned=result.banned)
    return result


async def run_purge_all_chats(
    bot: Bot,
    db: AsyncIOMotorDatabase[Any],
    http: httpx.AsyncClient,
) -> None:
    """Monthly job: purge all chats with purge_enabled=True.

    Called by APScheduler. Errors in individual chats are logged but don't
    abort the sweep — one broken chat shouldn't stop others.
    """
    chats = await db.chats.find({"purge_enabled": True}).to_list(None)
    log.info("purge_sweep_start", chat_count=len(chats))
    for chat in chats:
        chat_id = int(chat["_id"])
        try:
            await purge_chat(bot, db, http, chat_id=chat_id)
        except Exception as e:
            log.error("purge_sweep_chat_error", chat_id=chat_id, err=str(e))
    log.info("purge_sweep_done", chat_count=len(chats))
