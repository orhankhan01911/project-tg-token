"""Pydantic models for the multi-token USD-priced OR-logic gate."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.models.gate import Chain  # reuse existing Chain enum


def _now() -> datetime:
    return datetime.now(tz=UTC)


class TokenSpec(BaseModel):
    """One token that qualifies the user — OR semantics across the basket."""

    name: str  # human label e.g. "Brett"
    chain: Chain  # Chain.BASE / Chain.ETH / Chain.TON / Chain.SOLANA
    contract: str  # ERC-20 address (lowercased), TON jetton master, or Solana mint


class TokenGate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(default_factory=lambda: str(uuid4()), alias="_id")
    chat_id: int
    min_usd_value: str = "10"  # stored as str to avoid float precision issues
    tokens: list[TokenSpec]
    created_at: datetime = Field(default_factory=_now)
