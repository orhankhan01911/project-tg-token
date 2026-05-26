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
import time
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

from app.auth.address import detect_chain_type
from app.auth.dust import (
    cancel_dust_request,
    format_amount_eth,
    format_amount_sol,
    format_amount_ton,
    issue_dust_request,
)
from app.chains.evm import get_chain
from app.gates import Approve, Decline, NeedsVerify, evaluate
from app.logging_conf import get_logger
from app.settings import settings

log = get_logger(__name__)

router = Router(name="tg_token")

# 0x-prefixed 40-hex-char address. We don't enforce EIP-55 checksum since
# wallets often emit lowercase; we lowercase before storage.
_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")

# ---------------------------------------------------------------------------
# In-process rate-limit store for /verify cooldowns.
# Key: tg_user_id (int), Value: unix timestamp of last /verify call.
# TODO: replace with Redis when dp["redis"] is wired into __main__.py.
#       Use app.redis_store.make_redis(settings.redis_url) and inject via
#       dp["redis"] = redis_client. Then read from handler kwarg and call
#       await redis_client.set(key, "1", ex=300) / await redis_client.get(key).
# ---------------------------------------------------------------------------
_verify_cooldown_store: dict[int, float] = {}
_VERIFY_COOLDOWN_SECONDS = 60  # 1 minute


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
        # Record that this user has an active join request for this chat so
        # _resolve_pending_chat can look it up when the user calls /verify.
        # This is lightweight (upsert on composite key) and is cleaned up
        # when the dust_request is created in on_verify.
        await cast(Any, db.pending_joins).update_one(
            {"tg_user_id": user_id, "chat_id": chat_id},
            {
                "$set": {
                    "tg_user_id": user_id,
                    "chat_id": chat_id,
                    "created_at": datetime.now(tz=UTC),
                }
            },
            upsert=True,
        )
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


@router.chat_member()
async def on_chat_member_left(
    update: ChatMemberUpdated,
    db: AsyncIOMotorDatabase[Any],
) -> None:
    """Wipe verification + dust data when a member leaves or is kicked.

    Forces them through /verify again on next join attempt — prevents
    the stale-verification bypass where a previously verified user
    rejoins without re-proving wallet ownership.
    """
    new_status = update.new_chat_member.status
    if new_status not in ("left", "kicked"):
        return

    tg_user_id: int = update.new_chat_member.user.id
    chat_id: int = update.chat.id

    r_verif = await cast(Any, db.verifications).delete_many(
        {"tg_user_id": tg_user_id, "chat_id": chat_id}
    )
    r_dust = await cast(Any, db.dust_requests).delete_many(
        {"tg_user_id": tg_user_id, "chat_id": chat_id}
    )
    r_joins = await cast(Any, db.pending_joins).delete_many(
        {"tg_user_id": tg_user_id, "chat_id": chat_id}
    )

    log.info(
        "member_left_records_cleared",
        chat_id=chat_id,
        tg_user_id=tg_user_id,
        status=new_status,
        verifications=r_verif.deleted_count,
        dust_requests=r_dust.deleted_count,
        pending_joins=r_joins.deleted_count,
    )


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
    chain_type = detect_chain_type(arg) if arg else None
    if chain_type is None:
        await message.answer(
            "Usage: <code>/verify &lt;address&gt;</code>\n\n"
            "Supported formats:\n"
            "• <b>EVM</b>: <code>0x...</code> (42 chars)\n"
            "• <b>TON</b>: <code>EQ...</code> or <code>UQ...</code> (48 chars)\n"
            "• <b>Solana</b>: base58 public key (32-44 chars)"
        )
        return
    # EVM addresses are stored lowercase; TON/Solana are case-sensitive.
    address = arg.lower() if chain_type == "evm" else arg

    # Rate-limit: reject if the user has submitted a valid address within the
    # last 5 min. This prevents spamming /verify to trigger repeated expensive
    # watcher scans (500 eth_getBlockByNumber RPC calls every 30s per request).
    # Checked after address validation so malformed-arg calls are cheap and
    # don't consume or check the cooldown slot.
    now = time.monotonic()
    last_call = _verify_cooldown_store.get(user_id)
    if last_call is not None and (now - last_call) < _VERIFY_COOLDOWN_SECONDS:
        await message.answer("⏳ Please wait a few minutes before verifying again.")
        return
    _verify_cooldown_store[user_id] = now

    # Find the most recent chat the user has a pending join_request for.
    # We don't track pending join requests in Mongo (Telegram is the
    # source of truth); but we DO know which chats this user has been
    # NeedsVerify'd against because the bot DMd them. v0 simplification:
    # require exactly one registered chat; if multiple, the owner needs
    # to scope per-chat (deferred to S3).
    # Resolve the chat this user is verifying against. Returns None if the
    # user has neither an active dust_request nor a pending_join record
    # (i.e. they never clicked a real invite link).
    chat_id = await _resolve_pending_chat(db, tg_user_id=user_id)
    if chat_id is None:
        await message.answer(
            "No pending group join request found. "
            "Click a group's invite link first, then come back here to verify."
        )
        return

    chain_id = settings.dust_chain_id if chain_type == "evm" else 0
    req = await issue_dust_request(
        db,
        tg_user_id=user_id,
        chat_id=chat_id,
        address=address,
        chain_id=chain_id,
        chain_type=chain_type,
    )
    # Clean up the pending_join record — the dust_request is now the
    # authoritative source for "is this user verifying for this chat".
    await cast(Any, db.pending_joins).delete_one({"tg_user_id": user_id, "chat_id": chat_id})

    if chain_type == "ton":
        amount_display = format_amount_ton(req.amount_wei)
        await message.answer(
            "✅ Got it. Now <b>send EXACTLY this amount of TON from your wallet to itself</b>:\n\n"
            f"  <b>Amount:</b> <code>{amount_display} TON</code>\n"
            f"  <b>From → To:</b> <code>{address}</code> (yourself)\n"
            "  <b>Network:</b> TON mainnet\n\n"
            f"In nanoTON (for max precision): <code>{req.amount_wei}</code>\n\n"
            "I'll detect it automatically — usually within a minute. "
            f"This expires in {settings.dust_request_ttl_seconds // 60} min."
        )
    elif chain_type == "solana":
        amount_display = format_amount_sol(req.amount_wei)
        await message.answer(
            "✅ Got it. Now <b>send EXACTLY this amount of SOL from your wallet to itself</b>:\n\n"
            f"  <b>Amount:</b> <code>{amount_display} SOL</code>\n"
            f"  <b>From → To:</b> <code>{address}</code> (yourself)\n"
            "  <b>Network:</b> Solana mainnet\n\n"
            f"In lamports (for max precision): <code>{req.amount_wei}</code>\n\n"
            "I'll detect it automatically — usually within a minute. "
            f"This expires in {settings.dust_request_ttl_seconds // 60} min."
        )
    else:
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
        chain_type=chain_type,
        chain_id=chain_id,
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
    """Return the chat_id this user should verify against.

    Two sources, checked in order:
    1. An active (non-expired) pending dust_request — user already started
       the flow; we reuse the same chat.
    2. A pending_joins record written when the bot DM'd the user after their
       join_request — user has clicked the invite link but hasn't called
       /verify yet.

    Security: the old fallback that guessed "most recently registered chat"
    has been removed. A user with no join_request AND no active dust_request
    now gets None, preventing /verify from binding against a random chat.
    """
    # Path 1: existing active dust request (re-running /verify or /cancel).
    existing = await db.dust_requests.find_one(  # type: ignore[union-attr]
        {"tg_user_id": tg_user_id, "expires_at": {"$gt": datetime.now(tz=UTC)}}
    )
    if existing:
        return int(existing["chat_id"])

    # Path 2: pending_join record — written by on_chat_join_request when the
    # bot DM'd the user. Proves they clicked a real invite link.
    pending = await cast(Any, db.pending_joins).find_one(
        {"tg_user_id": tg_user_id},
        sort=[("created_at", -1)],
    )
    if pending:
        return int(pending["chat_id"])

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
        token_gate = await cast(Any, db.token_gates).find_one({"chat_id": chat_id})
        if token_gate:
            token_names = ", ".join(t.get("name", "?") for t in token_gate.get("tokens", []))
            lines.append(
                f"Token gate: ${token_gate.get('min_usd_value', '10')}+ of any: {token_names}"
            )
        else:
            lines.append(
                "Token gate: none (use /settokengate to set Brett/Wojak/Utya/Troll basket)"
            )
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


@router.message(Command("settokengate"))
async def on_set_token_gate(message: Message, db: AsyncIOMotorDatabase[Any]) -> None:
    """Admin-only: set the Brett/Wojak/Utya/Troll $10 USD gate for this chat."""
    from app.models.gate import Chain
    from app.models.token_gate import TokenGate, TokenSpec

    tg_user_id = message.from_user.id if message.from_user else None
    if not tg_user_id:
        return

    # If called from inside a group, use that group directly.
    # If called from a DM, find the one group owned by this user (error if ambiguous).
    if message.chat.type in ("group", "supergroup"):
        chat_id = message.chat.id
        # Verify the caller is the owner of this chat.
        chat_doc = await cast(Any, db.chats).find_one({"_id": chat_id, "owner_tg_id": tg_user_id})
        if not chat_doc:
            await message.answer("❌ You are not the registered owner of this group.")
            return
    else:
        # DM: find all chats owned by this user.
        cursor = cast(Any, db.chats).find({"owner_tg_id": tg_user_id})
        chat_docs = await cursor.to_list(length=10)
        if not chat_docs:
            await message.answer("❌ No registered group found. Add the bot to your group first.")
            return
        if len(chat_docs) > 1:
            names = "\n".join(f"• {d.get('title', d['_id'])}" for d in chat_docs)
            await message.answer(
                f"❌ You own multiple groups. Run /settokengate from inside the group you want to configure:\n\n{names}"
            )
            return
        chat_id = int(chat_docs[0]["_id"])

    gate = TokenGate(
        chat_id=chat_id,
        min_usd_value="10",
        tokens=[
            TokenSpec(
                name="Brett",
                chain=Chain.BASE,
                contract="0x532f27101965dd16442e59d40670faf5ebb142e4",
            ),
            TokenSpec(
                name="Wojak",
                chain=Chain.ETH,
                contract="0x8de39b057cc6522230ab19c0205080a8663331ef",
            ),
            TokenSpec(
                name="Utya",
                chain=Chain.TON,
                contract="EQBaCgUwOoc6gHCNln_oJzb0mVs79YG7wYoavh-o1ItaneLA",
            ),
            TokenSpec(
                name="Troll",
                chain=Chain.SOLANA,
                contract="5UUH9RTDiSpq6HKS6bp4NdU9PNJpXRXuiw6ShBTBhgH2",
            ),
        ],
    )

    doc = gate.model_dump(by_alias=True)
    gate_id = doc.pop("_id")  # _id is immutable after insert; handle separately
    await cast(Any, db.token_gates).update_one(
        {"chat_id": chat_id},
        {"$set": doc, "$setOnInsert": {"_id": gate_id}},
        upsert=True,
    )

    await message.answer(
        "✅ <b>Token gate configured</b>\n\n"
        "Users must hold <b>$10+ of any</b>:\n"
        "• Brett (Base)\n"
        "• Wojak (Ethereum)\n"
        "• Utya (TON)\n"
        "• Troll (Solana)\n\n"
        "Wallet verification via /verify (dust transfer) still required first.",
        parse_mode="HTML",
    )


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(router)
    return dp
