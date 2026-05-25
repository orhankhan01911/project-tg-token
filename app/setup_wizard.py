# app/setup_wizard.py
"""Telegram /setup wizard — owner configures a token gate for their group.

Flow (all in DMs):
  /setup
    → list owner's registered groups [inline keyboard]
    → pick chain [inline keyboard]
    → paste contract address (skipped for native ETH)
    → enter minimum balance
    → confirm [inline keyboard]
    → gate saved to MongoDB

Pure helper functions (is_valid_evm_address, human_to_raw, save_gate, count_gates)
are unit-tested independently of the Telegram FSM handlers.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.logging_conf import get_logger

log = get_logger(__name__)

router = Router()
router.message.filter(F.chat.type == "private")  # DMs only

MAX_GATES = 5
_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


# ── pure helpers (unit-testable) ─────────────────────────────────────────────


def is_valid_evm_address(address: str) -> bool:
    """Return True if address is a well-formed 0x-prefixed 40-hex-char EVM address."""
    return bool(_ADDRESS_RE.match(address))


def human_to_raw(amount_str: str, *, decimals: int) -> int:
    """Convert a human-readable token amount to raw integer units.

    Uses Decimal arithmetic to avoid float precision errors on large amounts
    (e.g. 1_000_000_000 tokens with 18 decimals exceeds float64 precision).

    Raises ValueError on non-numeric input, zero, or negative values.
    """
    try:
        d = Decimal(amount_str)
    except InvalidOperation:
        raise ValueError(f"not a number: {amount_str!r}") from None
    if d <= 0:
        raise ValueError(f"must be positive, got {d}")
    return int(d * Decimal(10**decimals))


async def save_gate(
    db: AsyncIOMotorDatabase[Any],
    *,
    chat_id: int,
    chain: str,
    contract: str | None,
    raw_threshold: str,
) -> None:
    """Insert a gate document into the gates collection."""
    await db.gates.insert_one(
        {
            "_id": str(uuid.uuid4()),
            "chat_id": chat_id,
            "kind": "token",
            "chain": chain,
            "contract": contract,
            "threshold": raw_threshold,
            "created_at": datetime.now(tz=UTC),
        }
    )


async def count_gates(db: AsyncIOMotorDatabase[Any], *, chat_id: int) -> int:
    """Return the number of gates configured for a chat."""
    return await db.gates.count_documents({"chat_id": chat_id})


# ── FSM states ───────────────────────────────────────────────────────────────


class SetupGate(StatesGroup):
    select_chat = State()
    select_chain = State()
    input_contract = State()
    input_threshold = State()
    confirm = State()


# ── keyboards ────────────────────────────────────────────────────────────────


def _chain_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Ethereum", callback_data="chain:eth:token"),
                InlineKeyboardButton(text="Base", callback_data="chain:base:token"),
            ],
            [
                InlineKeyboardButton(text="Native ETH", callback_data="chain:eth:native"),
                InlineKeyboardButton(text="Native ETH (Base)", callback_data="chain:base:native"),
            ],
        ]
    )


def _confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✓ Save", callback_data="confirm:yes"),
                InlineKeyboardButton(text="✗ Cancel", callback_data="confirm:no"),
            ]
        ]
    )


# ── handlers ─────────────────────────────────────────────────────────────────


@router.message(Command("setup"))
async def cmd_setup(
    message: Message,
    state: FSMContext,
    db: AsyncIOMotorDatabase[Any],
) -> None:
    user_id = message.from_user.id  # type: ignore[union-attr]
    chats = await db.chats.find({"owner_tg_id": user_id}).to_list(None)

    if not chats:
        await message.answer(
            "No registered groups found.\nAdd me to a group as admin first, then come back here."
        )
        return

    buttons = [
        [
            InlineKeyboardButton(
                text=c.get("title") or str(c["_id"]),
                callback_data=f"chat:{c['_id']}",
            )
        ]
        for c in chats
    ]
    await message.answer(
        "Which group do you want to configure?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await state.set_state(SetupGate.select_chat)


@router.callback_query(SetupGate.select_chat, F.data.startswith("chat:"))
async def cb_select_chat(
    query: CallbackQuery,
    state: FSMContext,
    db: AsyncIOMotorDatabase[Any],
) -> None:
    chat_id = int(query.data.split(":")[1])  # type: ignore[union-attr]
    n = await count_gates(db, chat_id=chat_id)
    if n >= MAX_GATES:
        await query.message.edit_text(  # type: ignore[union-attr]
            f"This group already has {MAX_GATES} gates (maximum). Remove one before adding another."
        )
        await state.clear()
        await query.answer()
        return

    await state.update_data(chat_id=chat_id)
    await query.message.edit_text(  # type: ignore[union-attr]
        "Which blockchain is your token on?",
        reply_markup=_chain_kb(),
    )
    await state.set_state(SetupGate.select_chain)
    await query.answer()


@router.callback_query(SetupGate.select_chain, F.data.startswith("chain:"))
async def cb_select_chain(
    query: CallbackQuery,
    state: FSMContext,
) -> None:
    _, chain, mode = query.data.split(":")  # type: ignore[union-attr]
    native = mode == "native"
    await state.update_data(chain=chain, native=native)

    if native:
        await query.message.edit_text(  # type: ignore[union-attr]
            "Minimum balance? Enter a number.\nExample: 0.1 means 0.1 ETH"
        )
        await state.set_state(SetupGate.input_threshold)
    else:
        await query.message.edit_text(  # type: ignore[union-attr]
            "Paste the token contract address (0x...):"
        )
        await state.set_state(SetupGate.input_contract)
    await query.answer()


@router.message(SetupGate.input_contract)
async def msg_input_contract(
    message: Message,
    state: FSMContext,
    http: Any,
) -> None:
    contract = (message.text or "").strip()
    if not is_valid_evm_address(contract):
        await message.answer("Invalid address. Paste a valid 0x... contract address:")
        return

    data = await state.get_data()
    from app.chains.evm import chain_id_for, erc20_decimals

    cid = chain_id_for(data["chain"])
    if cid is None:
        await message.answer("Unsupported chain. Start over with /setup.")
        await state.clear()
        return

    decimals = 18
    try:
        decimals = await erc20_decimals(http, chain_id=cid, contract=contract)
    except Exception:
        log.warning("decimals_fetch_failed", contract=contract)

    await state.update_data(contract=contract, decimals=decimals)
    await message.answer(
        f"Token detected ({decimals} decimals).\n"
        "Minimum balance? Enter a number.\n"
        "Example: 100 means 100 tokens"
    )
    await state.set_state(SetupGate.input_threshold)


@router.message(SetupGate.input_threshold)
async def msg_input_threshold(
    message: Message,
    state: FSMContext,
) -> None:
    text = (message.text or "").strip()
    data = await state.get_data()
    native: bool = data.get("native", False)
    decimals: int = 18 if native else data.get("decimals", 18)

    try:
        raw = human_to_raw(text, decimals=decimals)
    except ValueError:
        await message.answer("Enter a positive number (e.g. 100):")
        return

    await state.update_data(human_amount=text, raw_threshold=str(raw))

    chain = data["chain"]
    contract: str | None = data.get("contract")
    contract_display = f"{contract[:10]}..." if contract else "native ETH"

    await message.answer(
        f"Confirm gate:\n"
        f"  Chain:   {chain}\n"
        f"  Token:   {contract_display}\n"
        f"  Minimum: {text}\n\n"
        "Save?",
        reply_markup=_confirm_kb(),
    )
    await state.set_state(SetupGate.confirm)


@router.callback_query(SetupGate.confirm, F.data.startswith("confirm:"))
async def cb_confirm(
    query: CallbackQuery,
    state: FSMContext,
    db: AsyncIOMotorDatabase[Any],
) -> None:
    if query.data == "confirm:no":
        await query.message.edit_text("Cancelled.")  # type: ignore[union-attr]
        await state.clear()
        await query.answer()
        return

    data = await state.get_data()
    await save_gate(
        db,
        chat_id=data["chat_id"],
        chain=data["chain"],
        contract=data.get("contract"),
        raw_threshold=data["raw_threshold"],
    )

    contract: str | None = data.get("contract")
    contract_display = f"{contract[:10]}..." if contract else "native ETH"
    await query.message.edit_text(  # type: ignore[union-attr]
        f"✓ Gate saved.\n"
        f"New members must hold ≥ {data['human_amount']} of "
        f"{contract_display} on {data['chain']}."
    )
    await state.clear()
    await query.answer()
