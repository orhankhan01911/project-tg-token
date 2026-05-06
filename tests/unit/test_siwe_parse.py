"""Unit tests for our minimal SIWE parser. Stress test included — the
upstream `siwe.parsed.ABNFParsedMessage` developed state corruption
under repeated parses, so we validate that ours doesn't.
"""

from __future__ import annotations

import pytest

from app.auth.siwe_parse import SiweParseError, parse_siwe

pytestmark = pytest.mark.unit


def _msg(
    *,
    domain: str = "miniapp.example.com",
    address: str = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
    statement: str | None = "Sign in",
    chain_id: int = 84532,
    nonce: str = "abc12345",
    expiration_time: str | None = "2026-12-31T23:59:59Z",
) -> str:
    parts = [
        f"{domain} wants you to sign in with your Ethereum account:",
        address,
        "",
    ]
    if statement:
        parts.extend([statement, ""])
    parts.extend([
        f"URI: https://{domain}",
        "Version: 1",
        f"Chain ID: {chain_id}",
        f"Nonce: {nonce}",
        "Issued At: 2026-01-01T00:00:00Z",
    ])
    if expiration_time:
        parts.append(f"Expiration Time: {expiration_time}")
    return "\n".join(parts)


def test_happy_path_with_statement() -> None:
    parsed = parse_siwe(_msg())
    assert parsed.domain == "miniapp.example.com"
    assert parsed.address == "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"
    assert parsed.statement == "Sign in"
    assert parsed.chain_id == 84532
    assert parsed.nonce == "abc12345"
    assert parsed.expiration_time == "2026-12-31T23:59:59Z"


def test_happy_path_without_statement() -> None:
    parsed = parse_siwe(_msg(statement=None))
    assert parsed.statement is None
    assert parsed.domain == "miniapp.example.com"


def test_no_expiration_is_optional() -> None:
    parsed = parse_siwe(_msg(expiration_time=None))
    assert parsed.expiration_time is None


def test_empty_message_rejected() -> None:
    with pytest.raises(SiweParseError):
        parse_siwe("")


def test_malformed_header_rejected() -> None:
    with pytest.raises(SiweParseError, match="header"):
        parse_siwe("garbage line\n0xdeadbeef\n")


def test_missing_required_field_rejected() -> None:
    msg = _msg().replace("Nonce: abc12345\n", "")
    with pytest.raises(SiweParseError, match="missing_field:Nonce"):
        parse_siwe(msg)


def test_bad_chain_id_rejected() -> None:
    msg = _msg().replace("Chain ID: 84532", "Chain ID: notanumber")
    with pytest.raises(SiweParseError, match="bad_chain_id"):
        parse_siwe(msg)


def test_stress_500_iterations_no_state_corruption() -> None:
    """The reason this parser exists. siwe-py's ABNF parser fails under
    this exact pattern (mixed addresses + nonces, repeated parses)."""
    addresses = [
        "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
        "0x71C7656EC7ab88b098defB751B7401B5f6d8976F",
    ]
    for i in range(500):
        m = _msg(address=addresses[i % 2], nonce=f"nonce{i}_xxxxxxxx")
        parsed = parse_siwe(m)
        assert parsed.address == addresses[i % 2]
        assert parsed.nonce == f"nonce{i}_xxxxxxxx"
