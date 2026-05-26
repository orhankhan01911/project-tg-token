"""Unit tests for /verify TON and Solana address detection in bot.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.filters import CommandObject
from aiogram.types import Message, User
from mongomock_motor import AsyncMongoMockClient


def _make_db():
    return AsyncMongoMockClient()["tg_token_test"]


def _make_message(user_id: int = 111) -> MagicMock:
    msg = MagicMock(spec=Message)
    msg.from_user = User(id=user_id, is_bot=False, first_name="Tester")
    msg.answer = AsyncMock()
    return msg


def _make_bot() -> MagicMock:
    bot = MagicMock()
    bot.approve_chat_join_request = AsyncMock()
    bot.send_message = AsyncMock()
    return bot


pytestmark = pytest.mark.unit


async def test_verify_ton_address_detected() -> None:
    """TON address triggers chain_type='ton' in the verify flow."""
    db = _make_db()
    cmd = CommandObject(
        prefix="/",
        command="verify",
        mention=None,
        args="EQBaCgUwOoc6gHCNln_oJzb0mVs79YG7wYoavh-o1ItaneLA",
    )
    msg = _make_message()

    from app.bot import on_verify

    with (
        patch("app.bot._resolve_pending_chat", new_callable=AsyncMock) as mock_chat,
        patch("app.bot.issue_dust_request", new_callable=AsyncMock) as mock_issue,
        patch.dict("app.bot._verify_cooldown_store", {}, clear=True),
    ):
        mock_chat.return_value = -1001234567890
        mock_issue.return_value = MagicMock(
            amount_wei=10_001_234,
            chain_type="ton",
            chain_id=0,
        )
        await on_verify(msg, cmd, bot=_make_bot(), db=db)

    mock_issue.assert_awaited_once()
    call_kwargs = mock_issue.call_args.kwargs
    assert call_kwargs["chain_type"] == "ton"
    assert call_kwargs["chain_id"] == 0

    # DM should mention TON
    reply_text = msg.answer.call_args[0][0]
    assert "TON" in reply_text


async def test_verify_solana_address_detected() -> None:
    """Solana address triggers chain_type='solana' in the verify flow."""
    db = _make_db()
    cmd = CommandObject(
        prefix="/",
        command="verify",
        mention=None,
        args="5UUH9RTDiSpq6HKS6bp4NdU9PNJpXRXuiw6ShBTBhgH2",
    )
    msg = _make_message()

    from app.bot import on_verify

    with (
        patch("app.bot._resolve_pending_chat", new_callable=AsyncMock) as mock_chat,
        patch("app.bot.issue_dust_request", new_callable=AsyncMock) as mock_issue,
        patch.dict("app.bot._verify_cooldown_store", {}, clear=True),
    ):
        mock_chat.return_value = -1001234567890
        mock_issue.return_value = MagicMock(
            amount_wei=1_001_234,
            chain_type="solana",
            chain_id=0,
        )
        await on_verify(msg, cmd, bot=_make_bot(), db=db)

    mock_issue.assert_awaited_once()
    call_kwargs = mock_issue.call_args.kwargs
    assert call_kwargs["chain_type"] == "solana"
    assert call_kwargs["chain_id"] == 0

    reply_text = msg.answer.call_args[0][0]
    assert "SOL" in reply_text


async def test_verify_unknown_address_rejected() -> None:
    """Unrecognised address format returns usage error; issue_dust_request never called."""
    db = _make_db()
    cmd = CommandObject(
        prefix="/",
        command="verify",
        mention=None,
        args="notanaddress",
    )
    msg = _make_message()

    from app.bot import on_verify

    with (
        patch("app.bot.issue_dust_request", new_callable=AsyncMock) as mock_issue,
        patch.dict("app.bot._verify_cooldown_store", {}, clear=True),
    ):
        await on_verify(msg, cmd, bot=_make_bot(), db=db)

    mock_issue.assert_not_called()
    msg.answer.assert_called_once()
    # The response should mention supported address formats
    reply = msg.answer.call_args[0][0].lower()
    assert "evm" in reply or "ton" in reply or "solana" in reply or "address" in reply
