"""Unit tests for TON/Solana watcher dispatch in dust_watcher._process_request."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.dust_request import DustRequest, DustRequestStatus

pytestmark = pytest.mark.unit


def _make_req(chain_type: str, address: str, amount: int) -> DustRequest:
    return DustRequest(
        _id="111:222",
        tg_user_id=111,
        chat_id=222,
        address=address,
        chain_id=0,
        amount_wei=amount,
        expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
        status=DustRequestStatus.PENDING,
        chain_type=chain_type,
        created_block=100,
    )


async def test_ton_request_detected_and_approved() -> None:
    """TON request goes directly PENDING -> APPROVED (no DETECTED intermediate)."""
    from app.chains.ton import TonTxRecord
    from app.dust_watcher import _process_request

    req = _make_req("ton", "EQBaCgUwOoc6gHCNln_oJzb0mVs79YG7wYoavh-o1ItaneLA", 10_001_234)
    ton_tx = TonTxRecord(hash="tonhash123", lt=200, value=10_001_234)

    db = MagicMock()
    db.dust_requests.update_one = AsyncMock()
    db.verifications.update_one = AsyncMock()

    bot = MagicMock()
    bot.approve_chat_join_request = AsyncMock(return_value=True)
    bot.send_message = AsyncMock()

    with (
        patch(
            "app.dust_watcher.find_ton_self_transfer", new_callable=AsyncMock, return_value=ton_tx
        ),
        patch("app.dust_watcher._persist_verification_multichain", new_callable=AsyncMock),
        patch("app.dust_watcher._approve_pending_join", new_callable=AsyncMock, return_value=True),
        patch("app.dust_watcher._send_dm", new_callable=AsyncMock),
        patch("app.dust_watcher.load_token_gate", new_callable=AsyncMock, return_value=None),
    ):
        await _process_request(req=req, db=db, bot=bot, http=MagicMock())

    # Should update to APPROVED — no DETECTED state
    update_calls = db.dust_requests.update_one.call_args_list
    statuses = [c[0][1]["$set"]["status"] for c in update_calls]
    assert DustRequestStatus.APPROVED.value in statuses
    assert DustRequestStatus.DETECTED.value not in statuses


async def test_solana_request_detected_and_approved() -> None:
    """Solana request goes directly PENDING -> APPROVED (no DETECTED intermediate)."""
    from app.chains.solana import SolanaTxRecord
    from app.dust_watcher import _process_request

    req = _make_req("solana", "5UUH9RTDiSpq6HKS6bp4NdU9PNJpXRXuiw6ShBTBhgH2", 1_001_234)
    sol_tx = SolanaTxRecord(signature="solsig123", slot=300, lamports=1_001_234)

    db = MagicMock()
    db.dust_requests.update_one = AsyncMock()
    db.verifications.update_one = AsyncMock()

    with (
        patch(
            "app.dust_watcher.find_solana_self_transfer",
            new_callable=AsyncMock,
            return_value=sol_tx,
        ),
        patch("app.dust_watcher._persist_verification_multichain", new_callable=AsyncMock),
        patch("app.dust_watcher._approve_pending_join", new_callable=AsyncMock, return_value=True),
        patch("app.dust_watcher._send_dm", new_callable=AsyncMock),
        patch("app.dust_watcher.load_token_gate", new_callable=AsyncMock, return_value=None),
    ):
        await _process_request(req=req, db=db, bot=MagicMock(), http=MagicMock())

    update_calls = db.dust_requests.update_one.call_args_list
    statuses = [c[0][1]["$set"]["status"] for c in update_calls]
    assert DustRequestStatus.APPROVED.value in statuses
    assert DustRequestStatus.DETECTED.value not in statuses


async def test_ton_request_not_found_returns_early() -> None:
    """If no matching TON tx found, _process_request returns without updating DB."""
    from app.dust_watcher import _process_request

    req = _make_req("ton", "EQBaCgUwOoc6gHCNln_oJzb0mVs79YG7wYoavh-o1ItaneLA", 10_001_234)

    db = MagicMock()
    db.dust_requests.update_one = AsyncMock()

    with patch(
        "app.dust_watcher.find_ton_self_transfer", new_callable=AsyncMock, return_value=None
    ):
        await _process_request(req=req, db=db, bot=MagicMock(), http=MagicMock())

    db.dust_requests.update_one.assert_not_called()
