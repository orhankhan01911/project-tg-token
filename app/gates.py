"""Gate evaluator.

Session 1: Approve iff one of
- the user is the chat owner (auto-approve), OR
- the user is in the chat's whitelist.
Otherwise: Decline with a structured reason.

Session 2+ extends `evaluate` with per-gate-kind logic (token / networth /
payment) — this file is the single point of routing. Handlers in
`app.bot` should never read Mongo directly; they go through `evaluate`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from motor.motor_asyncio import AsyncIOMotorDatabase


@dataclass(frozen=True)
class Approve:
    reason: str


@dataclass(frozen=True)
class Decline:
    reason: str


Decision = Approve | Decline


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

    return Decline(reason="not_whitelisted")
