"""Round-trip every Mongo collection model. mongomock-motor speaks the
same wire types as real Mongo (BSON dates, etc.), so the round-trip below
is the same one production hits — minus the unique-index enforcement,
which moves to tests/integration/test_mongo_indexes.py.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.models import (
    Chain,
    Chat,
    Event,
    Gate,
    GateKind,
    Verification,
    VerificationMethod,
    WhitelistEntry,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def db():
    client = AsyncMongoMockClient()
    return client["tg_token_test"]


async def test_chat_round_trip(db) -> None:
    c = Chat(_id=-100, owner_tg_id=42)
    await db.chats.insert_one(c.model_dump(by_alias=True))
    raw = await db.chats.find_one({"_id": -100})
    back = Chat.model_validate(raw)
    assert back.chat_id == -100
    assert back.owner_tg_id == 42


async def test_gate_round_trip_with_chain_and_threshold(db) -> None:
    g = Gate(
        _id="g1",
        chat_id=-100,
        kind=GateKind.TOKEN,
        chain=Chain.BASE_SEPOLIA,
        contract="0xdeadbeef",
        threshold="1000000000000000000",
    )
    await db.gates.insert_one(g.model_dump(by_alias=True))
    raw = await db.gates.find_one({"_id": "g1"})
    back = Gate.model_validate(raw)
    assert back.kind is GateKind.TOKEN
    assert back.chain is Chain.BASE_SEPOLIA
    assert back.threshold == "1000000000000000000"


async def test_gate_native_token_no_contract() -> None:
    g = Gate(_id="native", chat_id=-100, kind=GateKind.TOKEN, chain=Chain.ETH, threshold="1")
    assert g.contract is None


async def test_verification_round_trip(db) -> None:
    v = Verification(
        tg_user_id=1,
        chat_id=-100,
        address="0xabc",
        chain=Chain.BASE_SEPOLIA,
        method=VerificationMethod.SIWE,
        nonce="n",
        sig_or_txhash="0xsig",
    )
    await db.verifications.insert_one(v.model_dump())
    raw = await db.verifications.find_one({"tg_user_id": 1, "chat_id": -100})
    back = Verification.model_validate(raw)
    assert back.method is VerificationMethod.SIWE
    assert back.chain is Chain.BASE_SEPOLIA


async def test_whitelist_entry_defaults_added_at_to_now() -> None:
    entry = WhitelistEntry(chat_id=-100, tg_user_id=42)
    assert entry.added_at <= datetime.now(tz=UTC)


async def test_event_round_trip(db) -> None:
    e = Event(
        _id="base:0xtx:0",
        kind="alchemy.address_activity",
        payload={"hash": "0xtx", "value": "1"},
    )
    await db.events.insert_one(e.model_dump(by_alias=True))
    raw = await db.events.find_one({"_id": "base:0xtx:0"})
    back = Event.model_validate(raw)
    assert back.idem_key == "base:0xtx:0"
    assert back.payload["hash"] == "0xtx"
