"""Unit tests for TokenSpec and TokenGate models."""

from __future__ import annotations

import pytest

from app.models.gate import Chain
from app.models.token_gate import TokenGate, TokenSpec

pytestmark = pytest.mark.unit


def _make_spec(
    name: str = "Brett",
    chain: Chain = Chain.BASE,
    contract: str = "0xabcdef1234567890abcdef1234567890abcdef12",
) -> TokenSpec:
    return TokenSpec(name=name, chain=chain, contract=contract)


def test_token_spec_round_trip() -> None:
    """TokenSpec serialises and deserialises without data loss."""
    spec = _make_spec()
    dumped = spec.model_dump()
    restored = TokenSpec.model_validate(dumped)
    assert restored == spec
    assert restored.name == "Brett"
    assert restored.chain == Chain.BASE
    assert restored.contract == "0xabcdef1234567890abcdef1234567890abcdef12"


def test_token_gate_default_uuid_id() -> None:
    """TokenGate generates a UUID id when none is supplied."""
    gate = TokenGate(chat_id=123456789, tokens=[_make_spec()])
    assert gate.id
    assert len(gate.id) == 36  # standard UUID string length
    # second instance gets a different id
    gate2 = TokenGate(chat_id=123456789, tokens=[_make_spec()])
    assert gate.id != gate2.id


def test_token_gate_accepts_id_alias() -> None:
    """TokenGate accepts _id alias (for Mongo round-trips)."""
    custom_id = "custom-mongo-id-123"
    gate = TokenGate(**{"_id": custom_id, "chat_id": 99, "tokens": [_make_spec()]})
    assert gate.id == custom_id


def test_token_gate_multiple_token_specs() -> None:
    """TokenGate.tokens can hold multiple TokenSpec entries (OR logic basket)."""
    specs = [
        _make_spec(name="Brett", chain=Chain.BASE),
        _make_spec(name="PEPE", chain=Chain.ETH, contract="0xdeadbeef" + "0" * 32),
        _make_spec(
            name="BONK", chain=Chain.SOLANA, contract="DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
        ),
    ]
    gate = TokenGate(chat_id=777, min_usd_value="50", tokens=specs)
    assert len(gate.tokens) == 3
    assert gate.tokens[0].name == "Brett"
    assert gate.tokens[1].chain == Chain.ETH
    assert gate.tokens[2].chain == Chain.SOLANA
    assert gate.min_usd_value == "50"
