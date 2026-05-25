"""Pydantic models for every Mongo collection.

Conventions:
- Datetimes are UTC-aware. We store as native `datetime` (Mongo persists as
  BSON date in UTC).
- Numeric ids that exceed 32-bit (Telegram chat ids fit comfortably in
  int64; on-chain values like ERC-20 thresholds can exceed it) — use `str`
  for the latter, document at the field.
- Enums are `StrEnum` so they compare cleanly to raw values pulled from
  Mongo without extra serialization shims.
- Every model has a `_now()` factory for `created_at` to keep tests
  deterministic-friendly (we patch `datetime.now` rather than the model).
"""

from app.models.chat import Chat
from app.models.dust_request import DustRequest, DustRequestStatus
from app.models.event import Event
from app.models.gate import Chain, Gate, GateKind
from app.models.verification import Verification, VerificationMethod
from app.models.whitelist import WhitelistEntry

__all__ = [
    "Chain",
    "Chat",
    "DustRequest",
    "DustRequestStatus",
    "Event",
    "Gate",
    "GateKind",
    "Verification",
    "VerificationMethod",
    "WhitelistEntry",
]
