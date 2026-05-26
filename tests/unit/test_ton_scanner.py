import httpx
import pytest
import respx

from app.chains.ton import (
    find_ton_self_transfer,
    get_ton_latest_lt,
    ton_address_to_raw,
)

EQ_ADDR = "EQBaCgUwOoc6gHCNln_oJzb0mVs79YG7wYoavh-o1ItaneLA"
RAW_ADDR = "0:690a053283a87ba80708d967fe827b6f4995bef3c06ef062a8bafe8d48b69e94"


@pytest.mark.unit
def test_ton_address_to_raw_known():
    raw = ton_address_to_raw(EQ_ADDR)
    assert raw.startswith("0:")
    assert len(raw) == 2 + 64  # "0:" + 64 hex chars


@pytest.mark.unit
async def test_find_ton_self_transfer_found():
    raw = ton_address_to_raw(EQ_ADDR)
    expected_nanoton = 10_001_234

    mock_response = {
        "transactions": [
            {
                "hash": "abc123txhash",
                "lt": "47592000000003",
                "in_msg": {
                    "source": {"address": raw},
                    "destination": {"address": raw},
                    "value": expected_nanoton,
                    "msg_type": "int_msg",
                },
            }
        ]
    }

    with respx.mock:
        respx.get(f"https://tonapi.io/v2/accounts/{EQ_ADDR}/transactions").mock(
            return_value=httpx.Response(200, json=mock_response)
        )
        async with httpx.AsyncClient() as http:
            tx = await find_ton_self_transfer(
                http,
                address=EQ_ADDR,
                expected_nanoton=expected_nanoton,
                tolerance_nanoton=1_000_000,
                min_lt=0,
            )

    assert tx is not None
    assert tx.hash == "abc123txhash"
    assert tx.lt == 47592000000003
    assert tx.value == expected_nanoton


@pytest.mark.unit
async def test_find_ton_self_transfer_not_found_wrong_value():
    raw = ton_address_to_raw(EQ_ADDR)
    mock_response = {
        "transactions": [
            {
                "hash": "abc123txhash",
                "lt": "47592000000003",
                "in_msg": {
                    "source": {"address": raw},
                    "destination": {"address": raw},
                    "value": 9_000_000,  # way off
                    "msg_type": "int_msg",
                },
            }
        ]
    }

    with respx.mock:
        respx.get(f"https://tonapi.io/v2/accounts/{EQ_ADDR}/transactions").mock(
            return_value=httpx.Response(200, json=mock_response)
        )
        async with httpx.AsyncClient() as http:
            tx = await find_ton_self_transfer(
                http,
                address=EQ_ADDR,
                expected_nanoton=10_001_234,
                tolerance_nanoton=1_000_000,
                min_lt=0,
            )

    assert tx is None


@pytest.mark.unit
async def test_find_ton_self_transfer_freshness_gate():
    """Tx with lt < min_lt must be skipped."""
    raw = ton_address_to_raw(EQ_ADDR)
    mock_response = {
        "transactions": [
            {
                "hash": "old_tx",
                "lt": "100",  # old
                "in_msg": {
                    "source": {"address": raw},
                    "destination": {"address": raw},
                    "value": 10_001_234,
                    "msg_type": "int_msg",
                },
            }
        ]
    }

    with respx.mock:
        respx.get(f"https://tonapi.io/v2/accounts/{EQ_ADDR}/transactions").mock(
            return_value=httpx.Response(200, json=mock_response)
        )
        async with httpx.AsyncClient() as http:
            tx = await find_ton_self_transfer(
                http,
                address=EQ_ADDR,
                expected_nanoton=10_001_234,
                tolerance_nanoton=1_000_000,
                min_lt=200,  # tx lt=100 < 200, must be skipped
            )

    assert tx is None


@pytest.mark.unit
async def test_get_ton_latest_lt():
    mock_response = {"last_transaction_lt": "47592000000099"}

    with respx.mock:
        respx.get(f"https://tonapi.io/v2/accounts/{EQ_ADDR}").mock(
            return_value=httpx.Response(200, json=mock_response)
        )
        async with httpx.AsyncClient() as http:
            lt = await get_ton_latest_lt(http, address=EQ_ADDR)

    assert lt == 47592000000099


@pytest.mark.unit
async def test_find_ton_self_transfer_not_self_transfer():
    """Tx where source != destination must be ignored."""
    raw = ton_address_to_raw(EQ_ADDR)
    other = "0:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    mock_response = {
        "transactions": [
            {
                "hash": "not_self",
                "lt": "47592000000003",
                "in_msg": {
                    "source": {"address": other},  # different source
                    "destination": {"address": raw},
                    "value": 10_001_234,
                    "msg_type": "int_msg",
                },
            }
        ]
    }

    with respx.mock:
        respx.get(f"https://tonapi.io/v2/accounts/{EQ_ADDR}/transactions").mock(
            return_value=httpx.Response(200, json=mock_response)
        )
        async with httpx.AsyncClient() as http:
            tx = await find_ton_self_transfer(
                http,
                address=EQ_ADDR,
                expected_nanoton=10_001_234,
                tolerance_nanoton=1_000_000,
                min_lt=0,
            )

    assert tx is None
