"""Background asyncio task: poll every pending DustRequest's claimed
address for a matching self-transfer, count confirmations, then
write a `verifications` row and approve the join request.

Lifecycle:
- Started by `app/__main__.py` after Mongo + Bot are up.
- One asyncio.Task per process, polling every
  `settings.dust_poll_interval_seconds` (default 30s).
- Each tick:
  1. Find all `dust_requests.status in {PENDING, DETECTED}` not expired.
  2. For each: scan recent blocks for a match; if found and confirmed,
     advance status and approve the join request.
- Crash-safe: state lives in Mongo; on restart we just continue from the
  current status. Nothing in-memory is load-bearing.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, cast

import httpx
import pymongo.errors
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramNetworkError
from motor.motor_asyncio import AsyncIOMotorDatabase
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.balance_gate import evaluate_token_gate, format_gate_decline, load_token_gate
from app.chains.evm import (
    confirmations_for,
    find_self_transfer,
    get_chain,
)
from app.chains.solana import find_solana_self_transfer
from app.chains.ton import find_ton_self_transfer
from app.logging_conf import get_logger
from app.models import (
    DustRequest,
    DustRequestStatus,
    Verification,
    VerificationMethod,
)
from app.models.gate import Chain
from app.settings import settings

log = get_logger(__name__)


class WalletAlreadyBoundError(Exception):
    """Raised when the claimed wallet address is already bound to a different
    Telegram user ID in the verifications collection.

    The caller should DM the user and decline verification rather than
    leaving the request in DETECTED state with no user-facing feedback.
    """


def _telegram_retry() -> AsyncRetrying:
    return AsyncRetrying(
        retry=retry_if_exception_type(TelegramNetworkError),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=8.0),
        reraise=True,
    )


def _chain_slug_for(chain_id: int) -> Chain:
    """Map numeric chain ID to the `Chain` enum the verifications row
    stores. Keep aligned with `app.models.gate.Chain`."""
    mapping = {
        1: Chain.ETH,
        11155111: Chain.ETH,  # Sepolia rolled under ETH for v0
        8453: Chain.BASE,
        84532: Chain.BASE_SEPOLIA,
    }
    return mapping.get(chain_id, Chain.BASE_SEPOLIA)


async def _approve_pending_join(bot: Bot, *, chat_id: int, tg_user_id: int) -> bool:
    try:
        async for attempt in _telegram_retry():
            with attempt:
                await bot.approve_chat_join_request(chat_id=chat_id, user_id=tg_user_id)
        return True
    except TelegramAPIError as e:
        log.info(
            "dust_approve_join_skipped",
            chat_id=chat_id,
            tg_user_id=tg_user_id,
            err=str(e),
        )
        return False


async def _persist_verification(
    db: AsyncIOMotorDatabase[Any],
    *,
    tg_user_id: int,
    chat_id: int,
    address: str,
    chain_id: int,
    tx_hash: str,
) -> None:
    """Write a Verification document binding the wallet to the Telegram user.

    Raises:
        WalletAlreadyBoundError: if the (chain, address) pair is already
            bound to a *different* tg_user_id. The caller must DM the user
            and mark the request as cancelled — do not leave it in DETECTED.
        pymongo.errors.DuplicateKeyError: re-raised if the conflict is on
            sig_or_txhash (tx already used for a different request) rather
            than on the chain/address pair. This is a different security
            violation and the outer loop's broad except will catch it.
    """
    chain = _chain_slug_for(chain_id)
    v = Verification(
        tg_user_id=tg_user_id,
        chat_id=chat_id,
        address=address.lower(),
        chain=chain,
        method=VerificationMethod.DUST,
        nonce="",  # dust binding is by tx hash, not nonce
        sig_or_txhash=tx_hash.lower(),
    )
    try:
        await cast(Any, db.verifications).update_one(
            {"tg_user_id": tg_user_id, "chat_id": chat_id, "chain": chain.value},
            {"$set": v.model_dump()},
            upsert=True,
        )
    except pymongo.errors.DuplicateKeyError as exc:
        # A DuplicateKeyError here means either:
        # (a) (chain, address) is bound to a DIFFERENT tg_user_id — sybil attempt.
        # (b) sig_or_txhash is already stored — tx reuse across requests.
        #
        # Distinguish by checking what's actually in the collection.
        existing = await cast(Any, db.verifications).find_one(
            {"chain": chain.value, "address": address.lower()}
        )
        if existing is not None and existing.get("tg_user_id") != tg_user_id:
            # Case (a): wallet bound to a different user.
            log.warning(
                "dust_wallet_already_bound",
                address=address.lower(),
                chain=chain.value,
                existing_tg_user_id=existing.get("tg_user_id"),
                new_tg_user_id=tg_user_id,
            )
            raise WalletAlreadyBoundError(address) from exc
        # Case (b) or same user re-binding: re-raise so the outer handler
        # logs it as an unexpected duplicate (tx reuse is a security event).
        raise


async def _persist_verification_multichain(
    db: AsyncIOMotorDatabase[Any],
    *,
    tg_user_id: int,
    chat_id: int,
    address: str,
    chain: Chain,
    tx_hash: str,
) -> None:
    """Like _persist_verification but accepts a Chain enum directly (TON/Solana).

    TON/Solana addresses are case-sensitive and must NOT be lowercased.
    Raises WalletAlreadyBoundError if the address is already bound to a
    different tg_user_id on the same chain.
    """
    v = Verification(
        tg_user_id=tg_user_id,
        chat_id=chat_id,
        address=address,  # case-sensitive for TON/Solana
        chain=chain,
        method=VerificationMethod.DUST,
        nonce="",
        sig_or_txhash=tx_hash,
    )
    try:
        await cast(Any, db.verifications).update_one(
            {"tg_user_id": tg_user_id, "chat_id": chat_id, "chain": chain.value},
            {"$set": v.model_dump()},
            upsert=True,
        )
    except pymongo.errors.DuplicateKeyError as exc:
        existing = await cast(Any, db.verifications).find_one(
            {"chain": chain.value, "address": address}
        )
        if existing is not None and existing.get("tg_user_id") != tg_user_id:
            raise WalletAlreadyBoundError(address) from exc
        raise


async def _send_dm(bot: Bot, *, tg_user_id: int, text: str) -> None:
    try:
        async for attempt in _telegram_retry():
            with attempt:
                await bot.send_message(chat_id=tg_user_id, text=text)
    except TelegramAPIError as e:
        log.warning("dust_dm_failed", tg_user_id=tg_user_id, err=str(e))


async def _process_request(
    *,
    req: DustRequest,
    db: AsyncIOMotorDatabase[Any],
    bot: Bot,
    http: httpx.AsyncClient,
) -> None:
    bind = log.bind(
        tg_user_id=req.tg_user_id,
        chat_id=req.chat_id,
        chain_type=req.chain_type,
        address=req.address,
    )

    # ── TON and Solana: instant-finality chains ───────────────────────────────
    # TON and Solana finalize within seconds. We skip the DETECTED intermediate
    # state and go straight from PENDING to APPROVED in one watcher tick.
    if req.chain_type in ("ton", "solana") and req.status == DustRequestStatus.PENDING:
        min_cursor = req.created_block or 0

        if req.chain_type == "ton":
            try:
                tx_ton = await find_ton_self_transfer(
                    http,
                    address=req.address,
                    expected_nanoton=req.amount_wei,
                    tolerance_nanoton=1_000_000,
                    min_lt=min_cursor,
                )
            except Exception as e:
                bind.warning("ton_scan_failed", err=repr(e))
                return
            if tx_ton is None:
                return
            tx_hash = tx_ton.hash
            explorer_url = f"https://tonscan.org/tx/{tx_ton.hash}"
            bind.info("ton_detected", tx=tx_hash, lt=tx_ton.lt)
            chain = Chain.TON
        else:  # solana
            try:
                tx_sol = await find_solana_self_transfer(
                    http,
                    address=req.address,
                    expected_lamports=req.amount_wei,
                    tolerance_lamports=100_000,
                    min_slot=min_cursor,
                )
            except Exception as e:
                bind.warning("solana_scan_failed", err=repr(e))
                return
            if tx_sol is None:
                return
            tx_hash = tx_sol.signature
            explorer_url = f"https://solscan.io/tx/{tx_sol.signature}"
            bind.info("solana_detected", sig=tx_hash, slot=tx_sol.slot)
            chain = Chain.SOLANA

        # Persist verification and approve.
        try:
            await _persist_verification_multichain(
                db,
                tg_user_id=req.tg_user_id,
                chat_id=req.chat_id,
                address=req.address,
                chain=chain,
                tx_hash=tx_hash,
            )
        except WalletAlreadyBoundError:
            await cast(Any, db.dust_requests).update_one(
                {"_id": req.id},
                {"$set": {"status": DustRequestStatus.CANCELLED.value}},
            )
            await _send_dm(
                bot,
                tg_user_id=req.tg_user_id,
                text=(
                    "<code>❌ Wallet already linked to another account.</code>\n\n"
                    f"<code>{req.address}</code> is already bound to a different "
                    "Telegram account. Use a different wallet address and run "
                    "<code>/verify</code> again."
                ),
            )
            bind.warning("dust_wallet_bound_to_other", address=req.address)
            return

        # Token gate check (same as EVM path).
        token_gate = await load_token_gate(db, chat_id=req.chat_id)
        if token_gate is not None:
            addr_key = "ton" if req.chain_type == "ton" else "solana"
            addresses = {addr_key: req.address}
            passed = await evaluate_token_gate(http, gate=token_gate, addresses=addresses)
            if not passed:
                await cast(Any, db.dust_requests).update_one(
                    {"_id": req.id},
                    {"$set": {"status": DustRequestStatus.APPROVED.value}},
                )
                await _send_dm(
                    bot,
                    tg_user_id=req.tg_user_id,
                    text=format_gate_decline(token_gate, verified_address=req.address),
                )
                bind.info("dust_verified_token_gate_failed", address=req.address)
                return

        approved = await _approve_pending_join(bot, chat_id=req.chat_id, tg_user_id=req.tg_user_id)
        await cast(Any, db.dust_requests).update_one(
            {"_id": req.id},
            {"$set": {"status": DustRequestStatus.APPROVED.value}},
        )
        bind.info("dust_verified", tx=tx_hash, approved_join=approved)

        msg = (
            "✅ Verified.\n\n"
            f"Wallet bound: <code>{req.address}</code>\n"
            f"Tx: {explorer_url}\n\n"
            + (
                "You've been approved into the chat."
                if approved
                else "Tap the invite link again -- you're now whitelisted."
            )
        )
        await _send_dm(bot, tg_user_id=req.tg_user_id, text=msg)
        return

    # ── EVM path (unchanged below) ────────────────────────────────────────────
    # Re-scan for the matching tx if we haven't pinned one yet.
    if req.status == DustRequestStatus.PENDING:
        try:
            tx = await find_self_transfer(
                http,
                chain_id=req.chain_id,
                address=req.address,
                expected_value_wei=req.amount_wei,
                blocks_to_scan=500,  # Base: 2s/block → ~16min window; was 15 (30s) which missed slow users
                tolerance_wei=10_000_000,  # suffix range = 10^7; wallets round to base, diff ≤ max_suffix
                min_block=req.created_block
                or 0,  # freshness gate: only accept txs mined after request was issued
            )
        except Exception as e:
            bind.warning("dust_scan_failed", err=repr(e))
            return
        if tx is None:
            return
        await cast(Any, db.dust_requests).update_one(
            {"_id": req.id},
            {
                "$set": {
                    "status": DustRequestStatus.DETECTED.value,
                    "detected_tx_hash": tx.hash,
                    "detected_at": datetime.now(tz=UTC),
                    "confirmations": 0,
                }
            },
        )
        bind.info("dust_detected", tx=tx.hash, block=tx.block_number)
        # Reload the doc so the next branch (DETECTED) sees the fresh hash.
        req = DustRequest.model_validate(
            await cast(Any, db.dust_requests).find_one({"_id": req.id})
        )

    # If detected, count confirmations.
    if req.status == DustRequestStatus.DETECTED and req.detected_tx_hash:
        try:
            # Re-fetch the tx's block via a one-off scan of the recent
            # window — cheaper than another RPC for getTransactionByHash.
            tx = await find_self_transfer(
                http,
                chain_id=req.chain_id,
                address=req.address,
                expected_value_wei=req.amount_wei,
                blocks_to_scan=500,  # same wide window for reorg checks
                tolerance_wei=10_000_000,  # keep consistent with PENDING scan
            )
        except Exception as e:
            bind.warning("dust_recheck_failed", err=repr(e))
            return
        if tx is None:
            # Reorged out. Fall back to PENDING and re-detect on next tick.
            bind.warning("dust_reorged", prior_tx=req.detected_tx_hash)
            await cast(Any, db.dust_requests).update_one(
                {"_id": req.id},
                {
                    "$set": {
                        "status": DustRequestStatus.PENDING.value,
                        "detected_tx_hash": None,
                        "detected_at": None,
                        "confirmations": 0,
                    }
                },
            )
            return
        confs = await confirmations_for(http, req.chain_id, tx.block_number)
        await cast(Any, db.dust_requests).update_one(
            {"_id": req.id}, {"$set": {"confirmations": confs}}
        )
        bind.info("dust_confirmations", n=confs)
        if confs < settings.dust_min_confirmations:
            return

        # Confirmed → write verification, approve, DM user.
        try:
            await _persist_verification(
                db,
                tg_user_id=req.tg_user_id,
                chat_id=req.chat_id,
                address=req.address,
                chain_id=req.chain_id,
                tx_hash=tx.hash,
            )
        except WalletAlreadyBoundError:
            # Wallet is bound to a different account. Mark the request
            # cancelled and DM the user — don't leave it in DETECTED forever.
            await cast(Any, db.dust_requests).update_one(
                {"_id": req.id},
                {"$set": {"status": DustRequestStatus.CANCELLED.value}},
            )
            await _send_dm(
                bot,
                tg_user_id=req.tg_user_id,
                text=(
                    "❌ <b>Wallet already linked to another account.</b>\n\n"
                    f"<code>{req.address}</code> is already bound to a different "
                    "Telegram account. Use a different wallet address and run "
                    "<code>/verify</code> again with that wallet."
                ),
            )
            bind.warning("dust_wallet_bound_to_other", address=req.address)
            return

        # Check token gate if configured for this chat.
        token_gate = await load_token_gate(db, chat_id=req.chat_id)
        if token_gate is not None:
            addresses = {"evm": req.address}  # dust-verified EVM address
            passed = await evaluate_token_gate(http, gate=token_gate, addresses=addresses)
            if not passed:
                await cast(Any, db.dust_requests).update_one(
                    {"_id": req.id},
                    {"$set": {"status": DustRequestStatus.APPROVED.value, "confirmations": confs}},
                )
                await _send_dm(
                    bot,
                    tg_user_id=req.tg_user_id,
                    text=format_gate_decline(token_gate, verified_address=req.address),
                )
                bind.info("dust_verified_token_gate_failed", address=req.address)
                return

        approved = await _approve_pending_join(bot, chat_id=req.chat_id, tg_user_id=req.tg_user_id)
        await cast(Any, db.dust_requests).update_one(
            {"_id": req.id},
            {"$set": {"status": DustRequestStatus.APPROVED.value, "confirmations": confs}},
        )
        bind.info("dust_verified", tx=tx.hash, approved_join=approved)

        chain = get_chain(req.chain_id)
        msg = (
            "✅ Verified.\n\n"
            f"Wallet bound: <code>{req.address}</code>\n"
            f"Tx: {chain.explorer}/tx/{tx.hash}\n\n"
            + (
                "You've been approved into the chat."
                if approved
                else "Tap the invite link again — you're now whitelisted."
            )
        )
        await _send_dm(bot, tg_user_id=req.tg_user_id, text=msg)


async def watcher_loop(
    db: AsyncIOMotorDatabase[Any],
    bot: Bot,
    *,
    interval_seconds: int | None = None,
) -> None:
    interval = interval_seconds or settings.dust_poll_interval_seconds
    log.info("dust_watcher_started", interval_seconds=interval)
    async with httpx.AsyncClient(timeout=10.0) as http:
        while True:
            try:
                now = datetime.now(tz=UTC)
                cursor = cast(Any, db.dust_requests).find(
                    {
                        "status": {
                            "$in": [
                                DustRequestStatus.PENDING.value,
                                DustRequestStatus.DETECTED.value,
                            ]
                        },
                        "expires_at": {"$gt": now},
                    }
                )
                pending = [DustRequest.model_validate(d) async for d in cursor]
                if pending:
                    log.info("dust_tick", pending=len(pending))
                for req in pending:
                    try:
                        await _process_request(req=req, db=db, bot=bot, http=http)
                    except Exception as e:
                        log.warning("dust_request_error", id=req.id, err=repr(e))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("dust_watcher_tick_failed", err=repr(e))
            await asyncio.sleep(interval)
