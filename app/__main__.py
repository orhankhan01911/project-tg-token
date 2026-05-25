"""Entry point: ``python -m app``.

Reads `.env`, configures structured logging, optionally inits Sentry, then
runs the aiogram polling loop subscribed to the four updates we care about
in v0: `chat_join_request`, `chat_member`, `message`, `callback_query`.

systemd's `EnvironmentFile=` populates the env in production. For local dev,
`pydantic-settings` reads `.env` from the working dir.
"""

from __future__ import annotations

import asyncio
import sys

import httpx
import sentry_sdk
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.bot import build_dispatcher
from app.db import ensure_indexes, get_db, make_client
from app.dust_watcher import watcher_loop
from app.logging_conf import configure_logging, get_logger
from app.purge import run_purge_all_chats
from app.settings import settings
from app.setup_wizard import router as setup_router

log = get_logger(__name__)


ALLOWED_UPDATES: list[str] = [
    "chat_join_request",
    "chat_member",
    "message",
    "callback_query",
]


def _init_sentry() -> None:
    if not settings.sentry_dsn:
        log.info("sentry_disabled", reason="empty SENTRY_DSN")
        return
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        traces_sample_rate=0.0,
        send_default_pii=False,
    )
    log.info("sentry_enabled")


async def _run() -> int:
    if not settings.bot_token:
        log.error("bot_token_missing", hint="set BOT_TOKEN in .env")
        return 2

    _init_sentry()
    mongo_client = make_client()
    db = get_db(mongo_client)
    await ensure_indexes(db)

    http = httpx.AsyncClient()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_purge_all_chats,
        trigger="cron",
        hour=getattr(settings, "purge_hour_utc", 0),
        kwargs={"bot": bot, "db": db, "http": http},
        id="daily_purge",
        replace_existing=True,
    )
    scheduler.start()

    dp = build_dispatcher()
    dp.include_router(setup_router)
    dp["db"] = db  # injected into every handler that declares `db` as a kwarg
    dp["http"] = http  # injected into handlers that declare `http` as a kwarg

    log.info(
        "bot_starting",
        owner_ids=sorted(settings.owner_ids) or None,
        allowed_updates=ALLOWED_UPDATES,
        mongo_db=db.name,
    )

    # Background dust watcher in the same event loop. Cancelled on shutdown.
    watcher_task = asyncio.create_task(watcher_loop(db, bot))

    try:
        await dp.start_polling(
            bot,
            allowed_updates=ALLOWED_UPDATES,
            handle_signals=True,
            close_bot_session=True,
        )
    finally:
        scheduler.shutdown(wait=False)
        watcher_task.cancel()
        try:
            await watcher_task
        except asyncio.CancelledError:
            pass
        await bot.session.close()
        await http.aclose()
        mongo_client.close()
    return 0


def main() -> int:
    configure_logging()
    try:
        return asyncio.run(_run())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
