"""Hits a real Mongo to prove the index bootstrap actually enforces what
mongomock cannot. Required by the production-quality testing bar — silent
divergence between mock and prod is the bug class we're refusing to ship.

Skipped if a Mongo daemon isn't reachable on `MONGO_URI`. CI brings one
up via the same docker-compose used in dev.
"""

from __future__ import annotations

import os

import pytest
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import DuplicateKeyError, ServerSelectionTimeoutError

from app.db import ensure_indexes

pytestmark = pytest.mark.integration

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017")


@pytest.fixture
async def db():
    client: AsyncIOMotorClient = AsyncIOMotorClient(
        MONGO_URI, serverSelectionTimeoutMS=2000
    )
    try:
        await client.admin.command("ping")
    except ServerSelectionTimeoutError:
        pytest.skip(f"Mongo not reachable at {MONGO_URI}")
    db = client["tg_token_test_indexes"]
    # Reset state between runs; the test owns this throwaway database.
    await client.drop_database("tg_token_test_indexes")
    await ensure_indexes(db)
    yield db
    await client.drop_database("tg_token_test_indexes")
    client.close()


async def test_whitelist_composite_unique(db) -> None:
    await db.whitelist.insert_one({"chat_id": -100, "tg_user_id": 42})
    with pytest.raises(DuplicateKeyError):
        await db.whitelist.insert_one({"chat_id": -100, "tg_user_id": 42})


async def test_whitelist_distinct_users_in_same_chat_ok(db) -> None:
    await db.whitelist.insert_one({"chat_id": -100, "tg_user_id": 42})
    await db.whitelist.insert_one({"chat_id": -100, "tg_user_id": 43})
    count = await db.whitelist.count_documents({"chat_id": -100})
    assert count == 2


async def test_events_idem_key_dedupes(db) -> None:
    await db.events.insert_one({"_id": "base:0xtx:0", "kind": "x"})
    with pytest.raises(DuplicateKeyError):
        await db.events.insert_one({"_id": "base:0xtx:0", "kind": "x"})


async def test_verifications_chain_address_unique(db) -> None:
    """One wallet on one chain → one tg_user_id (sybil mitigation)."""
    await db.verifications.insert_one(
        {"tg_user_id": 1, "chat_id": -100, "chain": "base-sepolia", "address": "0xabc"}
    )
    with pytest.raises(DuplicateKeyError):
        await db.verifications.insert_one(
            {"tg_user_id": 2, "chat_id": -100, "chain": "base-sepolia", "address": "0xabc"}
        )


async def test_verifications_same_address_different_chain_ok(db) -> None:
    """The same address on a *different* chain is a different binding."""
    await db.verifications.insert_one(
        {"tg_user_id": 1, "chat_id": -100, "chain": "base-sepolia", "address": "0xabc"}
    )
    await db.verifications.insert_one(
        {"tg_user_id": 1, "chat_id": -100, "chain": "eth", "address": "0xabc"}
    )
