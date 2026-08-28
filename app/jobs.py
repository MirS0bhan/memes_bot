"""Scheduled background jobs (spec §7.3): close expired vote windows and
removal reviews. Runs as the `worker` role (or `both`)."""

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select

from app.bot import bot
from app.config import get_settings
from app.db import SessionLocal
from app.governance import close_removal_review, close_submission
from app.logging_config import log_event
from app.models import Submission
from app.redis_client import get_redis

settings = get_settings()
logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def close_expired_submissions() -> int:
    cutoff = _utcnow() - timedelta(hours=settings.vote_window_hours)
    async with SessionLocal() as session:
        rows = await session.execute(
            select(Submission).where(
                Submission.status == "open", Submission.opened_at < cutoff
            )
        )
        subs = rows.scalars().all()
        closed = 0
        for sub in subs:
            await close_submission(bot, session, sub)
            closed += 1
            log_event(logger, "submission_auto_closed", submission_id=str(sub.id))
    return closed


async def close_expired_removal_reviews() -> int:
    redis = await get_redis()
    keys = [k async for k in redis.scan_iter(match="rrev_deadline:*")]
    now_ts = int(_utcnow().timestamp())
    closed = 0
    for key in keys:
        deadline = await redis.get(key)
        if deadline and int(deadline) <= now_ts:
            meme_id = key.split(":", 1)[1]
            from uuid import UUID

            try:
                async with SessionLocal() as session:
                    await close_removal_review(bot, session, UUID(meme_id))
                closed += 1
                log_event(logger, "removal_review_auto_closed", meme_id=meme_id)
            except Exception:
                logger.exception("Failed to close removal review %s", meme_id)
    return closed


async def scheduler_loop() -> None:
    logger.info("Scheduler started")
    while True:
        try:
            await close_expired_submissions()
            await close_expired_removal_reviews()
        except Exception:
            logger.exception("Scheduler iteration failed")
        await asyncio.sleep(60)
