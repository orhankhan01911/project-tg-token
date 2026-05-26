"""Dust self-transfer verification.

Flow:
1. User clicks invite → bot DMs verify instructions.
2. User: `/verify 0xtheirAddress` in DM.
3. Bot derives a unique amount in wei from
   `base + hash(tg_user_id, chat_id, server_nonce) % 10^7`. Persists a
   `DustRequest` Mongo row with status `PENDING`. Replies with the
   amount + chain + instructions.
4. User makes a self-transfer of exactly that amount from `0xtheirAddress`
   to itself.
5. The `dust_watcher` background task polls each pending address every
   N seconds. On match: row → `DETECTED`. After `min_confirmations`:
   row → `CONFIRMED`, write `verifications`, call `approve_chat_join_request`,
   row → `APPROVED`. DM the user "✅ Verified".
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Any, cast

import httpx
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.chains.evm import get_block_number
from app.chains.solana import get_solana_current_slot
from app.chains.ton import get_ton_latest_lt
from app.logging_conf import get_logger
from app.models import DustRequest, DustRequestStatus
from app.settings import settings

log = get_logger(__name__)


def derive_amount(*, tg_user_id: int, chat_id: int, nonce: str, base: int, modulus: int) -> int:
    """Generic amount derivation: base + hash(...) % modulus.

    Used for TON (base=dust_base_nanoton, modulus=1_000_000) and
    Solana (base=dust_base_lamports, modulus=100_000).
    EVM still uses derive_amount_wei() which delegates here.
    """
    payload = f"{tg_user_id}:{chat_id}:{nonce}".encode()
    digest = hashlib.sha256(payload).digest()
    suffix = int.from_bytes(digest[:8], "big") % modulus
    return base + suffix


def derive_amount_wei(*, tg_user_id: int, chat_id: int, nonce: str) -> int:
    """Deterministic from inputs but unguessable per-user (EVM path).

    Suffix is `hash(...) % 10_000_000` — up to 7 decimal digits of
    distinguishing entropy on top of the base. Two users will collide
    on suffix only if they both hit the same hash mod, which is ~1-in-10M
    per pair; for the v0 traffic that's irrelevant. If S5+ scales blow
    past that, widen the modulus and grow the base.
    """
    return derive_amount(
        tg_user_id=tg_user_id,
        chat_id=chat_id,
        nonce=nonce,
        base=settings.dust_base_wei,
        modulus=10_000_000,
    )


def format_amount_ton(nanoton: int) -> str:
    """Render nanoTON as a human-friendly TON string (9 decimal places)."""
    s = str(nanoton).rjust(10, "0")
    integer = s[:-9].lstrip("0") or "0"
    fractional = s[-9:].rstrip("0") or "0"
    return f"{integer}.{fractional}"


def format_amount_sol(lamports: int) -> str:
    """Render lamports as a human-friendly SOL string (9 decimal places)."""
    s = str(lamports).rjust(10, "0")
    integer = s[:-9].lstrip("0") or "0"
    fractional = s[-9:].rstrip("0") or "0"
    return f"{integer}.{fractional}"


def make_nonce() -> str:
    return secrets.token_urlsafe(12)


async def issue_dust_request(
    db: AsyncIOMotorDatabase[Any],
    *,
    tg_user_id: int,
    chat_id: int,
    address: str,
    chain_id: int,
    chain_type: str = "evm",
) -> DustRequest:
    """Mint a fresh DustRequest for EVM, TON, or Solana.

    Upserts into Mongo (user re-running /verify overwrites the prior request).
    Fetches the chain's current freshness cursor (block/LT/slot) so the watcher
    can reject txs that predate the request. Falls back to None on RPC failure.
    """
    nonce = make_nonce()
    created_block: int | None = None

    if chain_type == "ton":
        amount = derive_amount(
            tg_user_id=tg_user_id,
            chat_id=chat_id,
            nonce=nonce,
            base=settings.dust_base_nanoton,
            modulus=1_000_000,
        )
        try:
            async with httpx.AsyncClient(timeout=5.0) as http:
                created_block = await get_ton_latest_lt(http, address=address)
        except Exception as exc:
            log.warning("dust_ton_lt_fetch_failed", err=repr(exc))
    elif chain_type == "solana":
        amount = derive_amount(
            tg_user_id=tg_user_id,
            chat_id=chat_id,
            nonce=nonce,
            base=settings.dust_base_lamports,
            modulus=100_000,
        )
        try:
            async with httpx.AsyncClient(timeout=5.0) as http:
                created_block = await get_solana_current_slot(http)
        except Exception as exc:
            log.warning("dust_solana_slot_fetch_failed", err=repr(exc))
    else:
        # EVM (default)
        amount = derive_amount_wei(tg_user_id=tg_user_id, chat_id=chat_id, nonce=nonce)
        try:
            async with httpx.AsyncClient(timeout=5.0) as http:
                created_block = await get_block_number(http, chain_id)
        except Exception as exc:
            log.warning("dust_created_block_fetch_failed", chain_id=chain_id, err=repr(exc))

    req = DustRequest.make(
        tg_user_id=tg_user_id,
        chat_id=chat_id,
        address=address,
        chain_id=chain_id,
        amount_wei=amount,
        ttl_seconds=settings.dust_request_ttl_seconds,
        created_block=created_block,
        chain_type=chain_type,
    )
    await cast(Any, db.dust_requests).replace_one(
        {"_id": req.id},
        req.model_dump(by_alias=True),
        upsert=True,
    )
    log.info(
        "dust_request_issued",
        tg_user_id=tg_user_id,
        chat_id=chat_id,
        address=req.address,
        chain_type=chain_type,
        chain_id=chain_id,
        amount=amount,
        created_block=created_block,
    )
    return req


async def cancel_dust_request(
    db: AsyncIOMotorDatabase[Any], *, tg_user_id: int, chat_id: int
) -> bool:
    res = await cast(Any, db.dust_requests).update_one(
        {
            "_id": DustRequest.make_id(tg_user_id, chat_id),
            "status": DustRequestStatus.PENDING.value,
        },
        {"$set": {"status": DustRequestStatus.CANCELLED.value}},
    )
    return bool(res.modified_count)


def format_amount_eth(amount_wei: int) -> str:
    """Render wei as a human-friendly ETH string with full precision."""
    s = str(amount_wei).rjust(19, "0")  # pad to at least 19 digits = 1 ETH = 10^18 wei
    integer = s[:-18].lstrip("0") or "0"
    fractional = s[-18:].rstrip("0") or "0"
    return f"{integer}.{fractional}"
