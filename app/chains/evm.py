"""Minimal EVM JSON-RPC reader for the dust verifier.

We need exactly two read patterns:

1. **Latest block height** — for confirmation counting.
2. **Recent native-value transfers to/from a known address** — to
   detect a self-transfer with the expected `value` (wei).

We don't have a generic "give me address activity" primitive on stock
JSON-RPC: `eth_getLogs` only returns ERC-20 / contract events, not native
transfers. So the watcher walks the last N blocks (parameterized) and
filters by `from == to == address && value == expected_amount`. N is
small (5-15) because each verification window is short and we re-scan
every poll cycle — missed polls self-heal.

Per-chain RPC URLs:
- Alchemy if `ALCHEMY_API_KEY` set (paid tier scales)
- Else free public RPC for the chain (rate-limited, fine for v0)

Tenacity retry on transient errors. JSON-RPC error responses (logic
errors) raise immediately — those are bugs, not blips.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.logging_conf import get_logger
from app.settings import settings

log = get_logger(__name__)


@dataclass(frozen=True)
class ChainSpec:
    chain_id: int
    name: str
    explorer: str  # for nice DM links to the user's tx
    block_time_seconds: int
    public_rpc: str

    def alchemy_url(self, key: str) -> str | None:
        return None  # subclasses override

    def rpc_url(self) -> str:
        if settings.alchemy_api_key:
            url = self.alchemy_url(settings.alchemy_api_key)
            if url:
                return url
        return self.public_rpc


class _BaseSepolia(ChainSpec):
    def alchemy_url(self, key: str) -> str | None:
        return f"https://base-sepolia.g.alchemy.com/v2/{key}"


class _Base(ChainSpec):
    def alchemy_url(self, key: str) -> str | None:
        return f"https://base-mainnet.g.alchemy.com/v2/{key}"


class _EthMainnet(ChainSpec):
    def alchemy_url(self, key: str) -> str | None:
        return f"https://eth-mainnet.g.alchemy.com/v2/{key}"


class _Sepolia(ChainSpec):
    def alchemy_url(self, key: str) -> str | None:
        return f"https://eth-sepolia.g.alchemy.com/v2/{key}"


CHAINS: dict[int, ChainSpec] = {
    84532: _BaseSepolia(
        chain_id=84532,
        name="Base Sepolia",
        explorer="https://sepolia.basescan.org",
        block_time_seconds=2,
        public_rpc="https://sepolia.base.org",
    ),
    8453: _Base(
        chain_id=8453,
        name="Base",
        explorer="https://basescan.org",
        block_time_seconds=2,
        public_rpc="https://mainnet.base.org",
    ),
    1: _EthMainnet(
        chain_id=1,
        name="Ethereum",
        explorer="https://etherscan.io",
        block_time_seconds=12,
        public_rpc="https://eth.llamarpc.com",
    ),
    11155111: _Sepolia(
        chain_id=11155111,
        name="Sepolia",
        explorer="https://sepolia.etherscan.io",
        block_time_seconds=12,
        public_rpc="https://ethereum-sepolia.publicnode.com",
    ),
}


def get_chain(chain_id: int) -> ChainSpec:
    spec = CHAINS.get(chain_id)
    if spec is None:
        raise ValueError(f"unsupported_chain:{chain_id}")
    return spec


@dataclass(frozen=True)
class TxRecord:
    hash: str
    block_number: int
    from_address: str  # 0x... lowercased
    to_address: str | None  # None for contract-creation; we ignore those
    value_wei: int


class RpcError(Exception):
    """Logic-level JSON-RPC error (bad params, missing method). Don't retry."""


def _retry() -> AsyncRetrying:
    return AsyncRetrying(
        retry=retry_if_exception_type(
            (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError)
        ),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.4, min=0.4, max=2.0),
        reraise=True,
    )


async def _rpc(http: httpx.AsyncClient, url: str, method: str, params: list[Any]) -> Any:
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    async for attempt in _retry():
        with attempt:
            resp = await http.post(url, json=body, timeout=8.0)
            resp.raise_for_status()
            data = resp.json()
    if "error" in data:
        raise RpcError(f"{method}: {data['error']}")
    return data.get("result")


async def get_block_number(http: httpx.AsyncClient, chain_id: int) -> int:
    spec = get_chain(chain_id)
    raw = await _rpc(http, spec.rpc_url(), "eth_blockNumber", [])
    return int(raw, 16)


def _hex_to_int(s: str | None) -> int:
    if s is None or s == "0x":
        return 0
    return int(s, 16)


def _parse_tx(raw: dict[str, Any]) -> TxRecord:
    return TxRecord(
        hash=str(raw["hash"]).lower(),
        block_number=_hex_to_int(raw.get("blockNumber")),
        from_address=str(raw["from"]).lower(),
        to_address=str(raw["to"]).lower() if raw.get("to") else None,
        value_wei=_hex_to_int(raw.get("value")),
    )


async def get_block_with_txs(
    http: httpx.AsyncClient, chain_id: int, block_number: int
) -> list[TxRecord]:
    """Fetch a block + its full tx list (eth_getBlockByNumber, full=true).

    On chains with very full blocks (Base mainnet at peak) this is a
    big payload (~1 MB). Acceptable for v0 — we only do it when there's
    a pending dust request and only on N most recent blocks.
    """
    spec = get_chain(chain_id)
    raw = await _rpc(
        http,
        spec.rpc_url(),
        "eth_getBlockByNumber",
        [hex(block_number), True],
    )
    if not raw or "transactions" not in raw:
        return []
    out: list[TxRecord] = []
    for t in raw["transactions"]:
        try:
            out.append(_parse_tx(t))
        except (KeyError, ValueError) as e:
            log.warning("tx_parse_skipped", err=str(e))
    return out


async def find_self_transfer(
    http: httpx.AsyncClient,
    *,
    chain_id: int,
    address: str,
    expected_value_wei: int,
    blocks_to_scan: int = 15,
    tolerance_wei: int = 0,
    min_block: int = 0,
) -> TxRecord | None:
    """Scan the last `blocks_to_scan` blocks for a tx where
    `from == to == address` and `value ≈ expected_value_wei`.

    `tolerance_wei` allows fuzzy matching: the tx value must be within
    ±tolerance_wei of the stored amount. This handles wallets (e.g. MetaMask)
    that cap ETH input at 8 decimal places and round away the per-user suffix
    — the user sends the base amount, which is within the suffix range of the
    stored amount. Default (0) = exact match.

    `min_block` is a freshness gate: any tx with block_number < min_block is
    skipped. Set this to the block number at the time the dust request was
    created so that a pre-existing self-transfer of the same amount (made for
    an unrelated reason before the user ran /verify) cannot satisfy the check.
    Default (0) = no freshness gate, i.e. any block in the scan window matches.

    Why scan-from-tip vs cursor: missed polls self-heal. If we cached
    "last seen block" and the watcher process restarted between blocks,
    we'd miss any tx in the gap. Re-scanning a small window every poll
    is cheap and correct.
    """
    addr = address.lower()
    head = await get_block_number(http, chain_id)
    start = max(0, head - blocks_to_scan + 1)

    best: TxRecord | None = None
    for bn in range(head, start - 1, -1):
        if bn < min_block:
            # Everything from here downward is before the request was created;
            # skip the remaining blocks entirely.
            break
        try:
            txs = await get_block_with_txs(http, chain_id, bn)
        except RpcError as e:
            log.warning("get_block_failed", chain_id=chain_id, block=bn, err=str(e))
            continue
        for tx in txs:
            if (
                tx.to_address is not None
                and tx.from_address == addr
                and tx.to_address == addr
                and abs(tx.value_wei - expected_value_wei) <= tolerance_wei
                and tx.block_number >= min_block
            ):
                # Latest match wins (highest block).
                if best is None or tx.block_number > best.block_number:
                    best = tx
    return best


async def confirmations_for(http: httpx.AsyncClient, chain_id: int, tx_block_number: int) -> int:
    head = await get_block_number(http, chain_id)
    return max(0, head - tx_block_number + 1)


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
            http,
            spec.rpc_url(),
            "eth_call",
            [{"to": contract, "data": "0x313ce567"}, "latest"],
        )
        if not result or result == "0x":
            return 18
        return int(result, 16)
    except RpcError:
        return 18
