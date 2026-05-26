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
from datetime import UTC, datetime
from typing import Any, cast

import httpx
from aiogram import Bot, Dispatcher, Router
from aiogram.exceptions import TelegramAPIError, TelegramNetworkError
from aiogram.filters import Command, CommandObject
from aiogram.types import ChatJoinRequest, ChatMemberUpdated, Message
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
    http: httpx.AsyncClient,
) -> None:
    chat_id = event.chat.id
    user_id = event.from_user.id
    bind = log.bind(chat_id=chat_id, tg_user_id=user_id, kind="chat_join_request")
    bind.info("join_request_received")

    decision = await evaluate(db, http, chat_id=chat_id, tg_user_id=user_id)

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


@router.my_chat_member()
async def on_my_chat_member(
    update: ChatMemberUpdated,
    bot: Bot,
    db: Any,
) -> None:
    """Auto-register a chat when the bot is promoted to admin by the chat creator.

    Security: only the chat creator (owner) may register the chat for gating.
    Any other admin who promotes the bot is silently ignored — they must not
    be able to claim ownership of a chat they don't fully control.
    """
    new_status = update.new_chat_member.status
    if new_status not in ("administrator", "creator"):
        return  # bot demoted or kicked — don't touch the record

    chat_id = update.chat.id
    promoter = update.from_user  # type: ignore[union-attr]

    # Only allow the chat creator to register the chat. Any other admin who
    # promotes the bot is NOT trusted as the gate owner.
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=promoter.id)
    except TelegramAPIError as e:
        log.warning(
            "chat_register_get_member_failed",
            chat_id=chat_id,
            user_id=promoter.id,
            err=str(e),
        )
        return

    if member.status != "creator":
        log.info(
            "chat_register_skipped_not_creator",
            chat_id=chat_id,
            user_id=promoter.id,
            status=member.status,
        )
        return

    chat_title = update.chat.title or str(chat_id)
    owner_tg_id = promoter.id

    await cast(Any, db.chats).update_one(
        {"_id": chat_id},
        {
            "$setOnInsert": {
                "_id": chat_id,
                "title": chat_title,
                "owner_tg_id": owner_tg_id,
                "created_at": datetime.now(tz=UTC),
            }
        },
        upsert=True,
    )
    log.info("chat_registered", chat_id=chat_id, owner=owner_tg_id)


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


# ── management helpers (pure, unit-testable) ─────────────────────────────────


async def _cmd_settings_text(db: AsyncIOMotorDatabase[Any], *, owner_id: int) -> str:
    """Build the /settings display string for all chats owned by owner_id."""
    chats = await cast(Any, db.chats).find({"owner_tg_id": owner_id}).to_list(None)
    if not chats:
        return "No registered groups. Add me to a group as admin first."
    lines: list[str] = []
    for chat in chats:
        chat_id = int(chat["_id"])
        title = chat.get("title") or str(chat_id)
        purge_status = "✓ enabled" if chat.get("purge_enabled") else "✗ disabled"
        lines.append(f"📋 <b>{title}</b> ({chat_id}) — purge {purge_status}:")
        gates = await cast(Any, db.gates).find({"chat_id": chat_id}).to_list(None)
        if gates:
            lines.append(f"Gates ({len(gates)}):")
            for i, g in enumerate(gates, 1):
                contract = g.get("contract") or "native"
                lines.append(
                    f"  {i}. {g.get('chain')} · "
                    f"{contract[:10] if contract != 'native' else contract} · "
                    f"min {g['threshold']}"
                )
        else:
            lines.append("Gates: none")
        wl = await cast(Any, db.whitelist).find({"chat_id": chat_id}).to_list(None)
        if wl:
            lines.append(f"Whitelist ({len(wl)}):")
            for entry in wl:
                lines.append(f"  • {entry['tg_user_id']}")
        else:
            lines.append("Whitelist: none")
        lines.append("")
    return "\n".join(lines).strip()


async def _delete_gate_by_index(
    db: AsyncIOMotorDatabase[Any], *, owner_id: int, index: int
) -> bool:
    """Delete the index-th gate (1-based) across all chats the owner owns.

    Returns True if a gate was deleted, False if index is out of range.
    """
    chats = await cast(Any, db.chats).find({"owner_tg_id": owner_id}).to_list(None)
    all_gates: list[dict] = []
    for chat in chats:
        gates = await cast(Any, db.gates).find({"chat_id": int(chat["_id"])}).to_list(None)
        all_gates.extend(gates)
    if index < 1 or index > len(all_gates):
        return False
    gate = all_gates[index - 1]
    await cast(Any, db.gates).delete_one({"_id": gate["_id"]})
    return True


async def _whitelist_add(
    db: AsyncIOMotorDatabase[Any], *, owner_id: int, target_user_id: int
) -> None:
    """Add target_user_id to the whitelist for all chats owned by owner_id."""
    chats = await cast(Any, db.chats).find({"owner_tg_id": owner_id}).to_list(None)
    for chat in chats:
        chat_id = int(chat["_id"])
        await cast(Any, db.whitelist).update_one(
            {"chat_id": chat_id, "tg_user_id": target_user_id},
            {
                "$setOnInsert": {
                    "chat_id": chat_id,
                    "tg_user_id": target_user_id,
                    "added_at": datetime.now(tz=UTC),
                    "added_by_tg_id": owner_id,
                }
            },
            upsert=True,
        )


async def _whitelist_remove(
    db: AsyncIOMotorDatabase[Any], *, owner_id: int, target_user_id: int
) -> None:
    """Remove target_user_id from the whitelist for all chats owned by owner_id."""
    chats = await cast(Any, db.chats).find({"owner_tg_id": owner_id}).to_list(None)
    for chat in chats:
        chat_id = int(chat["_id"])
        await cast(Any, db.whitelist).delete_one({"chat_id": chat_id, "tg_user_id": target_user_id})


async def _set_purge_enabled(
    db: AsyncIOMotorDatabase[Any], *, owner_id: int, enabled: bool
) -> None:
    """Enable or disable daily purge for all chats owned by owner_id."""
    await cast(Any, db.chats).update_many(
        {"owner_tg_id": owner_id},
        {"$set": {"purge_enabled": enabled}},
    )


async def _recheck_user(
    db: AsyncIOMotorDatabase[Any],
    http: httpx.AsyncClient,
    *,
    tg_user_id: int,
) -> str:
    """Re-run gate evaluation for the user's most recently verified chat.

    Returns a human-readable result string.
    """
    verif = await cast(Any, db.verifications).find_one(
        {"tg_user_id": tg_user_id},
        sort=[("verified_at", -1)],
    )
    if verif is None:
        return "No verified wallet found. Run /verify first."
    chat_id = int(verif["chat_id"])
    decision = await evaluate(db, http, chat_id=chat_id, tg_user_id=tg_user_id)
    if isinstance(decision, Approve):
        return "✅ You still meet all requirements."
    if isinstance(decision, Decline):
        return f"❌ You no longer meet the requirements: {decision.reason}"
    return "⚠️ Your wallet verification has expired. Run /verify to re-verify."


# ── management handlers ───────────────────────────────────────────────────────


@router.message(Command("settings"))
async def on_settings(message: Message, db: AsyncIOMotorDatabase[Any]) -> None:
    if not message.from_user:
        return
    text = await _cmd_settings_text(db, owner_id=message.from_user.id)
    await message.answer(text, parse_mode="HTML")


@router.message(Command("delgate"))
async def on_delgate(
    message: Message, command: CommandObject, db: AsyncIOMotorDatabase[Any]
) -> None:
    if not message.from_user:
        return
    args = (command.args or "").strip()
    if not args.isdigit():
        await message.answer("Usage: <code>/delgate 1</code> (number from /settings list)")
        return
    ok = await _delete_gate_by_index(db, owner_id=message.from_user.id, index=int(args))
    if ok:
        await message.answer("✓ Gate deleted.")
    else:
        await message.answer("Invalid gate number. Run /settings to see the list.")


@router.message(Command("whitelist"))
async def on_whitelist(
    message: Message, command: CommandObject, db: AsyncIOMotorDatabase[Any]
) -> None:
    if not message.from_user:
        return
    args = (command.args or "").strip().split()
    if len(args) != 2 or args[0] not in ("add", "remove") or not args[1].isdigit():
        await message.answer(
            "Usage:\n"
            "  <code>/whitelist add 123456789</code>\n"
            "  <code>/whitelist remove 123456789</code>"
        )
        return
    action, uid_str = args
    target_uid = int(uid_str)
    if action == "add":
        await _whitelist_add(db, owner_id=message.from_user.id, target_user_id=target_uid)
        await message.answer(f"✓ Added {target_uid} to whitelist.")
    else:
        await _whitelist_remove(db, owner_id=message.from_user.id, target_user_id=target_uid)
        await message.answer(f"✓ Removed {target_uid} from whitelist.")


@router.message(Command("purge_enable"))
async def on_purge_enable(message: Message, db: AsyncIOMotorDatabase[Any]) -> None:
    if not message.from_user:
        return
    await _set_purge_enabled(db, owner_id=message.from_user.id, enabled=True)
    await message.answer("✓ Daily purge enabled for your groups.")


@router.message(Command("purge_disable"))
async def on_purge_disable(message: Message, db: AsyncIOMotorDatabase[Any]) -> None:
    if not message.from_user:
        return
    await _set_purge_enabled(db, owner_id=message.from_user.id, enabled=False)
    await message.answer("✓ Daily purge disabled for your groups.")


@router.message(Command("recheck"))
async def on_recheck(
    message: Message, db: AsyncIOMotorDatabase[Any], http: httpx.AsyncClient
) -> None:
    if not message.from_user:
        return
    result = await _recheck_user(db, http, tg_user_id=message.from_user.id)
    await message.answer(result)


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(router)
    return dp
