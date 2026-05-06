from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.models.gate import Chain


def _now() -> datetime:
    return datetime.now(tz=UTC)


class VerificationMethod(StrEnum):
    """How a wallet was bound to a Telegram user.

    DUST is preserved for legacy / future self-transfer records — we don't
    use it in v0 but the schema is additive (per IMPROVED_ARCHITECTURE §3)
    so old rows from a hypothetical migration stay valid.
    """

    DUST = "dust"
    SIWE = "siwe"
    SIWS = "siws"
    TON_PROOF = "ton_proof"
    ZK = "zk"


class Verification(BaseModel):
    """A wallet ↔ tg_user_id binding within a chat, with the proof artefact.

    Bound to `(tg_user_id, chat_id, address, chain)` — we accept the same
    address bound to a user across chains (different chains, different
    private-key universes for some wallets) but reject the same address
    bound to a *different* tg_user_id (sybil G9 mitigation). Enforced via
    a unique index on `(chain, address)` plus an app-side check.
    """

    tg_user_id: int
    chat_id: int
    address: str
    chain: Chain
    method: VerificationMethod
    nonce: str
    sig_or_txhash: str
    verified_at: datetime = Field(default_factory=_now)

    model_config = ConfigDict(populate_by_name=True)
