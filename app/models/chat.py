from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field


def _now() -> datetime:
    return datetime.now(tz=UTC)


class Chat(BaseModel):
    """A Telegram chat the bot is gating.

    `_id` is the Telegram chat id (negative for groups/supergroups). Storing
    chat_id as `_id` lets us upsert on join-request without an extra index
    lookup.

    `gate_logic` is a placeholder for the gate-combination DSL we'll need
    once a chat has more than one gate; in S1 it's literally the empty
    string and `evaluate` short-circuits on whitelist membership.
    """

    model_config = ConfigDict(populate_by_name=True)

    chat_id: int = Field(alias="_id")
    owner_tg_id: int
    gate_logic: str = ""
    created_at: datetime = Field(default_factory=_now)
