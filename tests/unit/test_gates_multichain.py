"""Unit tests for multi-chain address collection in gates.evaluate()."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.settings import settings

pytestmark = pytest.mark.unit

_FRESH = datetime.now(tz=UTC)
_CUTOFF_OK = _FRESH - timedelta(seconds=settings.verification_ttl_seconds - 60)


def _make_db():
    return AsyncMongoMockClient()["tg_token_test"]


async def test_evaluate_collects_all_chain_verifications() -> None:
    """evaluate() collects TON + Solana + EVM verifications into addresses dict."""
    from app.gates import Approve, evaluate

    db = _make_db()
    await db.chats.insert_one({"_id": -1001, "owner_tg_id": 1})

    # Seed three separate verifications — one per chain
    await db.verifications.insert_many(
        [
            {
                "tg_user_id": 42,
                "chat_id": -1001,
                "address": "0xd8da6bf26964af9d7eed9e03e53415d37aa96045",
                "chain": "base-sepolia",
                "method": "dust",
                "nonce": "",
                "sig_or_txhash": "0xtx",
                "verified_at": _CUTOFF_OK,
            },
            {
                "tg_user_id": 42,
                "chat_id": -1001,
                "address": "EQBaCgUwOoc6gHCNln_oJzb0mVs79YG7wYoavh-o1ItaneLA",
                "chain": "ton",
                "method": "dust",
                "nonce": "",
                "sig_or_txhash": "tonhash",
                "verified_at": _CUTOFF_OK,
            },
            {
                "tg_user_id": 42,
                "chat_id": -1001,
                "address": "5UUH9RTDiSpq6HKS6bp4NdU9PNJpXRXuiw6ShBTBhgH2",
                "chain": "solana",
                "method": "dust",
                "nonce": "",
                "sig_or_txhash": "solsig",
                "verified_at": _CUTOFF_OK,
            },
        ]
    )

    captured_addresses: dict[str, str] = {}

    async def _fake_evaluate_gate(http, *, gate, addresses):
        captured_addresses.update(addresses)
        return True

    with (
        patch(
            "app.gates.load_token_gate",
            new_callable=AsyncMock,
            return_value={"type": "erc20", "contract": "0xtoken", "threshold": 1},
        ),
        patch("app.gates.evaluate_token_gate", side_effect=_fake_evaluate_gate),
    ):
        result = await evaluate(db, http=AsyncMock(), chat_id=-1001, tg_user_id=42)

    assert isinstance(result, Approve)
    assert result.reason == "token_balance_gate_passed"
    assert captured_addresses["evm"] == "0xd8da6bf26964af9d7eed9e03e53415d37aa96045"
    assert captured_addresses["ton"] == "EQBaCgUwOoc6gHCNln_oJzb0mVs79YG7wYoavh-o1ItaneLA"
    assert captured_addresses["solana"] == "5UUH9RTDiSpq6HKS6bp4NdU9PNJpXRXuiw6ShBTBhgH2"


async def test_evaluate_non_evm_only_approves_without_legacy_gate() -> None:
    """TON-only verification with no token gate returns Approve(wallet_verified_non_evm)."""
    from app.gates import Approve, evaluate

    db = _make_db()
    await db.chats.insert_one({"_id": -1001, "owner_tg_id": 1})

    await db.verifications.insert_one(
        {
            "tg_user_id": 42,
            "chat_id": -1001,
            "address": "EQBaCgUwOoc6gHCNln_oJzb0mVs79YG7wYoavh-o1ItaneLA",
            "chain": "ton",
            "method": "dust",
            "nonce": "",
            "sig_or_txhash": "tonhash",
            "verified_at": _CUTOFF_OK,
        }
    )

    # No token gate, no legacy EVM gates — non-EVM wallet → approve directly
    with patch("app.gates.load_token_gate", new_callable=AsyncMock, return_value=None):
        result = await evaluate(db, http=AsyncMock(), chat_id=-1001, tg_user_id=42)

    assert isinstance(result, Approve)
    assert result.reason == "wallet_verified_non_evm"
