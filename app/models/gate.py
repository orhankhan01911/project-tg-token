from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


def _now() -> datetime:
    return datetime.now(tz=UTC)


class GateKind(StrEnum):
    TOKEN = "token"
    NETWORTH = "networth"
    PAYMENT = "payment"


class Chain(StrEnum):
    """Supported chains. Values are kept readable rather than chain-id ints
    so logs are scrutable without a lookup table; the EVM chain-id mapping
    lives in `app.chains.evm.CHAIN_RPC` and is the single source of truth
    for RPC dispatch."""

    ETH = "eth"
    BASE = "base"
    BASE_SEPOLIA = "base-sepolia"
    BNB = "bnb"
    POLYGON = "polygon"
    SOLANA = "solana"
    SOLANA_DEVNET = "solana-devnet"
    TON = "ton"


class Gate(BaseModel):
    """A single gate applied to a chat.

    `threshold` is `str` (not `int`) because ERC-20 amounts in raw units
    routinely exceed 64-bit; downstream code parses to `int(threshold)` or
    Python's arbitrary-precision int as needed. USD net-worth thresholds
    are also strings for symmetry — we never want a float in the schema.

    `contract` is unset for native-token gates (`Chain.ETH` native ether,
    Solana native SOL, etc.) and for net-worth gates (which span tokens).
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(alias="_id")
    chat_id: int
    kind: GateKind
    chain: Chain | None = None
    contract: str | None = None
    threshold: str
    created_at: datetime = Field(default_factory=_now)
