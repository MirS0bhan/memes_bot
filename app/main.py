"""Application entrypoint (spec §7.2, §7.4).

Runs the bot webhook (aiohttp) or long-polling, plus the background scheduler
when the role includes `worker`. Stateless, env-configured, horizontally scalable.
"""

import asyncio
import logging

from aiohttp import web

from app.bot import bot, dp, register_commands
from app.config import get_settings
from app.jobs import scheduler_loop
from app.logging_config import configure_logging, log_event
from app.metrics import metrics_middleware, render
from app.migrate import migrate
from app.redis_client import close_redis

settings = get_settings()
logger = logging.getLogger(__name__)


async def _run_webhook() -> None:
    await bot.set_webhook(
        settings.webhook_url,
        secret_token=settings.webhook_secret or None,
        drop_pending_updates=True,
    )
    logger.info("Webhook set: %s", settings.webhook_url)

    async def handle(request: web.Request) -> web.Response:
        if settings.webhook_secret:
            if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != settings.webhook_secret:
                return web.Response(status=403)
        raw = await request.text()
        from aiogram.types import Update

        update = Update.model_validate_json(raw)
        await dp.feed_update(bot, update)
        return web.Response()

    app = web.Application()
    app.router.add_post(settings.webhook_path, handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, settings.listen_host, settings.listen_port)
    await site.start()
    logger.info("Webhook server listening on %s:%s%s", settings.listen_host, settings.listen_port, settings.webhook_path)
    # Keep running.
    stop = asyncio.Event()
    await stop.wait()


async def _run_polling() -> None:
    logger.info("Starting long polling")
    await dp.start_polling(bot)


async def _run_metrics() -> None:
    from aiohttp import web

    async def handle(request: web.Request) -> web.Response:
        return web.Response(body=render(), content_type="text/plain; version=0.0.4")

    app = web.Application()
    app.router.add_get("/metrics", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, settings.listen_host, settings.metrics_port)
    await site.start()
    logger.info("Metrics server listening on %s:%s/metrics", settings.listen_host, settings.metrics_port)
    stop = asyncio.Event()
    await stop.wait()


async def main() -> None:
    configure_logging()
    await migrate()
    await register_commands()
    dp.update.outer_middleware(metrics_middleware)
    log_event(logger, "bot_start", role=settings.role)

    tasks = [_run_metrics()]
    if settings.role in ("web", "both"):
        tasks.append(_run_webhook() if settings.webhook_url else _run_polling())
    elif settings.role == "worker":
        pass  # worker-only: scheduler below
    else:
        tasks.append(_run_polling())

    if settings.role in ("worker", "both"):
        tasks.append(scheduler_loop())

    if not tasks:
        logger.warning("No tasks to run for role=%s", settings.role)
        return

    try:
        await asyncio.gather(*tasks)
    finally:
        await close_redis()


if __name__ == "__main__":
    asyncio.run(main())
