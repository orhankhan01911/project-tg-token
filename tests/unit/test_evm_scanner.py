"""Unit tests for `app.chains.evm.find_self_transfer` and chain dispatch.

We mock the JSON-RPC server with respx — the production-quality bar
demands self_transfer detection has positive + negative + edge-case
coverage at the unit level even before hitting a real RPC.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from app.chains.evm import (
    CHAINS,
    confirmations_for,
    find_self_transfer,
    get_block_number,
    get_chain,
)

pytestmark = pytest.mark.unit

ADDR = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045".lower()
RPC_URL = "https://sepolia.base.org"  # Base Sepolia public RPC


def _block(number: int, txs: list[dict]) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "number": hex(number),
            "transactions": txs,
        },
    }


def _block_number(n: int) -> dict:
    return {"jsonrpc": "2.0", "id": 1, "result": hex(n)}


def _tx(*, hash_: str, from_: str, to: str | None, value_wei: int, block: int) -> dict:
    return {
        "hash": hash_,
        "blockNumber": hex(block),
        "from": from_,
        "to": to,
        "value": hex(value_wei),
    }


# --- chain registry ---


def test_chain_registry_includes_base_sepolia() -> None:
    spec = get_chain(84532)
    assert spec.chain_id == 84532
    assert "base" in spec.name.lower()


def test_unsupported_chain_raises() -> None:
    with pytest.raises(ValueError, match="unsupported_chain"):
        get_chain(999_999)


def test_all_registered_chains_have_explorer_and_rpc() -> None:
    for cid, spec in CHAINS.items():
        assert spec.chain_id == cid
        assert spec.public_rpc.startswith("https://"), spec.name
        assert spec.explorer.startswith("https://"), spec.name


# --- get_block_number ---


@respx.mock
async def test_get_block_number_parses_hex() -> None:
    respx.post(RPC_URL).mock(return_value=httpx.Response(200, json=_block_number(123_456)))
    async with httpx.AsyncClient() as http:
        n = await get_block_number(http, 84532)
    assert n == 123_456


# --- confirmations_for ---


@respx.mock
async def test_confirmations_for_simple_math() -> None:
    respx.post(RPC_URL).mock(return_value=httpx.Response(200, json=_block_number(1000)))
    async with httpx.AsyncClient() as http:
        c = await confirmations_for(http, 84532, tx_block_number=995)
    assert c == 6  # 1000 - 995 + 1 = 6 (the tx's own block counts as 1)


# --- find_self_transfer ---


@respx.mock
async def test_find_self_transfer_happy_path() -> None:
    head = 100
    target_value = 12_345_678_999

    matching_tx = _tx(
        hash_="0xMATCH",
        from_=ADDR,
        to=ADDR,
        value_wei=target_value,
        block=98,
    )
    respx.post(RPC_URL).mock(
        side_effect=[
            httpx.Response(200, json=_block_number(head)),
            httpx.Response(200, json=_block(100, [])),
            httpx.Response(
                200,
                json=_block(
                    99,
                    [
                        _tx(
                            hash_="0xnoise",
                            from_=ADDR,
                            to="0xother",
                            value_wei=target_value,
                            block=99,
                        )
                    ],
                ),
            ),
            httpx.Response(200, json=_block(98, [matching_tx])),
            httpx.Response(200, json=_block(97, [])),
        ]
        + [httpx.Response(200, json=_block(b, [])) for b in range(96, 86 - 1, -1)]
    )

    async with httpx.AsyncClient() as http:
        tx = await find_self_transfer(
            http,
            chain_id=84532,
            address=ADDR,
            expected_value_wei=target_value,
            blocks_to_scan=15,
        )

    assert tx is not None
    assert tx.hash == "0xmatch"  # lowercased
    assert tx.from_address == ADDR
    assert tx.to_address == ADDR
    assert tx.value_wei == target_value


@respx.mock
async def test_find_self_transfer_rejects_wrong_amount() -> None:
    head = 100
    target_value = 12_345_678_999

    not_matching = _tx(
        hash_="0xWRONG",
        from_=ADDR,
        to=ADDR,
        value_wei=target_value + 1,  # off by one wei
        block=98,
    )
    respx.post(RPC_URL).mock(
        side_effect=[httpx.Response(200, json=_block_number(head))]
        + [
            httpx.Response(200, json=_block(b, [not_matching] if b == 98 else []))
            for b in range(100, 100 - 15, -1)
        ]
    )

    async with httpx.AsyncClient() as http:
        tx = await find_self_transfer(
            http,
            chain_id=84532,
            address=ADDR,
            expected_value_wei=target_value,
            blocks_to_scan=15,
        )

    assert tx is None


@respx.mock
async def test_find_self_transfer_rejects_non_self_transfer() -> None:
    head = 100
    target_value = 100

    cross_addr = _tx(
        hash_="0xCROSS",
        from_=ADDR,
        to="0xsomeoneelse" + "0" * 28,  # different address, same amount
        value_wei=target_value,
        block=98,
    )
    respx.post(RPC_URL).mock(
        side_effect=[httpx.Response(200, json=_block_number(head))]
        + [
            httpx.Response(200, json=_block(b, [cross_addr] if b == 98 else []))
            for b in range(100, 100 - 15, -1)
        ]
    )

    async with httpx.AsyncClient() as http:
        tx = await find_self_transfer(
            http,
            chain_id=84532,
            address=ADDR,
            expected_value_wei=target_value,
            blocks_to_scan=15,
        )

    assert tx is None


@respx.mock
async def test_find_self_transfer_picks_latest_when_multiple() -> None:
    head = 100
    target_value = 42

    older = _tx(hash_="0xOLD", from_=ADDR, to=ADDR, value_wei=target_value, block=95)
    newer = _tx(hash_="0xNEW", from_=ADDR, to=ADDR, value_wei=target_value, block=99)

    respx.post(RPC_URL).mock(
        side_effect=[httpx.Response(200, json=_block_number(head))]
        + [
            httpx.Response(
                200,
                json=_block(
                    b,
                    [newer] if b == 99 else [older] if b == 95 else [],
                ),
            )
            for b in range(100, 100 - 15, -1)
        ]
    )

    async with httpx.AsyncClient() as http:
        tx = await find_self_transfer(
            http,
            chain_id=84532,
            address=ADDR,
            expected_value_wei=target_value,
            blocks_to_scan=15,
        )

    assert tx is not None
    assert tx.hash == "0xnew"
