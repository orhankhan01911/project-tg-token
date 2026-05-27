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
    "my_chat_member",  # bot promoted/demoted in a group — needed to register chats
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


async def _wait_for_telegram(bot: Bot, max_attempts: int = 10, base_delay: float = 2.0) -> None:
    """Retry bot.get_me() with exponential backoff until the Telegram API is reachable.

    Containers on a fresh bridge network can have a brief window (~1-2s) where
    DNS/NAT rules aren't wired yet.  Rather than crash-restart (which leaves a
    spurious TelegramNetworkError in logs), we absorb the transient here.
    """
    from aiogram.exceptions import TelegramNetworkError

    for attempt in range(1, max_attempts + 1):
        try:
            # Short per-attempt timeout: on networks where some Telegram IPs
            # are blocked, aiohttp may land on a slow IPv4 path that takes 60s
            # to time out.  10s per attempt keeps the retry cadence tight.
            me = await bot.get_me(request_timeout=10)
            log.info("telegram_connected", username=me.username, attempt=attempt)
            return
        except TelegramNetworkError as exc:
            if attempt == max_attempts:
                raise
            delay = min(base_delay * (2 ** (attempt - 1)), 30.0)
            log.warning(
                "telegram_connect_retry",
                attempt=attempt,
                max_attempts=max_attempts,
                delay_s=round(delay, 1),
                error=str(exc),
            )
            await asyncio.sleep(delay)


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
        day=1,
        hour=getattr(settings, "purge_hour_utc", 0),
        kwargs={"bot": bot, "db": db, "http": http},
        id="monthly_purge",
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

    # Ensure Telegram API is reachable before handing off to aiogram's polling
    # loop (which calls get_me() itself and would crash on a cold network).
    await _wait_for_telegram(bot)

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
