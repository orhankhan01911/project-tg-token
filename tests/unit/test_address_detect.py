import pytest
from app.auth.address import detect_chain_type


@pytest.mark.unit
def test_evm_address():
    assert detect_chain_type("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045") == "evm"


@pytest.mark.unit
def test_evm_address_lowercase():
    assert detect_chain_type("0x532f27101965dd16442e59d40670faf5ebb142e4") == "evm"


@pytest.mark.unit
def test_ton_address_eq():
    assert detect_chain_type("EQBaCgUwOoc6gHCNln_oJzb0mVs79YG7wYoavh-o1ItaneLA") == "ton"


@pytest.mark.unit
def test_ton_address_uq():
    assert detect_chain_type("UQBaCgUwOoc6gHCNln_oJzb0mVs79YG7wYoavh-o1Itane00") == "ton"


@pytest.mark.unit
def test_solana_address():
    assert detect_chain_type("5UUH9RTDiSpq6HKS6bp4NdU9PNJpXRXuiw6ShBTBhgH2") == "solana"


@pytest.mark.unit
def test_solana_address_short():
    assert detect_chain_type("So11111111111111111111111111111111111111112") == "solana"


@pytest.mark.unit
def test_unknown_returns_none():
    assert detect_chain_type("notanaddress") is None


@pytest.mark.unit
def test_empty_returns_none():
    assert detect_chain_type("") is None


@pytest.mark.unit
def test_evm_too_short_returns_none():
    assert detect_chain_type("0xabc123") is None
