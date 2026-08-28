"""Governance engine: public submissions, voting, reports, removals, appeals
(spec §3.3, §4, §5.2–5.7)."""

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from aiogram import Bot
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    InputMediaVideo,
    InputMediaAnimation,
)
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.enums import (
    MediaType,
    RemovalDecision,
    RemovalTrigger,
    ReportReason,
    SubmissionStatus,
    Visibility,
    VoteValue,
)
from app.models import Meme, RemovalCase, Report, Submission, User, Vote
from app.policy import evaluate_submission
from app.redis_client import get_redis
from app.i18n import t

logger = logging.getLogger(__name__)
settings = get_settings()


class GovernanceError(Exception):
    """User-facing governance error."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── channel posting helpers ──────────────────────────────────────────────────

async def _post_channel_media(bot: Bot, chat_id: int, meme: Meme, caption: str):
    mtype = MediaType(meme.media_type)
    if mtype == MediaType.STICKER:
        msg = await bot.send_sticker(chat_id, meme.telegram_file_id)
        return msg
    senders = {
        MediaType.PHOTO: bot.send_photo,
        MediaType.VIDEO: bot.send_video,
        MediaType.ANIMATION: bot.send_animation,
        MediaType.VOICE: bot.send_voice,
        MediaType.AUDIO: bot.send_audio,
    }
    sender = senders.get(mtype)
    if not sender:
        raise GovernanceError(f"Cannot post media type {mtype} to channel")
    msg = await sender(chat_id, meme.telegram_file_id, caption=caption)
    return msg


def _vote_keyboard(submission_id: UUID) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="👍", callback_data=f"vote:{submission_id}:up"),
                InlineKeyboardButton(text="👎", callback_data=f"vote:{submission_id}:down"),
            ]
        ]
    )


# ── public submission lifecycle ──────────────────────────────────────────────

async def open_submission(
    bot: Bot, session: AsyncSession, meme: Meme, submitter: User, locale: str = "en"
) -> Submission:
    submission = Submission(
        meme_id=meme.id,
        submitter_id=submitter.id,
        status=SubmissionStatus.OPEN,
    )
    session.add(submission)
    await session.flush()

    if settings.review_channel_id:
        caption = (
            t(
                "channel_submission_caption",
                locale,
                title=meme.title,
                tags=", ".join(meme.tags),
                nsfw=("yes" if meme.nsfw else "no"),
                by=f"@{submitter.username or submitter.telegram_id}",
            )
            + "\n"
            + t("channel_vote_help", locale)
        )
        msg = await _post_channel_media(
            bot, settings.review_channel_id, meme, caption
        )
        submission.channel_message_id = msg.message_id
        await session.flush()

    await session.commit()
    return submission


async def _tally(session: AsyncSession, submission_id: UUID) -> tuple[float, int]:
    rows = await session.execute(
        select(Vote.value, Vote.weight).where(Vote.submission_id == submission_id)
    )
    net = 0.0
    up = 0
    for value, weight in rows.all():
        if value == VoteValue.UP:
            net += weight
            up += 1
        else:
            net -= weight
    return net, up


async def cast_vote(
    bot: Bot,
    session: AsyncSession,
    submission_id: UUID,
    voter: User,
    value: VoteValue,
) -> dict:
    if voter.is_banned:
        raise GovernanceError("You are banned from voting.")
    submission = await session.get(Submission, submission_id)
    if not submission or submission.status != SubmissionStatus.OPEN:
        raise GovernanceError("This submission is not open for voting.")

    weight = _vote_weight(voter)
    existing = await session.scalar(
        select(Vote).where(
            Vote.submission_id == submission_id, Vote.voter_id == voter.id
        )
    )
    if existing:
        existing.value = value
        existing.weight = weight
    else:
        session.add(
            Vote(submission_id=submission_id, voter_id=voter.id, value=value, weight=weight)
        )
    await session.flush()

    meme = await session.get(Meme, submission.meme_id)
    net, up = await _tally(session, submission_id)
    decision = evaluate_submission(net, up, bool(meme and meme.nsfw))
    if decision is not None:
        await close_submission(bot, session, submission)
        return {"status": "closed", "decision": decision.value, "net": net, "up": up}

    if settings.review_channel_id and submission.channel_message_id:
        await _edit_submission_caption(bot, submission, net, up)
    return {"status": "open", "net": net, "up": up}


async def _edit_submission_caption(bot: Bot, submission: Submission, net: float, up: int) -> None:
    try:
        await bot.edit_message_caption(
            chat_id=settings.review_channel_id,
            message_id=submission.channel_message_id,
            caption=t("channel_voting_progress", "en", net=net, up=up),
            reply_markup=_vote_keyboard(submission.id),
        )
    except Exception:  # pragma: no cover - cosmetic
        logger.exception("Failed to edit submission caption")


def _vote_weight(user: User) -> float:
    from app.policy import vote_weight

    return vote_weight(user)


async def close_submission(bot: Bot, session: AsyncSession, submission: Submission) -> None:
    net, up = await _tally(session, submission_id=submission.id)
    meme = await session.get(Meme, submission.meme_id)
    decision = evaluate_submission(net, up, bool(meme and meme.nsfw))
    # Window closed without reaching threshold -> reject.
    if decision is None:
        decision = SubmissionStatus.REJECTED

    submission.status = decision
    submission.closed_at = _utcnow()
    if meme:
        meme.visibility = (
            Visibility.PUBLIC if decision == SubmissionStatus.APPROVED else Visibility.REJECTED
        )
        meme.reviewed_at = _utcnow()
    await session.commit()

    await _notify_submission_outcome(bot, submission, meme, decision)
    if settings.review_channel_id and submission.channel_message_id:
        verdict = "APPROVED ✅" if decision == SubmissionStatus.APPROVED else "REJECTED ❌"
        try:
            await bot.edit_message_caption(
                chat_id=settings.review_channel_id,
                message_id=submission.channel_message_id,
                caption=t("channel_voting_closed", "en", net=net, up=up, verdict=verdict),
                reply_markup=None,
            )
        except Exception:
            logger.exception("Failed to edit final submission caption")


async def _notify_submission_outcome(
    bot: Bot, submission: Submission, meme: Meme | None, decision: SubmissionStatus
) -> None:
    submitter = await session_get_user_by_id(submission.submitter_id)
    if not submitter:
        return
    loc = getattr(submitter, "locale", "en") or "en"
    text = (
        t("submission_approved", loc)
        if decision == SubmissionStatus.APPROVED
        else t("submission_rejected", loc)
    )
    try:
        await bot.send_message(submitter.telegram_id, text)
    except Exception:
        logger.exception("Failed to notify submitter %s", submitter.telegram_id)


async def session_get_user_by_id(user_id: int) -> User | None:
    from app.db import SessionLocal

    async with SessionLocal() as s:
        return await s.get(User, user_id)


# ── report / removal pipeline (spec §5.5) ─────────────────────────────────────

async def file_report(
    bot: Bot,
    session: AsyncSession,
    meme_id: UUID,
    reporter: User,
    reason: ReportReason,
    note: str | None = None,
) -> str:
    meme = await session.get(Meme, meme_id)
    if not meme or meme.visibility != Visibility.PUBLIC:
        raise GovernanceError("Only public memes can be reported.")
    session.add(Report(meme_id=meme_id, reporter_id=reporter.id, reason=reason, note=note))
    await session.flush()

    # Distinct reporters for this reason within the rolling window.
    window = _utcnow() - timedelta(hours=settings.report_window_hours)
    distinct = await session.scalar(
        select(func.count(func.distinct(Report.reporter_id))).where(
            Report.meme_id == meme_id,
            Report.reason == reason,
            Report.created_at >= window,
        )
    )
    if distinct and distinct >= settings.report_threshold:
        await trigger_removal_review(bot, session, meme, reason.value)
        return "removal_review_started"
    await session.commit()
    return "report_recorded"


async def trigger_removal_review(
    bot: Bot, session: AsyncSession, meme: Meme, cause: str
) -> None:
    meme.visibility = Visibility.REMOVED
    case = RemovalCase(
        meme_id=meme.id,
        trigger=RemovalTrigger.REPORT_THRESHOLD,
        policy_clause=f"§5.5(1) report_threshold ({cause})",
        decision=RemovalDecision.APPEAL_PENDING,
    )
    session.add(case)
    await session.flush()
    await session.commit()

    redis = await get_redis()
    await redis.set(
        f"rrev_deadline:{meme.id}",
        int((_utcnow() + timedelta(hours=settings.review_vote_window_hours)).timestamp()),
    )

    if settings.review_channel_id:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="Keep", callback_data=f"rrev:{meme.id}:keep"),
                    InlineKeyboardButton(text="Remove", callback_data=f"rrev:{meme.id}:remove"),
                ]
            ]
        )
        msg = await bot.send_message(
            settings.review_channel_id,
            t("channel_removal_caption", "en", meme_id=meme.id, cause=cause),
            reply_markup=kb,
        )
        await redis.set(f"rrev_msg:{meme.id}", msg.message_id)


async def cast_removal_review_vote(
    bot: Bot, session: AsyncSession, meme_id: UUID, voter: User, keep: bool
) -> None:
    redis = await get_redis()
    key_voters = f"rrev_voters:{meme_id}"
    if await redis.sismember(key_voters, voter.telegram_id):
        raise GovernanceError("You already voted on this removal review.")
    await redis.sadd(key_voters, voter.telegram_id)
    if keep:
        await redis.incr(f"rrev_keep:{meme_id}")
    else:
        await redis.incr(f"rrev_remove:{meme_id}")


async def close_removal_review(bot: Bot, session: AsyncSession, meme_id: UUID) -> None:
    redis = await get_redis()
    keep = int(await redis.get(f"rrev_keep:{meme_id}") or 0)
    remove = int(await redis.get(f"rrev_remove:{meme_id}") or 0)
    meme = await session.get(Meme, meme_id)
    case = await session.scalar(
        select(RemovalCase)
        .where(RemovalCase.meme_id == meme_id)
        .order_by(RemovalCase.created_at.desc())
    )
    if not meme or not case:
        return
    if keep >= remove:
        meme.visibility = Visibility.PUBLIC
        case.decision = RemovalDecision.KEPT
    else:
        meme.visibility = Visibility.REMOVED
        case.decision = RemovalDecision.REMOVED
    await session.commit()
    await redis.delete(
        f"rrev_keep:{meme_id}", f"rrev_remove:{meme_id}",
        f"rrev_voters:{meme_id}", f"rrev_deadline:{meme_id}", f"rrev_msg:{meme_id}",
    )
    if settings.review_channel_id:
        msg_id = await redis.get(f"rrev_msg:{meme_id}")
        verdict = "KEPT ✅" if keep > remove else "REMOVED ❌"
        try:
            await bot.edit_message_text(
                t("channel_removal_closed", "en", keep=keep, remove=remove, verdict=verdict),
                chat_id=settings.review_channel_id,
                message_id=msg_id,
                reply_markup=None,
            )
        except Exception:
            logger.exception("Failed to edit removal review message")


async def admin_remove(
    bot: Bot, session: AsyncSession, meme_id: UUID, admin: User, clause: str
) -> None:
    meme = await session.get(Meme, meme_id)
    if not meme:
        raise GovernanceError("Meme not found.")
    meme.visibility = Visibility.REMOVED
    meme.reviewed_at = _utcnow()
    session.add(
        RemovalCase(
            meme_id=meme.id,
            trigger=RemovalTrigger.ADMIN_MANUAL,
            policy_clause=clause,
            decided_by=admin.id,
            decision=RemovalDecision.REMOVED,
        )
    )
    await session.commit()


async def legal_remove(session: AsyncSession, meme_id: UUID, clause: str) -> None:
    meme = await session.get(Meme, meme_id)
    if not meme:
        raise GovernanceError("Meme not found.")
    meme.visibility = Visibility.REMOVED
    meme.reviewed_at = _utcnow()
    session.add(
        RemovalCase(
            meme_id=meme.id,
            trigger=RemovalTrigger.LEGAL_REQUEST,
            policy_clause=clause,
            decided_by=None,
            decision=RemovalDecision.REMOVED,
        )
    )
    await session.commit()


async def open_appeal(
    bot: Bot, session: AsyncSession, meme_id: UUID, user: User, reason: str
) -> str:
    meme = await session.get(Meme, meme_id)
    if not meme or meme.visibility != Visibility.REMOVED:
        raise GovernanceError("Only removed memes can be appealed.")
    case = await session.scalar(
        select(RemovalCase)
        .where(RemovalCase.meme_id == meme_id)
        .order_by(RemovalCase.created_at.desc())
    )
    if case and case.created_at:
        if _utcnow() - case.created_at > timedelta(days=settings.appeal_window_days):
            raise GovernanceError("Appeal window has closed.")
    if case:
        case.decision = RemovalDecision.APPEAL_PENDING
    else:
        case = RemovalCase(
            meme_id=meme.id,
            trigger=RemovalTrigger.ADMIN_MANUAL,
            policy_clause="§5.6 appeal",
            decision=RemovalDecision.APPEAL_PENDING,
        )
        session.add(case)
    await session.commit()

    note = f"📨 Appeal from @{user.username or user.telegram_id} for meme {meme.id}: {reason}"
    if settings.review_channel_id:
        try:
            await bot.send_message(settings.review_channel_id, note)
        except Exception:
            logger.exception("Failed to post appeal note")
    return "appeal_opened"


# ── admin notifications / illegal auto-reject / community downvote ─────────────

async def notify_admins(bot: Bot, text: str) -> None:
    """Fan out a notice to configured admins and the review channel."""
    for admin_id in settings.admin_users:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            logger.exception("Failed to notify admin %s", admin_id)
    if settings.review_channel_id:
        try:
            await bot.send_message(settings.review_channel_id, text)
        except Exception:
            logger.exception("Failed to post to review channel")


async def notify_illegal_match(bot: Bot, submitter: User, file_hash: str) -> None:
    """§5.3: report an illegal-content hash match to admins and the submitter."""
    loc = getattr(submitter, "locale", "en") or "en"
    await notify_admins(
        bot,
        f"🚫 Illegal-content hash match blocked an upload "
        f"(hash={file_hash[:12]}…) from @{submitter.username or submitter.telegram_id}.",
    )
    try:
        await bot.send_message(
            submitter.telegram_id,
            t("illegal_submitter", loc),
        )
    except Exception:
        logger.exception("Failed to notify submitter of illegal rejection")


async def record_illegal_auto_reject(
    bot: Bot, session: AsyncSession, meme: Meme, submitter: User
) -> None:
    """§5.3: illegal-content hash match → auto-reject, never enters channel."""
    meme.visibility = Visibility.REJECTED
    meme.reviewed_at = _utcnow()
    session.add(
        RemovalCase(
            meme_id=meme.id,
            trigger=RemovalTrigger.LEGAL_REQUEST,
            policy_clause="§5.3 illegal-content hash match",
            decided_by=None,
            decision=RemovalDecision.REMOVED,
        )
    )
    await session.commit()
    await notify_admins(
        bot,
        f"🚫 Auto-rejected illegal-content meme <code>{meme.id}</code> "
        f"from @{submitter.username or submitter.telegram_id} (hash blocklist).",
    )
    try:
        await bot.send_message(
            submitter.telegram_id,
            "Your submission was auto-rejected: it matched the illegal-content blocklist.",
        )
    except Exception:
        logger.exception("Failed to notify submitter of illegal rejection")


async def community_downvote(
    bot: Bot, session: AsyncSession, meme_id: UUID, user: User
) -> str:
    """§5.5.4: organic downvotes accumulate; past threshold → removal review."""
    if user.is_banned:
        raise GovernanceError("You are banned.")
    meme = await session.get(Meme, meme_id)
    if not meme or meme.visibility != Visibility.PUBLIC:
        raise GovernanceError("Only public memes can be downvoted.")
    meme.downvotes = (meme.downvotes or 0) + 1
    await session.flush()
    if meme.downvotes >= settings.community_downvote_threshold:
        await session.commit()
        await trigger_removal_review(bot, session, meme, "community_downvote §5.5.4")
        return "removal_review_started"
    await session.commit()
    return "downvoted"
