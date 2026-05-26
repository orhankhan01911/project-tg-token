"""OR-logic token balance gate evaluator.

Given a TokenGate (basket of tokens, min_usd_value) and a dict of the user's
verified wallet addresses keyed by VM family, check whether the user holds
>= min_usd_value of ANY token in the basket.

Decision logic:
- For each TokenSpec:
    1. Fetch raw balance + decimals for that chain/contract.
    2. Fetch USD price from DexScreener.
    3. Compute usd_value = (raw_balance / 10**decimals) * price.
    4. If usd_value >= min_usd_value → return True immediately (OR logic).
- If all tokens fail (zero balance or price unavailable) → return False.

Addresses dict format:
    {
        "evm": "0x...",     # for eth / base / base-sepolia chains
        "ton": "EQ...",     # for ton chain
        "solana": "...",    # for solana chain
    }

Missing addresses for a chain family → that token is skipped (can't check).
Price unavailable → that token is treated as a fail, but we continue checking
the rest (do NOT raise, do NOT short-circuit).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx

from app.chains.evm import erc20_balance_of, erc20_decimals
from app.chains.solana import spl_balance
from app.chains.ton import jetton_balance
from app.logging_conf import get_logger
from app.models.gate import Chain
from app.models.token_gate import TokenGate, TokenSpec
from app.pricing import get_token_price_usd

log = get_logger(__name__)

# Map Chain enum → DexScreener chainId slug for pricing
_DEXSCREENER_SLUG: dict[Chain, str] = {
    Chain.ETH: "eth",
    Chain.BASE: "base",
    Chain.BASE_SEPOLIA: "base",
    Chain.TON: "ton",
    Chain.SOLANA: "solana",
}

# Map Chain enum → address family key in `addresses` dict
_ADDRESS_FAMILY: dict[Chain, str] = {
    Chain.ETH: "evm",
    Chain.BASE: "evm",
    Chain.BASE_SEPOLIA: "evm",
    Chain.TON: "ton",
    Chain.SOLANA: "solana",
}

# Map Chain enum → numeric chain_id (EVM only)
_EVM_CHAIN_ID: dict[Chain, int] = {
    Chain.ETH: 1,
    Chain.BASE: 8453,
    Chain.BASE_SEPOLIA: 84532,
}


async def _token_usd_value(
    http: httpx.AsyncClient,
    *,
    spec: TokenSpec,
    addresses: dict[str, str],
) -> Decimal:
    """Return the USD value of the user's holding of one token.

    Returns Decimal("0") if the address is missing, balance is zero,
    price lookup fails, or any other non-fatal error.
    """
    family = _ADDRESS_FAMILY.get(spec.chain)
    address = addresses.get(family) if family else None
    if not address:
        log.debug("token_gate_skip_no_address", token=spec.name, chain=spec.chain.value)
        return Decimal("0")

    # --- fetch balance ---
    raw_balance = 0
    decimals = 18  # safe default
    try:
        if spec.chain in _EVM_CHAIN_ID:
            chain_id = _EVM_CHAIN_ID[spec.chain]
            raw_balance = await erc20_balance_of(
                http, chain_id=chain_id, contract=spec.contract, address=address
            )
            decimals = await erc20_decimals(http, chain_id=chain_id, contract=spec.contract)
        elif spec.chain == Chain.TON:
            raw_balance, decimals = await jetton_balance(
                http, owner_address=address, jetton_master=spec.contract
            )
        elif spec.chain == Chain.SOLANA:
            raw_balance, decimals = await spl_balance(
                http, owner_address=address, mint=spec.contract
            )
        else:
            log.warning("token_gate_unsupported_chain", chain=spec.chain.value)
            return Decimal("0")
    except Exception as exc:
        log.warning("token_gate_balance_error", token=spec.name, err=repr(exc))
        return Decimal("0")

    if raw_balance == 0:
        return Decimal("0")

    # --- fetch price ---
    chain_slug = _DEXSCREENER_SLUG.get(spec.chain, spec.chain.value)
    price = await get_token_price_usd(http, chain_slug=chain_slug, contract_or_mint=spec.contract)
    if price is None:
        log.info("token_gate_no_price", token=spec.name, chain=spec.chain.value)
        return Decimal("0")

    amount = Decimal(raw_balance) / Decimal(10**decimals)
    usd_value = amount * price
    log.info(
        "token_gate_value",
        token=spec.name,
        chain=spec.chain.value,
        raw=raw_balance,
        decimals=decimals,
        price=str(price),
        usd_value=str(usd_value),
    )
    return usd_value


async def evaluate_token_gate(
    http: httpx.AsyncClient,
    *,
    gate: TokenGate,
    addresses: dict[str, str],
) -> bool:
    """Return True if the user holds >= gate.min_usd_value of ANY token in the basket."""
    min_usd = Decimal(gate.min_usd_value)
    for spec in gate.tokens:
        usd = await _token_usd_value(http, spec=spec, addresses=addresses)
        if usd >= min_usd:
            log.info("token_gate_passed", token=spec.name, usd=str(usd), min=gate.min_usd_value)
            return True
    log.info("token_gate_failed", min=gate.min_usd_value, tokens=[s.name for s in gate.tokens])
    return False


async def load_token_gate(db: Any, *, chat_id: int) -> TokenGate | None:
    """Load the token gate for a chat, or None if not configured."""
    from typing import cast

    raw = await cast(Any, db.token_gates).find_one({"chat_id": chat_id})
    if raw is None:
        return None
    return TokenGate.model_validate(raw)


# Human-readable wallet hint per chain value
_CHAIN_WALLET: dict[str, str] = {
    "eth": "Ethereum wallet (MetaMask / OKX)",
    "base": "Base wallet (MetaMask / OKX)",
    "base-sepolia": "Base wallet (MetaMask / OKX)",
    "ton": "TON wallet (Tonkeeper / OKX)",
    "solana": "Solana wallet (Phantom / OKX)",
}


def format_gate_decline(gate: TokenGate, *, verified_address: str | None = None) -> str:
    """Build a clear token gate decline message listing each required token and its network.

    Shown to users after /verify succeeds but the balance check fails, so they
    know exactly which wallet type and token they need.
    """
    if verified_address:
        short = (
            verified_address[:8] + "..." + verified_address[-4:]
            if len(verified_address) > 14
            else verified_address
        )
        intro = f"<code>{short}</code> doesn't hold $10+ of any required token."
    else:
        intro = "Your wallet doesn't hold $10+ of any required token."

    token_lines = []
    for spec in gate.tokens:
        chain_val = spec.chain.value
        wallet_hint = _CHAIN_WALLET.get(chain_val, chain_val)
        token_lines.append(f"• <b>{spec.name}</b> — {wallet_hint}")

    token_list = "\n".join(token_lines)
    return (
        "✅ Wallet verified, but...\n\n"
        f"{intro}\n\n"
        f"Required tokens (hold <b>any one ≥ $10</b>):\n"
        f"{token_list}\n\n"
        "Verify a wallet that holds one of these, then click the invite link again."
    )
