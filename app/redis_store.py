"""Async Redis client + nonce-store helpers.

We name this module `redis_store` (not `redis`) to avoid shadowing the
pip package import path.

The nonce primitive is `SET ... NX EX <ttl>`: atomic insert-if-absent with
expiry, the canonical idempotency / one-shot-token pattern. `consume`
deletes the key on first successful read so a nonce can only be used
exactly once — replay protection without an audit log.
"""

from __future__ import annotations

from typing import cast

import redis.asyncio as aioredis

from app.settings import settings


def make_redis(url: str | None = None) -> aioredis.Redis:
    return aioredis.from_url(
        url or settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=2,
    )


def _nonce_key(scope: str, *parts: str | int) -> str:
    return ":".join(["nonce", scope, *(str(p) for p in parts)])


async def issue_nonce(
    r: aioredis.Redis, scope: str, *parts: str | int, value: str, ttl: int
) -> bool:
    """Atomic SET NX EX. Returns True if the nonce was stored, False if a
    fresh one already exists for this key (caller should not overwrite —
    that would invalidate an in-flight signature)."""
    key = _nonce_key(scope, *parts)
    set_ok = await cast(
        "object",
        r.set(key, value, nx=True, ex=ttl),  # type: ignore[misc]
    )
    return bool(set_ok)


async def peek_nonce(r: aioredis.Redis, scope: str, *parts: str | int) -> str | None:
    return await cast("object", r.get(_nonce_key(scope, *parts)))  # type: ignore[no-any-return]


async def consume_nonce(r: aioredis.Redis, scope: str, *parts: str | int, expected: str) -> bool:
    """Delete the nonce iff it equals `expected`. Returns True on success
    (nonce existed, matched, and is now consumed). The compare-and-delete
    is done with a tiny Lua script so the check + delete are atomic."""
    key = _nonce_key(scope, *parts)
    script = """
    if redis.call('GET', KEYS[1]) == ARGV[1] then
        return redis.call('DEL', KEYS[1])
    else
        return 0
    end
    """
    n = await cast("object", r.eval(script, 1, key, expected))  # type: ignore[misc]
    return bool(n)
