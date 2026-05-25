# Token Gate Balance Check — Design Spec
**Date:** 2026-05-26  
**Scope:** EVM (ETH mainnet + Base mainnet) token balance gating. Solana is out of scope for this build — same architecture, second pass.

---

## Problem

Wallet ownership is already proven via dust self-transfer. The system does not yet check *what is in* the verified wallet. Any user who completes dust verification gets approved, regardless of token holdings. Token gates exist in the schema but are never evaluated.

---

## What We're Building

Four pieces, in dependency order:

1. **ERC-20 + native balance reader** — new functions in `app/chains/evm.py`
2. **Gate evaluator update** — `app/gates.py` checks balances after verification
3. **/setup wizard** — aiogram FSM in `app/setup_wizard.py` for owners to configure gates
4. **Bot wiring** — register /setup router in `app/bot.py`

---

## 1. Balance Reader (`app/chains/evm.py`)

Two new async functions added to the existing module:

### `erc20_balance_of(http, chain_id, contract, address) → int`
- Calls `eth_call` with `balanceOf(address)` ABI-encoded selector (`0x70a08231` + zero-padded address)
- Returns raw integer (wei-scale units — no decimal adjustment here; that's the caller's job)
- Uses existing `_rpc()` helper and Alchemy URL resolution
- Raises `RpcError` on bad contract address or network error

### `eth_balance_of(http, chain_id, address) → int`
- Calls `eth_getBalance(address, "latest")`
- Returns wei as int
- Used when gate has no `contract` (native ETH gate)

### Decimal handling
Raw balances are in token-smallest-units (18 decimals for most ERC-20s, 6 for USDC). The gate threshold stored in MongoDB is also in **raw units** (owner enters human amount during /setup, we multiply by decimals at save time). Comparison is always `raw_balance >= raw_threshold` — no floats anywhere.

To get decimals during /setup: call `eth_call` with `decimals()` selector (`0x313ce567`).

---

## 2. Gate Evaluator Update (`app/gates.py`)

Current tail of `evaluate()`:
```
has verification within TTL → Approve
else                         → NeedsVerify
```

New tail:
```
has verification within TTL:
    gates = load all gates for this chat
    if no gates configured → Approve (open gate, wallet-verified only)
    for each gate:
        check balance via evm reader
        if balance < threshold → Decline(reason="insufficient_balance")
    all gates passed → Approve(reason="token_gate_passed")
else → NeedsVerify
```

**Key decisions:**
- If a chat has no gates configured: verification alone is sufficient to approve. Owner must explicitly add a gate to enforce token holding.
- Multiple gates = user must pass ALL of them (AND logic, not OR).
- Gate check uses a shared `httpx.AsyncClient` passed in from the caller (same pattern as dust watcher). Not created per-call.
- `Decline` on balance failure is silent — no DM to the user (option C deferred).

**Shared HTTP client:** `evaluate()` gains an `http: httpx.AsyncClient` parameter. Callers (bot join handler) already have an http client available.

---

## 3. /setup Wizard (`app/setup_wizard.py`)

aiogram FSM conversation. States:

```
SELECT_CHAT → SELECT_CHAIN → INPUT_CONTRACT → INPUT_THRESHOLD → CONFIRM
```

### State: SELECT_CHAT
- Triggered by `/setup` in DMs only (private chat filter)
- Bot queries Telegram for groups where the user is admin (`getChatAdministrators`)
- Presents as inline keyboard buttons (group name → chat_id)
- If user is not admin in any group: reply "Add me to a group first and make me admin."

### State: SELECT_CHAIN
- Inline keyboard: `[Ethereum]` `[Base]` `[Native ETH]`
- Stores chain in FSM state

### State: INPUT_CONTRACT
- Skipped if "Native ETH" selected (no contract for native balance)
- Bot asks: "Paste the token contract address (0x...)"
- Validates: 42 chars, starts with 0x, hex only
- Fetches token decimals from chain → stores in FSM state
- On bad address: "That doesn't look like a valid contract. Try again."

### State: INPUT_THRESHOLD
- Bot asks: "Minimum balance? Enter a number (e.g. 100 for 100 tokens)"
- Validates: positive number, up to 18 decimal places
- Multiplies by 10^decimals → stored as raw string in FSM state
- On bad input: re-prompts

### State: CONFIRM
- Shows summary: chain, contract (or "native ETH"), human threshold
- Inline buttons: `[✓ Save]` `[✗ Cancel]`
- On save: upserts Gate document to MongoDB, clears FSM state, replies "✓ Gate set."
- On cancel: clears FSM state, replies "Cancelled."

### Constraints
- `/setup` only works in private DMs (not in groups)
- One active FSM state per user — starting `/setup` again while mid-flow resets to beginning
- Max 5 gates per chat (matches competitor limit) — bot blocks adding a 6th

---

## 4. Bot Wiring (`app/bot.py`)

- Import and include the `setup_router` from `app/setup_wizard.py`
- Pass `http` client into `evaluate()` call in the join handler
- The `http` client is already created at bot startup — reuse it

---

## Data Flow (Happy Path After This Build)

```
User requests join
  → evaluate() checks: owner? whitelist? verification?
  → verification exists within TTL
  → load gates from MongoDB for this chat
  → for each gate: call erc20_balance_of / eth_balance_of via Alchemy
  → all balances ≥ thresholds → Approve
  → Telegram: approve_chat_join_request
```

---

## Testing

### Unit tests (new)
- `test_evm_balance.py` — mock `_rpc`, test `erc20_balance_of` and `eth_balance_of` for happy path, bad contract, zero balance
- `test_gates_token.py` — mock balance reader, test: no gates → approve, one gate pass, one gate fail → decline, multiple gates all pass, multiple gates one fail
- `test_setup_wizard.py` — FSM state transitions, validation rejection, threshold decimal conversion, max-gate limit

### Existing tests
All 58 existing unit tests must remain green. `evaluate()` change is backward-compatible: chats with no gates still approve on verification.

---

## Out of Scope

- Solana / SPL token balances (same architecture, second pass — Helius reader)
- DM user on decline with reason (deferred — option C)
- Net-worth gates (multi-token USD sum)
- Payment gates
- Re-check command (user buys tokens, triggers re-evaluation without re-verifying wallet)

---

## File Changeset

| File | Change |
|---|---|
| `app/chains/evm.py` | Add `erc20_balance_of()`, `eth_balance_of()` |
| `app/gates.py` | Add gate balance check after verification step; add `http` param |
| `app/setup_wizard.py` | New — FSM wizard, all 5 states |
| `app/bot.py` | Include setup_router; pass http to evaluate() |
| `tests/unit/test_evm_balance.py` | New unit tests |
| `tests/unit/test_gates_token.py` | New unit tests |
| `tests/unit/test_setup_wizard.py` | New unit tests |
