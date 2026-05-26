from unittest.mock import patch

import httpx
import pytest
import respx

from app.chains.solana import find_solana_self_transfer, get_solana_current_slot

ADDR = "5UUH9RTDiSpq6HKS6bp4NdU9PNJpXRXuiw6ShBTBhgH2"
HELIUS_URL = "https://mainnet.helius-rpc.com/"


def _sigs_response(sigs: list[dict]) -> dict:
    return {"jsonrpc": "2.0", "id": 1, "result": sigs}


def _tx_response(source: str, destination: str, lamports: int, slot: int = 300) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "slot": slot,
            "transaction": {
                "message": {
                    "instructions": [
                        {
                            "program": "system",
                            "parsed": {
                                "type": "transfer",
                                "info": {
                                    "source": source,
                                    "destination": destination,
                                    "lamports": lamports,
                                },
                            },
                        }
                    ]
                }
            },
        },
    }


@pytest.mark.unit
async def test_find_solana_self_transfer_found():
    expected = 1_001_234

    with respx.mock(base_url=HELIUS_URL, assert_all_called=False) as mock:
        mock.post("").mock(
            side_effect=[
                httpx.Response(
                    200, json=_sigs_response([{"signature": "sig1", "slot": 300, "err": None}])
                ),
                httpx.Response(200, json=_tx_response(ADDR, ADDR, expected, slot=300)),
            ]
        )
        async with httpx.AsyncClient(base_url=HELIUS_URL) as http:
            with patch("app.chains.solana.settings") as mock_settings:
                mock_settings.helius_api_key = "testkey"
                tx = await find_solana_self_transfer(
                    http,
                    address=ADDR,
                    expected_lamports=expected,
                    tolerance_lamports=100_000,
                    min_slot=0,
                )

    assert tx is not None
    assert tx.signature == "sig1"
    assert tx.slot == 300
    assert tx.lamports == expected


@pytest.mark.unit
async def test_find_solana_self_transfer_not_found_wrong_amount():
    with respx.mock(base_url=HELIUS_URL, assert_all_called=False) as mock:
        mock.post("").mock(
            side_effect=[
                httpx.Response(
                    200, json=_sigs_response([{"signature": "sig1", "slot": 300, "err": None}])
                ),
                httpx.Response(200, json=_tx_response(ADDR, ADDR, 500_000, slot=300)),
            ]
        )
        async with httpx.AsyncClient(base_url=HELIUS_URL) as http:
            with patch("app.chains.solana.settings") as mock_settings:
                mock_settings.helius_api_key = "testkey"
                tx = await find_solana_self_transfer(
                    http,
                    address=ADDR,
                    expected_lamports=1_001_234,
                    tolerance_lamports=100_000,
                    min_slot=0,
                )
    assert tx is None


@pytest.mark.unit
async def test_find_solana_self_transfer_freshness_gate():
    """Skip txs with slot < min_slot."""
    with respx.mock(base_url=HELIUS_URL, assert_all_called=False) as mock:
        mock.post("").mock(
            side_effect=[
                httpx.Response(
                    200, json=_sigs_response([{"signature": "old_sig", "slot": 100, "err": None}])
                ),
            ]
        )
        async with httpx.AsyncClient(base_url=HELIUS_URL) as http:
            with patch("app.chains.solana.settings") as mock_settings:
                mock_settings.helius_api_key = "testkey"
                tx = await find_solana_self_transfer(
                    http,
                    address=ADDR,
                    expected_lamports=1_001_234,
                    tolerance_lamports=100_000,
                    min_slot=200,  # old_sig slot=100 < 200, must be skipped
                )
    assert tx is None


@pytest.mark.unit
async def test_find_solana_self_transfer_not_self():
    """Tx where source != destination must be ignored."""
    other = "So11111111111111111111111111111111111111112"
    with respx.mock(base_url=HELIUS_URL, assert_all_called=False) as mock:
        mock.post("").mock(
            side_effect=[
                httpx.Response(
                    200, json=_sigs_response([{"signature": "sig1", "slot": 300, "err": None}])
                ),
                httpx.Response(200, json=_tx_response(ADDR, other, 1_001_234, slot=300)),
            ]
        )
        async with httpx.AsyncClient(base_url=HELIUS_URL) as http:
            with patch("app.chains.solana.settings") as mock_settings:
                mock_settings.helius_api_key = "testkey"
                tx = await find_solana_self_transfer(
                    http,
                    address=ADDR,
                    expected_lamports=1_001_234,
                    tolerance_lamports=100_000,
                    min_slot=0,
                )
    assert tx is None


@pytest.mark.unit
async def test_get_solana_current_slot():
    with respx.mock(base_url=HELIUS_URL, assert_all_called=False) as mock:
        mock.post("").mock(
            return_value=httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": 987654321})
        )
        async with httpx.AsyncClient(base_url=HELIUS_URL) as http:
            with patch("app.chains.solana.settings") as mock_settings:
                mock_settings.helius_api_key = "testkey"
                slot = await get_solana_current_slot(http)
    assert slot == 987654321
