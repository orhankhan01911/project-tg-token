# Token Gate Balance Check — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After a user proves wallet ownership via dust verification, check that their wallet holds ≥ threshold of the configured token before approving group entry. Group owners configure gates via a `/setup` Telegram wizard.

**Architecture:** Four pieces in dependency order — (1) balance reader functions added to `evm.py`, (2) `evaluate()` updated to load and check gates after verification, (3) `/setup` FSM wizard in a new file, (4) bot wiring connects everything. All existing tests must remain green.

**Tech Stack:** Python 3.12, aiogram 3, Motor, httpx, respx (tests), pytest-asyncio, `unittest.mock.patch` for async mocking.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `app/chains/evm.py` | Modify | Add `erc20_balance_of`, `eth_balance_of`, `erc20_decimals`, `chain_id_for`, `CHAIN_ID_MAP` |
| `app/gates.py` | Modify | Add `http` param to `evaluate()`; load gates and check balances after verification |
| `app/setup_wizard.py` | Create | aiogram FSM: `/setup` wizard — 5 states, owner configures a token gate |
| `app/bot.py` | Modify | Add `my_chat_member` auto-register handler; include `setup_router`; pass `http` to `evaluate()` |
| `tests/unit/test_evm_balance.py` | Create | Unit tests for balance reader functions |
| `tests/unit/test_gates_token.py` | Create | Unit tests for gate balance evaluation |
| `tests/unit/test_setup_wizard.py` | Create | Unit tests for wizard validation and gate persistence |

---

## Task 1: Balance Reader — tests first

**Files:**
- Create: `tests/unit/test_evm_balance.py`

- [ ] **Step 1.1 — Write failing tests**

```python
# tests/unit/test_evm_balance.py
"""Unit tests for ERC-20 and native balance reader functions."""

from __future__ import annotations

import httpx
import pytest
import respx

pytestmark = pytest.mark.unit

RPC_URL = "https://sepolia.base.org"  # Base Sepolia public RPC (no ALCHEMY_API_KEY in test env)
CONTRACT = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
ADDRESS   = "0xd8da6bf26964af9d7eed9e03e53415d37aa96045"


def _rpc_ok(result: str) -> httpx.Response:
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})


# ── erc20_balance_of ─────────────────────────────────────────────────────────

@respx.mock
@pytest.mark.asyncio
async def test_erc20_balance_of_returns_raw_int():
    from app.chains.evm import erc20_balance_of
    # 100 USDC in raw units (6 decimals) = 100_000_000 = 0x5F5E100
    respx.post(RPC_URL).mock(return_value=_rpc_ok(
        "0x0000000000000000000000000000000000000000000000000000000005F5E100"
    ))
    async with httpx.AsyncClient() as http:
        bal = await erc20_balance_of(http, chain_id=84532, contract=CONTRACT, address=ADDRESS)
    assert bal == 100_000_000


@respx.mock
@pytest.mark.asyncio
async def test_erc20_balance_of_zero_returns_zero():
    from app.chains.evm import erc20_balance_of
    respx.post(RPC_URL).mock(return_value=_rpc_ok("0x" + "00" * 32))
    async with httpx.AsyncClient() as http:
        bal = await erc20_balance_of(http, chain_id=84532, contract=CONTRACT, address=ADDRESS)
    assert bal == 0


@respx.mock
@pytest.mark.asyncio
async def test_erc20_balance_of_empty_result_returns_zero():
    from app.chains.evm import erc20_balance_of
    respx.post(RPC_URL).mock(return_value=_rpc_ok("0x"))
    async with httpx.AsyncClient() as http:
        bal = await erc20_balance_of(http, chain_id=84532, contract=CONTRACT, address=ADDRESS)
    assert bal == 0


# ── eth_balance_of ───────────────────────────────────────────────────────────

@respx.mock
@pytest.mark.asyncio
async def test_eth_balance_of_returns_wei():
    from app.chains.evm import eth_balance_of
    # 1 ETH = 1e18 wei = 0xDE0B6B3A7640000
    respx.post(RPC_URL).mock(return_value=_rpc_ok("0xDE0B6B3A7640000"))
    async with httpx.AsyncClient() as http:
        bal = await eth_balance_of(http, chain_id=84532, address=ADDRESS)
    assert bal == 10 ** 18


# ── erc20_decimals ───────────────────────────────────────────────────────────

@respx.mock
@pytest.mark.asyncio
async def test_erc20_decimals_returns_int():
    from app.chains.evm import erc20_decimals
    # USDC has 6 decimals = 0x6
    respx.post(RPC_URL).mock(return_value=_rpc_ok(
        "0x0000000000000000000000000000000000000000000000000000000000000006"
    ))
    async with httpx.AsyncClient() as http:
        d = await erc20_decimals(http, chain_id=84532, contract=CONTRACT)
    assert d == 6


@respx.mock
@pytest.mark.asyncio
async def test_erc20_decimals_falls_back_to_18_on_empty():
    from app.chains.evm import erc20_decimals
    respx.post(RPC_URL).mock(return_value=_rpc_ok("0x"))
    async with httpx.AsyncClient() as http:
        d = await erc20_decimals(http, chain_id=84532, contract=CONTRACT)
    assert d == 18


# ── chain_id_for ─────────────────────────────────────────────────────────────

def test_chain_id_for_known_chains():
    from app.chains.evm import chain_id_for
    assert chain_id_for("eth") == 1
    assert chain_id_for("base") == 8453
    assert chain_id_for("base-sepolia") == 84532


def test_chain_id_for_non_evm_returns_none():
    from app.chains.evm import chain_id_for
    assert chain_id_for("solana") is None
    assert chain_id_for("ton") is None
    assert chain_id_for("bnb") is None
```

- [ ] **Step 1.2 — Run, confirm all FAIL**

```bash
.venv/bin/pytest tests/unit/test_evm_balance.py -v
```

Expected: `ImportError` or `AttributeError` — functions don't exist yet.

---

## Task 2: Balance Reader — implementation

**Files:**
- Modify: `app/chains/evm.py` — append after `confirmations_for()`

- [ ] **Step 2.1 — Add `CHAIN_ID_MAP`, `chain_id_for`, and three new async functions**

Append this block at the end of `app/chains/evm.py`:

```python
# ── chain-id lookup ──────────────────────────────────────────────────────────

CHAIN_ID_MAP: dict[str, int] = {
    "eth": 1,
    "base": 8453,
    "base-sepolia": 84532,
    "sepolia": 11155111,
}


def chain_id_for(chain_str: str) -> int | None:
    """Map a Chain enum value (string) to an EVM chain ID.

    Returns None for non-EVM chains (Solana, TON, BNB not yet wired).
    Callers should skip gates with a None chain_id — they belong to a
    future reader implementation.
    """
    return CHAIN_ID_MAP.get(chain_str)


# ── balance reads ────────────────────────────────────────────────────────────

async def erc20_balance_of(
    http: httpx.AsyncClient,
    *,
    chain_id: int,
    contract: str,
    address: str,
) -> int:
    """Return raw ERC-20 token balance in smallest units (no decimal scaling).

    Calls balanceOf(address) — selector 0x70a08231 — via eth_call.
    Returns 0 if the call returns empty (undeployed contract, wrong chain).
    The caller is responsible for comparing against a raw threshold that
    was already scaled by token decimals at gate-creation time.
    """
    spec = get_chain(chain_id)
    padded = address.lower().removeprefix("0x").zfill(64)
    data = f"0x70a08231{padded}"
    result = await _rpc(
        http, spec.rpc_url(), "eth_call", [{"to": contract, "data": data}, "latest"]
    )
    if not result or result == "0x":
        return 0
    return int(result, 16)


async def eth_balance_of(
    http: httpx.AsyncClient,
    *,
    chain_id: int,
    address: str,
) -> int:
    """Return native ETH balance in wei via eth_getBalance."""
    spec = get_chain(chain_id)
    result = await _rpc(http, spec.rpc_url(), "eth_getBalance", [address, "latest"])
    return int(result, 16)


async def erc20_decimals(
    http: httpx.AsyncClient,
    *,
    chain_id: int,
    contract: str,
) -> int:
    """Return token decimal places via decimals() — selector 0x313ce567.

    Falls back to 18 if the call fails or returns empty (safe default for
    most ERC-20 tokens). Used during /setup to convert human amount to raw.
    """
    spec = get_chain(chain_id)
    try:
        result = await _rpc(
            http, spec.rpc_url(), "eth_call",
            [{"to": contract, "data": "0x313ce567"}, "latest"],
        )
        if not result or result == "0x":
            return 18
        return int(result, 16)
    except RpcError:
        return 18
```

- [ ] **Step 2.2 — Run tests, confirm all PASS**

```bash
.venv/bin/pytest tests/unit/test_evm_balance.py -v
```

Expected: 9 passed.

- [ ] **Step 2.3 — Run full suite to confirm nothing broke**

```bash
.venv/bin/pytest -q -m unit
```

Expected: all existing tests + 9 new = green.

- [ ] **Step 2.4 — Commit**

```bash
git add app/chains/evm.py tests/unit/test_evm_balance.py
git commit -m "feat(evm): add erc20_balance_of, eth_balance_of, erc20_decimals, chain_id_for"
```

---

## Task 3: Gate Evaluator — tests first

**Files:**
- Create: `tests/unit/test_gates_token.py`

- [ ] **Step 3.1 — Write failing tests**

```python
# tests/unit/test_gates_token.py
"""Unit tests for token-gate balance checking in evaluate()."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from mongomock_motor import AsyncMongoMockClient

from app.gates import Approve, Decline, NeedsVerify, evaluate

pytestmark = pytest.mark.unit


def _now() -> datetime:
    return datetime.now(tz=UTC)


@pytest.fixture
def db():
    client = AsyncMongoMockClient()
    return client["tg_token_test"]


@pytest.fixture
def http():
    return AsyncMock(spec=httpx.AsyncClient)


async def _seed(db, *, owner_id=999, user_id=1, chat_id=-1001, verified=True, gates=None):
    """Insert a registered chat, optional verification, optional gates."""
    await db.chats.insert_one({"_id": chat_id, "owner_tg_id": owner_id, "title": "Test"})
    if verified:
        await db.verifications.insert_one({
            "tg_user_id": user_id,
            "chat_id": chat_id,
            "address": "0xdeadbeef",
            "chain": "base-sepolia",
            "verified_at": _now(),
        })
    for g in (gates or []):
        await db.gates.insert_one(g)


# ── no gates ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_verified_no_gates_approves(db, http):
    await _seed(db, verified=True, gates=[])
    result = await evaluate(db, http, chat_id=-1001, tg_user_id=1)
    assert isinstance(result, Approve)
    assert result.reason == "wallet_verified"


# ── single ERC-20 gate ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gate_passes_when_balance_sufficient(db, http):
    await _seed(db, gates=[{
        "_id": "g1", "chat_id": -1001, "kind": "token",
        "chain": "base", "contract": "0xusdc", "threshold": "1000000",
    }])
    with patch("app.gates.erc20_balance_of", new=AsyncMock(return_value=5_000_000)):
        result = await evaluate(db, http, chat_id=-1001, tg_user_id=1)
    assert isinstance(result, Approve)
    assert result.reason == "token_gate_passed"


@pytest.mark.asyncio
async def test_gate_declines_when_balance_insufficient(db, http):
    await _seed(db, gates=[{
        "_id": "g1", "chat_id": -1001, "kind": "token",
        "chain": "base", "contract": "0xusdc", "threshold": "1000000",
    }])
    with patch("app.gates.erc20_balance_of", new=AsyncMock(return_value=500_000)):
        result = await evaluate(db, http, chat_id=-1001, tg_user_id=1)
    assert isinstance(result, Decline)
    assert result.reason == "insufficient_balance"


@pytest.mark.asyncio
async def test_gate_exact_threshold_approves(db, http):
    await _seed(db, gates=[{
        "_id": "g1", "chat_id": -1001, "kind": "token",
        "chain": "base", "contract": "0xusdc", "threshold": "1000000",
    }])
    with patch("app.gates.erc20_balance_of", new=AsyncMock(return_value=1_000_000)):
        result = await evaluate(db, http, chat_id=-1001, tg_user_id=1)
    assert isinstance(result, Approve)


# ── native ETH gate (no contract) ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_native_eth_gate_passes(db, http):
    await _seed(db, gates=[{
        "_id": "g1", "chat_id": -1001, "kind": "token",
        "chain": "eth", "contract": None, "threshold": str(10 ** 17),  # 0.1 ETH
    }])
    with patch("app.gates.eth_balance_of", new=AsyncMock(return_value=10 ** 18)):
        result = await evaluate(db, http, chat_id=-1001, tg_user_id=1)
    assert isinstance(result, Approve)


@pytest.mark.asyncio
async def test_native_eth_gate_declines(db, http):
    await _seed(db, gates=[{
        "_id": "g1", "chat_id": -1001, "kind": "token",
        "chain": "eth", "contract": None, "threshold": str(10 ** 18),  # 1 ETH
    }])
    with patch("app.gates.eth_balance_of", new=AsyncMock(return_value=10 ** 17)):
        result = await evaluate(db, http, chat_id=-1001, tg_user_id=1)
    assert isinstance(result, Decline)


# ── multiple gates (AND logic) ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_multiple_gates_all_pass(db, http):
    await _seed(db, gates=[
        {"_id": "g1", "chat_id": -1001, "kind": "token", "chain": "base",
         "contract": "0xusdc", "threshold": "1000000"},
        {"_id": "g2", "chat_id": -1001, "kind": "token", "chain": "eth",
         "contract": None, "threshold": str(10 ** 17)},
    ])
    with patch("app.gates.erc20_balance_of", new=AsyncMock(return_value=5_000_000)), \
         patch("app.gates.eth_balance_of",   new=AsyncMock(return_value=10 ** 18)):
        result = await evaluate(db, http, chat_id=-1001, tg_user_id=1)
    assert isinstance(result, Approve)


@pytest.mark.asyncio
async def test_multiple_gates_one_fails_declines(db, http):
    await _seed(db, gates=[
        {"_id": "g1", "chat_id": -1001, "kind": "token", "chain": "base",
         "contract": "0xusdc", "threshold": "1000000"},
        {"_id": "g2", "chat_id": -1001, "kind": "token", "chain": "eth",
         "contract": None, "threshold": str(10 ** 18)},
    ])
    with patch("app.gates.erc20_balance_of", new=AsyncMock(return_value=5_000_000)), \
         patch("app.gates.eth_balance_of",   new=AsyncMock(return_value=10 ** 14)):  # too low
        result = await evaluate(db, http, chat_id=-1001, tg_user_id=1)
    assert isinstance(result, Decline)


# ── non-EVM gate is skipped ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_solana_gate_skipped_approves(db, http):
    """Solana gates have no chain_id mapping yet — skip and approve."""
    await _seed(db, gates=[{
        "_id": "g1", "chat_id": -1001, "kind": "token",
        "chain": "solana", "contract": "So111...", "threshold": "1000000",
    }])
    result = await evaluate(db, http, chat_id=-1001, tg_user_id=1)
    assert isinstance(result, Approve)


# ── unverified user still hits NeedsVerify ───────────────────────────────────

@pytest.mark.asyncio
async def test_no_verification_needs_verify(db, http):
    await _seed(db, verified=False, gates=[{
        "_id": "g1", "chat_id": -1001, "kind": "token",
        "chain": "base", "contract": "0xusdc", "threshold": "1000000",
    }])
    result = await evaluate(db, http, chat_id=-1001, tg_user_id=1)
    assert isinstance(result, NeedsVerify)
```

- [ ] **Step 3.2 — Run, confirm all FAIL**

```bash
.venv/bin/pytest tests/unit/test_gates_token.py -v
```

Expected: `TypeError` — `evaluate()` doesn't accept `http` yet.

---

## Task 4: Gate Evaluator — implementation

**Files:**
- Modify: `app/gates.py`

- [ ] **Step 4.1 — Replace the full `gates.py` content**

```python
"""Gate evaluator.

Three outcomes per join request:

- **Approve** — user passes all checks (owner / whitelist / verification + token gates).
- **Decline** — permanently rejected (chat not registered, insufficient token balance).
- **NeedsVerify** — user must prove wallet ownership first. Bot DMs /verify instructions.

evaluate() is the single entry point. All gate logic lives here.
Token balance reads go through app.chains.evm — no direct RPC calls in this file.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.chains.evm import chain_id_for, erc20_balance_of, eth_balance_of
from app.logging_conf import get_logger
from app.settings import settings

log = get_logger(__name__)


@dataclass(frozen=True)
class Approve:
    reason: str


@dataclass(frozen=True)
class Decline:
    reason: str


@dataclass(frozen=True)
class NeedsVerify:
    reason: str


Decision = Approve | Decline | NeedsVerify


async def _check_gates(
    db: AsyncIOMotorDatabase[Any],
    http: httpx.AsyncClient,
    *,
    chat_id: int,
    address: str,
) -> Decision | None:
    """Load gates for chat and check balances. Returns Approve/Decline or None if no gates."""
    gates = await cast(Any, db.gates).find({"chat_id": chat_id}).to_list(None)
    if not gates:
        return Approve(reason="wallet_verified")

    for gate in gates:
        gate_chain: str = gate.get("chain") or "base"
        cid = chain_id_for(gate_chain)
        if cid is None:
            # Non-EVM chain (Solana, TON) — reader not built yet, skip this gate
            log.info("gate_chain_skipped", chain=gate_chain, gate_id=gate.get("_id"))
            continue

        contract: str | None = gate.get("contract")
        threshold = int(gate["threshold"])

        if contract:
            balance = await erc20_balance_of(http, chain_id=cid, contract=contract, address=address)
        else:
            balance = await eth_balance_of(http, chain_id=cid, address=address)

        if balance < threshold:
            log.info(
                "gate_failed",
                chat_id=chat_id,
                gate_id=gate.get("_id"),
                balance=balance,
                threshold=threshold,
            )
            return Decline(reason="insufficient_balance")

    return Approve(reason="token_gate_passed")


async def evaluate(
    db: AsyncIOMotorDatabase[Any],
    http: httpx.AsyncClient,
    *,
    chat_id: int,
    tg_user_id: int,
) -> Decision:
    chat = await cast(Any, db.chats).find_one({"_id": chat_id})
    if chat is None:
        return Decline(reason="chat_not_registered")

    if chat.get("owner_tg_id") == tg_user_id:
        return Approve(reason="chat_owner")

    wl = await cast(Any, db.whitelist).find_one({"chat_id": chat_id, "tg_user_id": tg_user_id})
    if wl is not None:
        return Approve(reason="whitelist")

    fresh_cutoff = datetime.now(tz=UTC) - timedelta(seconds=settings.verification_ttl_seconds)
    verif = await cast(Any, db.verifications).find_one(
        {
            "tg_user_id": tg_user_id,
            "chat_id": chat_id,
            "verified_at": {"$gte": fresh_cutoff},
        }
    )
    if verif is None:
        return NeedsVerify(reason="requires_verification")

    return await _check_gates(db, http, chat_id=chat_id, address=verif["address"])
```

- [ ] **Step 4.2 — Run gate token tests, confirm PASS**

```bash
.venv/bin/pytest tests/unit/test_gates_token.py -v
```

Expected: 10 passed.

- [ ] **Step 4.3 — Run full suite, check nothing broke**

```bash
.venv/bin/pytest -q -m unit
```

The existing `test_gates.py` tests call `evaluate(db, chat_id=..., tg_user_id=...)` without `http`. They will now FAIL because `evaluate()` requires `http` as the second positional argument.

Fix: update all calls in `tests/unit/test_gates.py` to pass a mock http client.

Open `tests/unit/test_gates.py`. At the top add:

```python
from unittest.mock import AsyncMock
import httpx

@pytest.fixture
def http():
    return AsyncMock(spec=httpx.AsyncClient)
```

Then update every `await evaluate(db, chat_id=..., tg_user_id=...)` call to `await evaluate(db, http, chat_id=..., tg_user_id=...)`.

Re-run:
```bash
.venv/bin/pytest -q -m unit
```

Expected: all tests green.

- [ ] **Step 4.4 — Commit**

```bash
git add app/gates.py tests/unit/test_gates_token.py tests/unit/test_gates.py
git commit -m "feat(gates): check token balances after wallet verification"
```

---

## Task 5: /setup Wizard — tests first

**Files:**
- Create: `tests/unit/test_setup_wizard.py`

- [ ] **Step 5.1 — Write failing tests for wizard helpers**

```python
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
    assert human_to_raw("1", decimals=18) == 10 ** 18


def test_human_to_raw_fractional():
    from app.setup_wizard import human_to_raw
    assert human_to_raw("0.5", decimals=18) == 5 * 10 ** 17


def test_human_to_raw_large_number_no_float_error():
    from app.setup_wizard import human_to_raw
    # 1 billion tokens with 18 decimals — would overflow float
    result = human_to_raw("1000000000", decimals=18)
    assert result == 10 ** 27


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
        await db.gates.insert_one({"_id": f"g{i}", "chat_id": -1001, "kind": "token",
                                    "chain": "base", "contract": "0x1", "threshold": "1"})
    assert await count_gates(db, chat_id=-1001) == 3


@pytest.mark.asyncio
async def test_count_gates_is_chat_scoped(db):
    from app.setup_wizard import count_gates
    await db.gates.insert_one({"_id": "g1", "chat_id": -1001, "kind": "token",
                                "chain": "base", "contract": "0x1", "threshold": "1"})
    await db.gates.insert_one({"_id": "g2", "chat_id": -9999, "kind": "token",
                                "chain": "base", "contract": "0x1", "threshold": "1"})
    assert await count_gates(db, chat_id=-1001) == 1
```

- [ ] **Step 5.2 — Run, confirm all FAIL**

```bash
.venv/bin/pytest tests/unit/test_setup_wizard.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.setup_wizard'`

---

## Task 6: /setup Wizard — implementation

**Files:**
- Create: `app/setup_wizard.py`

- [ ] **Step 6.1 — Create `app/setup_wizard.py`**

```python
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
        raise ValueError(f"not a number: {amount_str!r}")
    if d <= 0:
        raise ValueError(f"must be positive, got {d}")
    return int(d * Decimal(10 ** decimals))


async def save_gate(
    db: AsyncIOMotorDatabase[Any],
    *,
    chat_id: int,
    chain: str,
    contract: str | None,
    raw_threshold: str,
) -> None:
    """Insert a gate document into the gates collection."""
    await db.gates.insert_one({
        "_id": str(uuid.uuid4()),
        "chat_id": chat_id,
        "kind": "token",
        "chain": chain,
        "contract": contract,
        "threshold": raw_threshold,
        "created_at": datetime.now(tz=UTC),
    })


async def count_gates(db: AsyncIOMotorDatabase[Any], *, chat_id: int) -> int:
    """Return the number of gates configured for a chat."""
    return await db.gates.count_documents({"chat_id": chat_id})


# ── FSM states ───────────────────────────────────────────────────────────────

class SetupGate(StatesGroup):
    select_chat      = State()
    select_chain     = State()
    input_contract   = State()
    input_threshold  = State()
    confirm          = State()


# ── keyboards ────────────────────────────────────────────────────────────────

def _chain_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Ethereum",         callback_data="chain:eth:token"),
            InlineKeyboardButton(text="Base",             callback_data="chain:base:token"),
        ],
        [
            InlineKeyboardButton(text="Native ETH",       callback_data="chain:eth:native"),
            InlineKeyboardButton(text="Native ETH (Base)",callback_data="chain:base:native"),
        ],
    ])


def _confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✓ Save",   callback_data="confirm:yes"),
        InlineKeyboardButton(text="✗ Cancel", callback_data="confirm:no"),
    ]])


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
            "No registered groups found.\n"
            "Add me to a group as admin first, then come back here."
        )
        return

    buttons = [
        [InlineKeyboardButton(
            text=c.get("title") or str(c["_id"]),
            callback_data=f"chat:{c['_id']}",
        )]
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
            f"This group already has {MAX_GATES} gates (maximum). "
            "Remove one before adding another."
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
    native = (mode == "native")
    await state.update_data(chain=chain, native=native)

    if native:
        await query.message.edit_text(  # type: ignore[union-attr]
            "Minimum balance? Enter a number.\n"
            "Example: 0.1 means 0.1 ETH"
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
```

- [ ] **Step 6.2 — Run wizard tests, confirm PASS**

```bash
.venv/bin/pytest tests/unit/test_setup_wizard.py -v
```

Expected: 14 passed.

- [ ] **Step 6.3 — Run full suite**

```bash
.venv/bin/pytest -q -m unit
```

Expected: all green.

- [ ] **Step 6.4 — Commit**

```bash
git add app/setup_wizard.py tests/unit/test_setup_wizard.py
git commit -m "feat(wizard): /setup FSM — owner configures token gate in Telegram DMs"
```

---

## Task 7: Bot Wiring

**Files:**
- Modify: `app/bot.py`
- Modify: `app/__main__.py`

- [ ] **Step 7.1 — Add `my_chat_member` handler to `app/bot.py`**

Add this import at the top of `app/bot.py` (after existing imports):

```python
from datetime import UTC, datetime

from aiogram.types import ChatMemberUpdated
```

Add this handler inside `app/bot.py` (after existing handlers):

```python
@router.my_chat_member()
async def on_my_chat_member(
    update: ChatMemberUpdated,
    db: AsyncIOMotorDatabase[Any],
) -> None:
    """Auto-register a chat when the bot is promoted to admin.

    This is the only way a chat enters the chats collection without manual
    DB intervention. The user who promotes the bot becomes the owner.
    """
    new_status = update.new_chat_member.status
    if new_status not in ("administrator", "creator"):
        return  # bot demoted or kicked — don't touch the record

    chat_id = update.chat.id
    chat_title = update.chat.title or str(chat_id)
    owner_tg_id = update.from_user.id  # type: ignore[union-attr]

    await cast(Any, db.chats).update_one(
        {"_id": chat_id},
        {"$setOnInsert": {
            "_id": chat_id,
            "title": chat_title,
            "owner_tg_id": owner_tg_id,
            "created_at": datetime.now(tz=UTC),
        }},
        upsert=True,
    )
    log.info("chat_registered", chat_id=chat_id, owner=owner_tg_id)
```

- [ ] **Step 7.2 — Wire `setup_router` and `http` into `app/__main__.py`**

Open `app/__main__.py`. Find where `dp` (the Dispatcher) is created and routers are included.

Add the setup router:
```python
from app.setup_wizard import router as setup_router
dp.include_router(setup_router)
```

Create a shared httpx client and pass it to the dispatcher's workflow data so all handlers receive it via dependency injection:

```python
import httpx

# Inside the main() / run() function, after dp is created:
http_client = httpx.AsyncClient()
dp["http"] = http_client

# Ensure it's closed on shutdown:
try:
    await dp.start_polling(bot)
finally:
    await http_client.aclose()
```

- [ ] **Step 7.3 — Update the join_request handler call in `app/bot.py`**

Find the `evaluate()` call in the join_request handler. It currently reads:
```python
decision = await evaluate(db, chat_id=..., tg_user_id=...)
```

Change it to:
```python
decision = await evaluate(db, http, chat_id=..., tg_user_id=...)
```

Where `http` comes from the handler's dependency injection (add `http: httpx.AsyncClient` to the handler's signature, same as `db`).

- [ ] **Step 7.4 — Run full unit suite**

```bash
.venv/bin/pytest -q -m unit
```

Expected: all green (the wiring changes are in `__main__.py` which isn't unit-tested directly — integration tests cover the live path).

- [ ] **Step 7.5 — Smoke test: start the bot locally**

```bash
make infra-up   # starts local Mongo + Redis
make dev        # launches the bot
```

Expected output: bot starts, no import errors, Polling started logged.

- [ ] **Step 7.6 — Commit**

```bash
git add app/bot.py app/__main__.py
git commit -m "feat(bot): wire /setup router, http client, auto-register on admin-add"
```

---

## Task 8: Final gate — full test run + push

- [ ] **Step 8.1 — Full unit suite**

```bash
.venv/bin/pytest -q -m unit
```

Expected: all tests green. Count should be 58 (existing) + 9 (evm_balance) + 10 (gates_token) + 14 (setup_wizard) = 91 tests.

- [ ] **Step 8.2 — Lint and type check**

```bash
make lint
make type
```

Expected: no errors.

- [ ] **Step 8.3 — Push (triggers pre-push hook)**

```bash
git push
```

Pre-push runs ruff + pyright + pytest -m unit automatically. Must be green before push succeeds.

---

## Self-Review

**Spec coverage:**
- ✅ `erc20_balance_of`, `eth_balance_of`, `erc20_decimals` — Task 1–2
- ✅ `chain_id_for` + `CHAIN_ID_MAP` — Task 2
- ✅ Decimal handling (raw units, no floats, Decimal arithmetic) — Task 6 `human_to_raw`
- ✅ Gate evaluator: no gates → approve, gate pass → approve, gate fail → decline — Task 3–4
- ✅ AND logic for multiple gates — Task 3 tests
- ✅ Non-EVM gate skipped — Task 3 test + Task 4 implementation
- ✅ `/setup` FSM all 5 states — Task 6
- ✅ Auto-register chat on bot admin-add — Task 7
- ✅ `http` client passed via dispatcher data — Task 7
- ✅ MAX_GATES=5 enforced — Task 6 `cb_select_chat`
- ✅ Backward compatibility (existing 58 tests fixed in Task 4 Step 4.3)

**Type consistency check:**
- `erc20_balance_of` → called as `erc20_balance_of(http, chain_id=cid, contract=contract, address=address)` in gates.py — matches Task 2 signature ✅
- `eth_balance_of` → called as `eth_balance_of(http, chain_id=cid, address=address)` — matches ✅
- `evaluate(db, http, *, chat_id, tg_user_id)` → called in bot.py as `evaluate(db, http, chat_id=..., tg_user_id=...)` — matches ✅
- `human_to_raw(text, decimals=decimals)` → called in `msg_input_threshold` — matches ✅
- `save_gate(db, chat_id=..., chain=..., contract=..., raw_threshold=...)` → called in `cb_confirm` — matches ✅
- `count_gates(db, chat_id=chat_id)` → called in `cb_select_chat` — matches ✅
