import pytest

from app.models.dust_request import DustRequest


@pytest.mark.unit
def test_dust_request_default_chain_type_is_evm():
    req = DustRequest.make(
        tg_user_id=1,
        chat_id=2,
        address="0xabc",
        chain_id=8453,
        amount_wei=40_001_234,
        ttl_seconds=3600,
    )
    assert req.chain_type == "evm"


@pytest.mark.unit
def test_dust_request_ton_chain_type():
    req = DustRequest.make(
        tg_user_id=1,
        chat_id=2,
        address="EQBaCgUwOoc6gHCNln_oJzb0mVs79YG7wYoavh-o1ItaneLA",
        chain_id=0,
        amount_wei=10_001_234,
        ttl_seconds=3600,
        chain_type="ton",
    )
    assert req.chain_type == "ton"
    assert req.chain_id == 0
    # TON addresses are case-sensitive -- must NOT be lowercased
    assert req.address == "EQBaCgUwOoc6gHCNln_oJzb0mVs79YG7wYoavh-o1ItaneLA"


@pytest.mark.unit
def test_dust_request_solana_chain_type():
    req = DustRequest.make(
        tg_user_id=1,
        chat_id=2,
        address="5UUH9RTDiSpq6HKS6bp4NdU9PNJpXRXuiw6ShBTBhgH2",
        chain_id=0,
        amount_wei=1_001_234,
        ttl_seconds=3600,
        chain_type="solana",
    )
    assert req.chain_type == "solana"
    assert req.address == "5UUH9RTDiSpq6HKS6bp4NdU9PNJpXRXuiw6ShBTBhgH2"


@pytest.mark.unit
def test_dust_request_roundtrip_chain_type():
    req = DustRequest.make(
        tg_user_id=1,
        chat_id=2,
        address="EQBaCgUwOoc6gHCNln_oJzb0mVs79YG7wYoavh-o1ItaneLA",
        chain_id=0,
        amount_wei=1234,
        ttl_seconds=3600,
        chain_type="ton",
    )
    dumped = req.model_dump(by_alias=True)
    loaded = DustRequest.model_validate(dumped)
    assert loaded.chain_type == "ton"
