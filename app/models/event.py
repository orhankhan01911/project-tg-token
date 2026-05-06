from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _now() -> datetime:
    return datetime.now(tz=UTC)


class Event(BaseModel):
    """A webhook (or otherwise-deduplicable) event we've seen.

    `_id` is the idempotency key — `f"{chain}:{txhash}:{logIndex}"` for
    Alchemy/Helius transfer events; `f"telegram:join:{chat_id}:{user_id}:{date}"`
    for replays of `chat_join_request`. Insert-with-duplicate-key is the
    dedup mechanism: we never need to read first.

    `payload` is intentionally typed `dict[str, Any]` because webhook
    bodies are vendor-defined and we round-trip the original payload for
    forensics. The strongly-typed parser lives in
    `app.webhooks.{alchemy,helius}` per vendor.
    """

    model_config = ConfigDict(populate_by_name=True)

    idem_key: str = Field(alias="_id")
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)
    received_at: datetime = Field(default_factory=_now)
