"""Unit tests for `app.auth.siwe.verify_siwe`. Sidecar HTTP is mocked via
respx — the real-sidecar coverage lives in tests/integration/."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from fakeredis import aioredis as fake

from app.auth.siwe import VerifyFail, VerifyOk, issue_siwe_nonce, verify_siwe
from app.settings import settings

pytestmark = pytest.mark.unit


@pytest.fixture
async def redis_fx():
    r = fake.FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


@pytest.fixture
async def http_fx():
    async with httpx.AsyncClient() as c:
        yield c


@pytest.fixture(autouse=True)
def _override_webapp_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the SIWE expected domain for tests."""
    monkeypatch.setattr(settings, "webapp_url", "https://miniapp.example.com")
    monkeypatch.setattr(settings, "verifier_url", "http://verifier.test")


def _siwe_message(
    *,
    domain: str = "miniapp.example.com",
    address: str = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
    nonce: str = "abc12345",
    chain_id: int = 84532,
    expiration_minutes: int = 5,
) -> str:
    """Build a SIWE message string without going through siwe-py — same
    rationale as `app/auth/siwe_parse.py`."""
    issued = datetime.now(tz=UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    expiry = (
        datetime.now(tz=UTC).replace(microsecond=0) + timedelta(minutes=expiration_minutes)
    ).isoformat().replace("+00:00", "Z")
    return "\n".join([
        f"{domain} wants you to sign in with your Ethereum account:",
        address,
        "",
        "Sign in to tg-token",
        "",
        f"URI: https://{domain}",
        "Version: 1",
        f"Chain ID: {chain_id}",
        f"Nonce: {nonce}",
        f"Issued At: {issued}",
        f"Expiration Time: {expiry}",
    ])


@respx.mock
async def test_happy_path(redis_fx, http_fx) -> None:
    nonce = await issue_siwe_nonce(redis_fx, tg_user_id=42, chat_id=-100)
    msg = _siwe_message(nonce=nonce)
    respx.post("http://verifier.test/verify").mock(
        return_value=httpx.Response(200, json={"ok": True, "recovered": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"})
    )
    result = await verify_siwe(
        redis=redis_fx,
        http=http_fx,
        message=msg,
        signature="0xfeedface",
        expected_address="0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
        tg_user_id=42,
        chat_id=-100,
    )
    assert isinstance(result, VerifyOk)
    assert result.address.lower() == ("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045").lower()
    assert result.nonce == nonce


@respx.mock
async def test_domain_mismatch_rejected(redis_fx, http_fx) -> None:
    nonce = await issue_siwe_nonce(redis_fx, tg_user_id=42, chat_id=-100)
    msg = _siwe_message(domain="evil.example.com", nonce=nonce)
    result = await verify_siwe(
        redis=redis_fx,
        http=http_fx,
        message=msg,
        signature="0xfeedface",
        expected_address="0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
        tg_user_id=42,
        chat_id=-100,
    )
    assert isinstance(result, VerifyFail)
    assert result.reason == "domain_mismatch"


@respx.mock
async def test_address_mismatch_rejected(redis_fx, http_fx) -> None:
    nonce = await issue_siwe_nonce(redis_fx, tg_user_id=42, chat_id=-100)
    msg = _siwe_message(address="0x71C7656EC7ab88b098defB751B7401B5f6d8976F", nonce=nonce)
    result = await verify_siwe(
        redis=redis_fx,
        http=http_fx,
        message=msg,
        signature="0xfeedface",
        expected_address="0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
        tg_user_id=42,
        chat_id=-100,
    )
    assert isinstance(result, VerifyFail)
    assert result.reason == "address_mismatch"


@respx.mock
async def test_expired_message_rejected(redis_fx, http_fx) -> None:
    nonce = await issue_siwe_nonce(redis_fx, tg_user_id=42, chat_id=-100)
    msg = _siwe_message(nonce=nonce, expiration_minutes=-5)
    result = await verify_siwe(
        redis=redis_fx,
        http=http_fx,
        message=msg,
        signature="0xfeedface",
        expected_address="0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
        tg_user_id=42,
        chat_id=-100,
    )
    assert isinstance(result, VerifyFail)
    assert result.reason == "expired"


@respx.mock
async def test_unknown_nonce_rejected(redis_fx, http_fx) -> None:
    msg = _siwe_message(nonce="never_issued12345")
    result = await verify_siwe(
        redis=redis_fx,
        http=http_fx,
        message=msg,
        signature="0xfeedface",
        expected_address="0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
        tg_user_id=42,
        chat_id=-100,
    )
    assert isinstance(result, VerifyFail)
    assert result.reason == "nonce_invalid_or_consumed"


@respx.mock
async def test_replay_rejected(redis_fx, http_fx) -> None:
    """First verify consumes the nonce; second verify with the same
    nonce + signature must fail even if everything else looks good."""
    nonce = await issue_siwe_nonce(redis_fx, tg_user_id=42, chat_id=-100)
    msg = _siwe_message(nonce=nonce)
    respx.post("http://verifier.test/verify").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    first = await verify_siwe(
        redis=redis_fx,
        http=http_fx,
        message=msg,
        signature="0xfeedface",
        expected_address="0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
        tg_user_id=42,
        chat_id=-100,
    )
    assert isinstance(first, VerifyOk)

    second = await verify_siwe(
        redis=redis_fx,
        http=http_fx,
        message=msg,
        signature="0xfeedface",
        expected_address="0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
        tg_user_id=42,
        chat_id=-100,
    )
    assert isinstance(second, VerifyFail)
    assert second.reason == "nonce_invalid_or_consumed"


@respx.mock
async def test_sidecar_rejection_rejects(redis_fx, http_fx) -> None:
    nonce = await issue_siwe_nonce(redis_fx, tg_user_id=42, chat_id=-100)
    msg = _siwe_message(nonce=nonce)
    respx.post("http://verifier.test/verify").mock(
        return_value=httpx.Response(200, json={"ok": False, "error": "bad_signature"})
    )
    result = await verify_siwe(
        redis=redis_fx,
        http=http_fx,
        message=msg,
        signature="0xfeedface",
        expected_address="0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
        tg_user_id=42,
        chat_id=-100,
    )
    assert isinstance(result, VerifyFail)
    assert result.reason == "bad_signature"


@respx.mock
async def test_sidecar_5xx_returns_status_reason(redis_fx, http_fx) -> None:
    nonce = await issue_siwe_nonce(redis_fx, tg_user_id=42, chat_id=-100)
    msg = _siwe_message(nonce=nonce)
    respx.post("http://verifier.test/verify").mock(
        return_value=httpx.Response(500, json={"error": "boom"})
    )
    result = await verify_siwe(
        redis=redis_fx,
        http=http_fx,
        message=msg,
        signature="0xfeedface",
        expected_address="0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
        tg_user_id=42,
        chat_id=-100,
    )
    assert isinstance(result, VerifyFail)
    assert result.reason == "sidecar_status_500"
