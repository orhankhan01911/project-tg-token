from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


def _now() -> datetime:
    return datetime.now(tz=UTC)


class DustRequestStatus(StrEnum):
    PENDING = "pending"
    DETECTED = "detected"  # tx seen, awaiting confirmations
    CONFIRMED = "confirmed"  # >= min_confirmations, ready for approve
    APPROVED = "approved"  # bot approved the join request
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class DustRequest(BaseModel):
    """A pending self-transfer verification request.

    The amount is unique per (tg_user_id, chat_id, server_nonce) so we can
    distinguish concurrent requests. The user sends `amount_wei` from
    `address` to `address` (self-transfer); on a chain configured by
    `chain_id`. The watcher polls `address` every N seconds, looks for a
    matching tx, and on `min_confirmations` writes a `verifications` row +
    approves the join.

    `_id` is `f"{tg_user_id}:{chat_id}"` so a user re-running /verify on
    the same chat overwrites the previous (still-pending) request — the
    last one wins.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(alias="_id")
    tg_user_id: int
    chat_id: int
    address: str  # 0x... lowercased; the wallet they claim to control
    chain_id: int
    amount_wei: int  # exact match — no slack
    expires_at: datetime
    status: DustRequestStatus = DustRequestStatus.PENDING
    detected_tx_hash: str | None = None
    detected_at: datetime | None = None
    confirmations: int = 0
    created_at: datetime = Field(default_factory=_now)
    # Block number at the time the request was issued. Used by the watcher to
    # enforce tx freshness: only txs mined at or after this block are eligible.
    # None on legacy rows (pre-patch) — watcher falls back to no freshness gate.
    created_block: int | None = None

    @staticmethod
    def make_id(tg_user_id: int, chat_id: int) -> str:
        return f"{tg_user_id}:{chat_id}"

    @staticmethod
    def make(
        *,
        tg_user_id: int,
        chat_id: int,
        address: str,
        chain_id: int,
        amount_wei: int,
        ttl_seconds: int,
        created_block: int | None = None,
    ) -> DustRequest:
        now = _now()
        return DustRequest(
            _id=DustRequest.make_id(tg_user_id, chat_id),
            tg_user_id=tg_user_id,
            chat_id=chat_id,
            address=address.lower(),
            chain_id=chain_id,
            amount_wei=amount_wei,
            expires_at=now + timedelta(seconds=ttl_seconds),
            created_at=now,
            created_block=created_block,
        )
