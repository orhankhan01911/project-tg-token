"""Gate evaluator.

Three outcomes per join request:

- **Approve** — the user passes some gate (chat_owner / whitelist / fresh
  SIWE verification within the TTL window). Bot calls `approve_chat_join_request`.
- **Decline** — the request is final-rejected (chat_not_registered, etc.).
  Bot calls `decline_chat_join_request`.
- **NeedsVerify** — the user needs to do something on their end (e.g. sign
  SIWE in the Mini App). Bot DMs the user the verify link and leaves the
  join request pending; once the user verifies, the API endpoint approves
  the still-pending request via Bot API.

Session 1 had only Approve/Decline. Session 2 adds the SIWE check + the
NeedsVerify branch. Session 3+ extends with token / net-worth gates,
all routed through this single function.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.settings import settings


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


async def evaluate(
    db: AsyncIOMotorDatabase[Any],
    *,
    chat_id: int,
    tg_user_id: int,
) -> Decision:
    chat = await cast(Any, db.chats).find_one({"_id": chat_id})
    if chat is None:
        # The bot was added to a chat we never registered. Production: we
        # should not auto-approve random groups someone added the bot to —
        # that's a footgun for the bot operator. Decline by default.
        return Decline(reason="chat_not_registered")

    if chat.get("owner_tg_id") == tg_user_id:
        return Approve(reason="chat_owner")

    wl = await cast(Any, db.whitelist).find_one(
        {"chat_id": chat_id, "tg_user_id": tg_user_id}
    )
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
    if verif is not None:
        return Approve(reason="siwe_verified")

    return NeedsVerify(reason="requires_siwe_verification")
