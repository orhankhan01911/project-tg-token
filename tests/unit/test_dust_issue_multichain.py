from unittest.mock import AsyncMock, patch

import pytest

from app.auth.dust import derive_amount, format_amount_sol, format_amount_ton


@pytest.mark.unit
def test_format_amount_ton_basic():
    # 10_001_234 nanoTON = 0.010001234 TON
    assert format_amount_ton(10_001_234) == "0.010001234"


@pytest.mark.unit
def test_format_amount_ton_whole():
    # 1_000_000_000 nanoTON = 1.0 TON
    assert format_amount_ton(1_000_000_000) == "1.0"


@pytest.mark.unit
def test_format_amount_sol_basic():
    # 1_001_234 lamports = 0.001001234 SOL
    assert format_amount_sol(1_001_234) == "0.001001234"


@pytest.mark.unit
def test_derive_amount_uses_custom_base_and_modulus():
    amount = derive_amount(
        tg_user_id=123, chat_id=456, nonce="abc", base=10_000_000, modulus=1_000_000
    )
    assert 10_000_000 <= amount < 11_000_000


@pytest.mark.unit
def test_derive_amount_deterministic():
    a = derive_amount(tg_user_id=1, chat_id=2, nonce="n", base=1_000_000, modulus=100_000)
    b = derive_amount(tg_user_id=1, chat_id=2, nonce="n", base=1_000_000, modulus=100_000)
    assert a == b


@pytest.mark.unit
async def test_issue_dust_request_ton():
    """TON request stores chain_type='ton' and uses nanoTON base."""
    import mongomock_motor

    from app.auth.dust import issue_dust_request

    db = mongomock_motor.AsyncMongoMockClient()["tg_token"]

    with patch("app.auth.dust.get_ton_latest_lt", new_callable=AsyncMock) as mock_lt:
        mock_lt.return_value = 47592000000099
        req = await issue_dust_request(
            db,
            tg_user_id=111,
            chat_id=222,
            address="EQBaCgUwOoc6gHCNln_oJzb0mVs79YG7wYoavh-o1ItaneLA",
            chain_id=0,
            chain_type="ton",
        )

    assert req.chain_type == "ton"
    assert 10_000_000 <= req.amount_wei < 11_000_000  # nanoTON base range
    assert req.created_block == 47592000000099  # LT stored as created_block


@pytest.mark.unit
async def test_issue_dust_request_solana():
    """Solana request stores chain_type='solana' and uses lamports base."""
    import mongomock_motor

    from app.auth.dust import issue_dust_request

    db = mongomock_motor.AsyncMongoMockClient()["tg_token"]

    with patch("app.auth.dust.get_solana_current_slot", new_callable=AsyncMock) as mock_slot:
        mock_slot.return_value = 987654321
        req = await issue_dust_request(
            db,
            tg_user_id=333,
            chat_id=444,
            address="5UUH9RTDiSpq6HKS6bp4NdU9PNJpXRXuiw6ShBTBhgH2",
            chain_id=0,
            chain_type="solana",
        )

    assert req.chain_type == "solana"
    assert 1_000_000 <= req.amount_wei < 1_100_000  # lamports base range
    assert req.created_block == 987654321  # slot stored as created_block
