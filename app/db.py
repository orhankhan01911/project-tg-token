"""Motor async client + index bootstrap.

Indexes are *the* schema in MongoDB. Listing them here, in code, makes the
schema reviewable in PRs and re-applied on every startup (`ensure_indexes`
is idempotent — calling it twice is cheap). Workspace convention is no
SQLAlchemy/Alembic — the lifespan-applied bootstrap below is what
`project-btcV2/backend/app/db/indexes.py` does.
"""

from __future__ import annotations

from typing import Any, cast

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING

from app.logging_conf import get_logger
from app.settings import settings

log = get_logger(__name__)


def make_client(uri: str | None = None) -> AsyncIOMotorClient[Any]:
    return AsyncIOMotorClient[Any](
        uri or settings.mongo_uri,
        uuidRepresentation="standard",
        serverSelectionTimeoutMS=2000,
    )


def get_db(
    client: AsyncIOMotorClient[Any], db_name: str | None = None
) -> AsyncIOMotorDatabase[Any]:
    return client[db_name or settings.mongo_db]


async def ensure_indexes(db: AsyncIOMotorDatabase[Any]) -> None:
    """Idempotent index bootstrap. Safe to call on every startup.

    Index choices, briefly:
    - `whitelist`: composite-unique on (chat_id, tg_user_id) — closes G6
      and keeps "is this user whitelisted in this chat?" a single point read.
    - `gates`: lookup by chat_id — every join evaluates all gates for a chat.
    - `verifications`: composite (tg_user_id, chat_id) for the gate
      evaluator's per-user lookup; non-unique because a user may have
      multiple bound wallets per chat (one per chain).
    - `events`: `_id` is the idem_key (no extra index needed); MongoDB's
      unique-on-`_id` is the dedup primitive.
    """
    await cast(Any, db.whitelist).create_index(
        [("chat_id", ASCENDING), ("tg_user_id", ASCENDING)],
        unique=True,
        name="whitelist_chat_user_unique",
    )
    await cast(Any, db.gates).create_index(
        [("chat_id", ASCENDING)],
        name="gates_by_chat",
    )
    await cast(Any, db.verifications).create_index(
        [("tg_user_id", ASCENDING), ("chat_id", ASCENDING)],
        name="verifications_user_chat",
    )
    await cast(Any, db.verifications).create_index(
        [("chain", ASCENDING), ("address", ASCENDING)],
        unique=True,
        name="verifications_chain_address_unique",
    )
    # Prevent one dust tx from satisfying multiple requests (e.g. same wallet
    # joining two chats). sparse=True so SIWE verifications (which store a
    # signature in sig_or_txhash) don't falsely conflict with each other on
    # the empty-string / non-tx-hash values — each dust row will have a unique
    # tx hash string and sparse index only indexes non-null, non-absent values.
    await cast(Any, db.verifications).create_index(
        [("sig_or_txhash", ASCENDING)],
        unique=True,
        sparse=True,
        name="verifications_sig_or_txhash_unique_sparse",
    )

    # Dust verification: pending requests are auto-cleaned via TTL on
    # `expires_at` (Mongo runs the reaper every 60s; effective expiry is
    # the field value, the cleanup is the lag). The status index speeds
    # up the watcher's "find me all pending" scan.
    await cast(Any, db.dust_requests).create_index(
        [("expires_at", ASCENDING)],
        expireAfterSeconds=0,
        name="dust_requests_ttl",
    )
    await cast(Any, db.dust_requests).create_index(
        [("status", ASCENDING), ("chain_id", ASCENDING)],
        name="dust_requests_by_status_chain",
    )
    # token_gates: one basket per chat
    await cast(Any, db.token_gates).create_index(
        [("chat_id", ASCENDING)],
        unique=True,
        name="token_gates_by_chat",
    )
    log.info("indexes_ensured", db=db.name)
