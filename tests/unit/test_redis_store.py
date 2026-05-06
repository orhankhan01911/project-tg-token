"""Unit tests for `app.redis_store` using fakeredis. Same wire semantics
as a real Redis (NX/EX/EVAL all supported)."""

from __future__ import annotations

import pytest
from fakeredis import aioredis as fake

from app.redis_store import consume_nonce, issue_nonce, peek_nonce

pytestmark = pytest.mark.unit


@pytest.fixture
async def r():
    redis = fake.FakeRedis(decode_responses=True)
    yield redis
    await redis.aclose()


async def test_issue_nonce_returns_true_first_then_false(r) -> None:
    ok1 = await issue_nonce(r, "siwe", 42, -100, value="abc", ttl=60)
    assert ok1 is True
    ok2 = await issue_nonce(r, "siwe", 42, -100, value="def", ttl=60)
    assert ok2 is False  # NX should refuse to overwrite
    assert (await peek_nonce(r, "siwe", 42, -100)) == "abc"


async def test_consume_nonce_one_shot(r) -> None:
    await issue_nonce(r, "siwe", 42, -100, value="abc", ttl=60)
    assert (await consume_nonce(r, "siwe", 42, -100, expected="abc")) is True
    assert (await consume_nonce(r, "siwe", 42, -100, expected="abc")) is False
    assert (await peek_nonce(r, "siwe", 42, -100)) is None


async def test_consume_nonce_wrong_value_keeps_nonce(r) -> None:
    await issue_nonce(r, "siwe", 42, -100, value="abc", ttl=60)
    assert (await consume_nonce(r, "siwe", 42, -100, expected="WRONG")) is False
    # The original nonce is still there — wrong-value attempts must not
    # invalidate the legitimate nonce.
    assert (await peek_nonce(r, "siwe", 42, -100)) == "abc"


async def test_scope_isolates_keys(r) -> None:
    await issue_nonce(r, "siwe", 42, -100, value="abc", ttl=60)
    await issue_nonce(r, "other", 42, -100, value="xyz", ttl=60)
    assert (await peek_nonce(r, "siwe", 42, -100)) == "abc"
    assert (await peek_nonce(r, "other", 42, -100)) == "xyz"
