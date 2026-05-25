# tests/unit/test_setup_wizard.py
"""Unit tests for /setup wizard helper logic.

We test: address validation, threshold conversion (human → raw), gate persistence.
We do NOT test full Telegram FSM state transitions — that requires aiogram's
test client which is integration-level. The handler functions are tested
indirectly through the helpers they call.
"""

from __future__ import annotations

import pytest
from mongomock_motor import AsyncMongoMockClient

pytestmark = pytest.mark.unit


@pytest.fixture
def db():
    client = AsyncMongoMockClient()
    return client["tg_token_test"]


# ── address validation ────────────────────────────────────────────────────────


def test_valid_evm_address_passes():
    from app.setup_wizard import is_valid_evm_address

    assert is_valid_evm_address("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48") is True


def test_address_without_0x_fails():
    from app.setup_wizard import is_valid_evm_address

    assert is_valid_evm_address("A0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48") is False


def test_address_too_short_fails():
    from app.setup_wizard import is_valid_evm_address

    assert is_valid_evm_address("0x1234") is False


def test_address_non_hex_fails():
    from app.setup_wizard import is_valid_evm_address

    assert is_valid_evm_address("0xZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ") is False


# ── threshold conversion ──────────────────────────────────────────────────────


def test_human_to_raw_usdc_6_decimals():
    from app.setup_wizard import human_to_raw

    assert human_to_raw("100", decimals=6) == 100_000_000


def test_human_to_raw_18_decimals():
    from app.setup_wizard import human_to_raw

    assert human_to_raw("1", decimals=18) == 10**18


def test_human_to_raw_fractional():
    from app.setup_wizard import human_to_raw

    assert human_to_raw("0.5", decimals=18) == 5 * 10**17


def test_human_to_raw_large_number_no_float_error():
    from app.setup_wizard import human_to_raw

    # 1 billion tokens with 18 decimals — would overflow float
    result = human_to_raw("1000000000", decimals=18)
    assert result == 10**27


def test_human_to_raw_rejects_negative():
    from app.setup_wizard import human_to_raw

    with pytest.raises(ValueError):
        human_to_raw("-1", decimals=18)


def test_human_to_raw_rejects_zero():
    from app.setup_wizard import human_to_raw

    with pytest.raises(ValueError):
        human_to_raw("0", decimals=18)


def test_human_to_raw_rejects_non_number():
    from app.setup_wizard import human_to_raw

    with pytest.raises(ValueError):
        human_to_raw("abc", decimals=18)


# ── gate persistence ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_save_gate_inserts_document(db):
    from app.setup_wizard import save_gate

    await save_gate(
        db,
        chat_id=-1001,
        chain="base",
        contract="0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        raw_threshold="1000000",
    )
    doc = await db.gates.find_one({"chat_id": -1001})
    assert doc is not None
    assert doc["chain"] == "base"
    assert doc["contract"] == "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
    assert doc["threshold"] == "1000000"
    assert doc["kind"] == "token"


@pytest.mark.asyncio
async def test_save_gate_native_no_contract(db):
    from app.setup_wizard import save_gate

    await save_gate(db, chat_id=-1001, chain="eth", contract=None, raw_threshold=str(10**17))
    doc = await db.gates.find_one({"chat_id": -1001})
    assert doc["contract"] is None


@pytest.mark.asyncio
async def test_count_gates_returns_correct_number(db):
    from app.setup_wizard import count_gates

    for i in range(3):
        await db.gates.insert_one(
            {
                "_id": f"g{i}",
                "chat_id": -1001,
                "kind": "token",
                "chain": "base",
                "contract": "0x1",
                "threshold": "1",
            }
        )
    assert await count_gates(db, chat_id=-1001) == 3


@pytest.mark.asyncio
async def test_count_gates_is_chat_scoped(db):
    from app.setup_wizard import count_gates

    await db.gates.insert_one(
        {
            "_id": "g1",
            "chat_id": -1001,
            "kind": "token",
            "chain": "base",
            "contract": "0x1",
            "threshold": "1",
        }
    )
    await db.gates.insert_one(
        {
            "_id": "g2",
            "chat_id": -9999,
            "kind": "token",
            "chain": "base",
            "contract": "0x1",
            "threshold": "1",
        }
    )
    assert await count_gates(db, chat_id=-1001) == 1
