"""Chain type detection from wallet address format.

Three disjoint address spaces:
- EVM:    0x + 40 hex chars  (42 total)
- TON:    48 base64url chars (EQ.../UQ... user-friendly mainnet format)
- Solana: 32-44 base58 chars (no 0/O/I/l, no 0x prefix, not 48 chars)

Returns "evm" | "ton" | "solana" | None.
"""

from __future__ import annotations

import re

# EVM: 0x + exactly 40 hex characters
_EVM_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")

# TON user-friendly address: exactly 48 base64url characters.
# Includes A-Z, a-z, 0-9, underscore, hyphen.
# Real mainnet addresses start with EQ or UQ but we accept any 48-char
# base64url string to be forward-compatible with other workchains.
_TON_RE = re.compile(r"^[A-Za-z0-9_-]{48}$")

# Solana base58: 32-44 chars, alphabet excludes 0, O, I, l.
# Must not match 48-char strings (those are TON), must not start with 0x.
_SOLANA_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


def detect_chain_type(address: str) -> str | None:
    """Return 'evm', 'ton', 'solana', or None if unrecognised."""
    if _EVM_RE.match(address):
        return "evm"
    if _TON_RE.match(address):
        return "ton"
    if _SOLANA_RE.match(address):
        return "solana"
    return None
