"""Gate evaluator.

Three outcomes per join request:

- **Approve** — user passes all checks (owner / whitelist / verification + token gates).
- **Decline** — permanently rejected (chat not registered, insufficient token balance).
- **NeedsVerify** — user must prove wallet ownership first. Bot DMs /verify instructions.

evaluate() is the single entry point. All gate logic lives here.
Token balance reads go through app.chains.evm — no direct RPC calls in this file.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.chains.evm import chain_id_for, erc20_balance_of, eth_balance_of
from app.logging_conf import get_logger
from app.settings import settings

log = get_logger(__name__)


@dataclass(frozen=True)
class Approve:
    reason: str


@dataclass(frozen=True)
class Decline:
    reason: str


@dataclass(frozen=True)
class NeedsVerify:
    reason: str


Decision = Approve | Decline | NeedsVerify


async def _check_gates(
    db: AsyncIOMotorDatabase[Any],
    http: httpx.AsyncClient,
    *,
    chat_id: int,
    address: str,
) -> Decision | None:
    """Load gates for chat and check balances. Returns Approve/Decline or None if no gates."""
    gates = await cast(Any, db.gates).find({"chat_id": chat_id}).to_list(None)
    if not gates:
        return Approve(reason="wallet_verified")

    for gate in gates:
        gate_chain: str = gate.get("chain") or "base"
        cid = chain_id_for(gate_chain)
        if cid is None:
            # Non-EVM chain (Solana, TON) — reader not built yet, skip this gate
            log.info("gate_chain_skipped", chain=gate_chain, gate_id=gate.get("_id"))
            continue

        contract: str | None = gate.get("contract")
        threshold = int(gate["threshold"])

        if contract:
            balance = await erc20_balance_of(http, chain_id=cid, contract=contract, address=address)
        else:
            balance = await eth_balance_of(http, chain_id=cid, address=address)

        if balance < threshold:
            log.info(
                "gate_failed",
                chat_id=chat_id,
                gate_id=gate.get("_id"),
                balance=balance,
                threshold=threshold,
            )
            return Decline(reason="insufficient_balance")

    return Approve(reason="token_gate_passed")


async def evaluate(
    db: AsyncIOMotorDatabase[Any],
    http: httpx.AsyncClient,
    *,
    chat_id: int,
    tg_user_id: int,
) -> Decision:
    chat = await cast(Any, db.chats).find_one({"_id": chat_id})
    if chat is None:
        return Decline(reason="chat_not_registered")

    if chat.get("owner_tg_id") == tg_user_id:
        return Approve(reason="chat_owner")

    wl = await cast(Any, db.whitelist).find_one({"chat_id": chat_id, "tg_user_id": tg_user_id})
    if wl is not None:
        return Approve(reason="whitelist")

    fresh_cutoff = datetime.now(tz=UTC) - timedelta(seconds=settings.verification_ttl_seconds)
    verif = await cast(Any, db.verifications).find_one(
        {
            "tg_user_id": tg_user_id,
            "chat_id": chat_id,
            "verified_at": {"$gte": fresh_cutoff},
        }
    )
    if verif is None:
        return NeedsVerify(reason="requires_verification")

    return await _check_gates(db, http, chat_id=chat_id, address=verif["address"])
