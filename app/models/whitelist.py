from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(tz=UTC)


class WhitelistEntry(BaseModel):
    """A user explicitly approved for a chat regardless of token gates.

    Keyed on numeric `tg_user_id`, not `@username` — Telegram usernames
    can change or be unset (closes G6 from RE_ANALYSIS). The composite
    index `(chat_id, tg_user_id)` is unique.
    """

    chat_id: int
    tg_user_id: int
    added_at: datetime = Field(default_factory=_now)
    added_by_tg_id: int | None = None
    note: str | None = None
