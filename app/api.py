"""FastAPI server for tg-token v2.

Runs as a separate process from the polling bot (`make api`). Both
processes connect to the same Mongo + Redis. The bot owns long-poll
update handling; the API owns Mini App auth + signature verification +
webhook receivers (added in S5).

Routes:
- GET  /health                      → liveness
- POST /siwe/nonce                  → issue a SIWE nonce for (user, chat)
- POST /siwe/verify                 → verify a signed SIWE message; on
                                      success persist a `verifications` row
                                      and best-effort approve the pending
                                      chat_join_request

Auth: every state-changing route validates Telegram `initData` HMAC and
extracts the tg_user_id from the verified payload. The client never gets
to claim arbitrary tg_user_ids.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated, Any

import httpx
import sentry_sdk
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field
from redis.asyncio import Redis as AsyncRedis

from app.auth.initdata import Invalid as InitDataInvalid
from app.auth.initdata import Verified as InitDataVerified
from app.auth.initdata import verify_init_data
from app.auth.siwe import (
    VerifyFail,
    VerifyOk,
    issue_siwe_nonce,
    verify_siwe,
)
from app.db import ensure_indexes, get_db
from app.db import make_client as make_mongo_client
from app.logging_conf import configure_logging, get_logger
from app.models import Chain, Verification, VerificationMethod
from app.redis_store import make_redis
from app.settings import settings

log = get_logger(__name__)


def _init_sentry() -> None:
    if settings.sentry_dsn:
        sentry_sdk.init(dsn=settings.sentry_dsn, traces_sample_rate=0.0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    _init_sentry()

    mongo = make_mongo_client()
    db = get_db(mongo)
    await ensure_indexes(db)

    redis = make_redis()
    await redis.ping()  # type: ignore[misc]

    http = httpx.AsyncClient(timeout=10.0)

    bot: Bot | None = None
    if settings.bot_token:
        bot = Bot(
            token=settings.bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )

    app.state.mongo = mongo
    app.state.db = db
    app.state.redis = redis
    app.state.http = http
    app.state.bot = bot

    log.info("api_starting", mongo_db=db.name, has_bot=bot is not None)
    try:
        yield
    finally:
        log.info("api_stopping")
        await http.aclose()
        await redis.aclose()
        if bot is not None:
            await bot.session.close()
        mongo.close()


app = FastAPI(title="tg-token", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    allow_credentials=False,
)


# --- Dependency helpers ---


async def get_dbh() -> AsyncIOMotorDatabase[Any]:
    return app.state.db  # type: ignore[no-any-return]


async def get_redish() -> AsyncRedis:
    return app.state.redis  # type: ignore[no-any-return]


async def get_httph() -> httpx.AsyncClient:
    return app.state.http  # type: ignore[no-any-return]


def get_both() -> Bot | None:
    return app.state.bot  # type: ignore[no-any-return]


def _verify_init_data_or_401(init_data: str) -> InitDataVerified:
    result = verify_init_data(
        init_data,
        bot_token=settings.bot_token,
        max_age_seconds=settings.initdata_max_age_seconds,
    )
    if isinstance(result, InitDataInvalid):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "init_data_invalid", "reason": result.reason},
        )
    return result


# --- Routes ---


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "version": app.version}


class NonceRequest(BaseModel):
    init_data: str = Field(..., min_length=1, alias="initData")
    chat_id: int


class NonceResponse(BaseModel):
    nonce: str
    ttl_seconds: int


@app.post("/siwe/nonce", response_model=NonceResponse)
async def siwe_nonce(
    body: NonceRequest,
    redis: Annotated[AsyncRedis, Depends(get_redish)],
) -> NonceResponse:
    verified = _verify_init_data_or_401(body.init_data)
    tg_user_id = int(verified.user.get("id", 0))
    if not tg_user_id:
        raise HTTPException(401, detail="missing_user_id")

    nonce = await issue_siwe_nonce(redis, tg_user_id=tg_user_id, chat_id=body.chat_id)
    log.info(
        "siwe_nonce_issued",
        tg_user_id=tg_user_id,
        chat_id=body.chat_id,
    )
    return NonceResponse(nonce=nonce, ttl_seconds=settings.siwe_nonce_ttl_seconds)


class VerifyRequest(BaseModel):
    init_data: str = Field(..., min_length=1, alias="initData")
    chat_id: int
    message: str
    signature: str
    address: str
    chain: Chain = Chain.BASE_SEPOLIA  # default for v0; Mini App will pass real value


class VerifyResponse(BaseModel):
    ok: bool
    address: str | None = None
    approved_join: bool = False
    reason: str | None = None


async def _persist_verification(
    db: AsyncIOMotorDatabase[Any],
    *,
    tg_user_id: int,
    chat_id: int,
    address: str,
    chain: Chain,
    nonce: str,
    signature: str,
) -> None:
    v = Verification(
        tg_user_id=tg_user_id,
        chat_id=chat_id,
        address=address,
        chain=chain,
        method=VerificationMethod.SIWE,
        nonce=nonce,
        sig_or_txhash=signature,
    )
    await db.verifications.update_one(
        {"tg_user_id": tg_user_id, "chat_id": chat_id, "chain": chain.value},
        {"$set": v.model_dump()},
        upsert=True,
    )


async def _try_approve_join(bot: Bot | None, *, chat_id: int, tg_user_id: int) -> bool:
    if bot is None:
        return False
    try:
        await bot.approve_chat_join_request(chat_id=chat_id, user_id=tg_user_id)
        return True
    except TelegramAPIError as e:
        log.info(
            "approve_join_skipped",
            chat_id=chat_id,
            tg_user_id=tg_user_id,
            err=str(e),
        )
        return False


@app.post("/siwe/verify", response_model=VerifyResponse)
async def siwe_verify(
    body: VerifyRequest,
    db: Annotated[AsyncIOMotorDatabase[Any], Depends(get_dbh)],
    redis: Annotated[AsyncRedis, Depends(get_redish)],
    http: Annotated[httpx.AsyncClient, Depends(get_httph)],
) -> VerifyResponse:
    verified = _verify_init_data_or_401(body.init_data)
    tg_user_id = int(verified.user.get("id", 0))
    if not tg_user_id:
        raise HTTPException(401, detail="missing_user_id")

    bind = log.bind(tg_user_id=tg_user_id, chat_id=body.chat_id, address=body.address)
    bind.info("siwe_verify_received")

    result = await verify_siwe(
        redis=redis,
        http=http,
        message=body.message,
        signature=body.signature,
        expected_address=body.address,
        tg_user_id=tg_user_id,
        chat_id=body.chat_id,
    )
    if isinstance(result, VerifyFail):
        bind.info("siwe_verify_rejected", reason=result.reason)
        return VerifyResponse(ok=False, reason=result.reason)

    assert isinstance(result, VerifyOk)
    await _persist_verification(
        db,
        tg_user_id=tg_user_id,
        chat_id=body.chat_id,
        address=result.address,
        chain=body.chain,
        nonce=result.nonce,
        signature=body.signature,
    )

    bot = get_both()
    approved = await _try_approve_join(bot, chat_id=body.chat_id, tg_user_id=tg_user_id)

    bind.info("siwe_verify_ok", approved_join=approved)
    return VerifyResponse(ok=True, address=result.address, approved_join=approved)
