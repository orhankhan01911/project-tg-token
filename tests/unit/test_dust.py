"""Unit tests for dust amount derivation, request issuance, and the
human-readable formatter."""

from __future__ import annotations

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.auth.dust import (
    cancel_dust_request,
    derive_amount_wei,
    format_amount_eth,
    issue_dust_request,
    make_nonce,
)
from app.models import DustRequest, DustRequestStatus
from app.settings import settings

pytestmark = pytest.mark.unit


@pytest.fixture
def db():
    client = AsyncMongoMockClient()
    return client["tg_token_test"]


# --- amount derivation ---


def test_derive_is_deterministic_per_inputs() -> None:
    a1 = derive_amount_wei(tg_user_id=42, chat_id=-100, nonce="n1")
    a2 = derive_amount_wei(tg_user_id=42, chat_id=-100, nonce="n1")
    assert a1 == a2


def test_derive_changes_with_nonce() -> None:
    a1 = derive_amount_wei(tg_user_id=42, chat_id=-100, nonce="n1")
    a2 = derive_amount_wei(tg_user_id=42, chat_id=-100, nonce="n2")
    assert a1 != a2


def test_derive_changes_per_user() -> None:
    a1 = derive_amount_wei(tg_user_id=42, chat_id=-100, nonce="x")
    a2 = derive_amount_wei(tg_user_id=43, chat_id=-100, nonce="x")
    assert a1 != a2


def test_derive_in_expected_range() -> None:
    a = derive_amount_wei(tg_user_id=42, chat_id=-100, nonce="x")
    assert settings.dust_base_wei <= a < settings.dust_base_wei + 10_000_000


def test_make_nonce_is_unique() -> None:
    seen = {make_nonce() for _ in range(100)}
    assert len(seen) == 100


# --- format ---


def test_format_eth_zero() -> None:
    assert format_amount_eth(0) == "0.0"


def test_format_eth_one_eth() -> None:
    assert format_amount_eth(10**18) == "1.0"


def test_format_eth_dust_amount() -> None:
    # 10^10 wei = 0.00000001 ETH
    assert format_amount_eth(10**10) == "0.00000001"


def test_format_eth_full_precision_no_padding_artifacts() -> None:
    # 10^10 + 1234567 = 0.000000010001234567
    assert format_amount_eth(10**10 + 1234567) == "0.000000010001234567"


# --- issue / cancel ---


async def test_issue_dust_request_persists(db) -> None:
    req = await issue_dust_request(
        db, tg_user_id=42, chat_id=-100, address="0xABCD", chain_id=84532
    )
    assert isinstance(req, DustRequest)
    assert req.address == "0xabcd"  # lowercased
    assert req.amount_wei >= settings.dust_base_wei
    assert req.status is DustRequestStatus.PENDING

    raw = await db.dust_requests.find_one({"_id": req.id})
    assert raw is not None
    back = DustRequest.model_validate(raw)
    assert back.amount_wei == req.amount_wei


async def test_issue_replaces_existing_pending(db) -> None:
    """If the user runs /verify a second time, the new request overwrites
    the old. The old amount is no longer valid; the user must use the new."""
    req1 = await issue_dust_request(
        db, tg_user_id=42, chat_id=-100, address="0xABCD", chain_id=84532
    )
    req2 = await issue_dust_request(
        db, tg_user_id=42, chat_id=-100, address="0xABCD", chain_id=84532
    )
    assert req1.id == req2.id  # same key
    # Different nonces → different amounts (with extremely high probability)
    assert req1.amount_wei != req2.amount_wei

    n = await db.dust_requests.count_documents({"_id": req1.id})
    assert n == 1


async def test_cancel_marks_pending_request(db) -> None:
    await issue_dust_request(db, tg_user_id=42, chat_id=-100, address="0xABCD", chain_id=84532)
    ok = await cancel_dust_request(db, tg_user_id=42, chat_id=-100)
    assert ok is True

    raw = await db.dust_requests.find_one({"_id": "42:-100"})
    assert raw is not None
    assert raw["status"] == DustRequestStatus.CANCELLED.value


async def test_cancel_returns_false_when_no_pending(db) -> None:
    ok = await cancel_dust_request(db, tg_user_id=999, chat_id=-100)
    assert ok is False
