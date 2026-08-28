"""Telegram bot: handlers and dispatcher wiring (spec §3, §8)."""

import asyncio
import hashlib
import logging
import os
from uuid import UUID

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BotCommand,
    BotCommandScopeChat,
    CallbackQuery,
    ErrorEvent,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultCachedAudio,
    InlineQueryResultCachedMpeg4Gif,
    InlineQueryResultCachedPhoto,
    InlineQueryResultCachedSticker,
    InlineQueryResultCachedVideo,
    InlineQueryResultCachedVoice,
    InlineQueryResultArticle,
    InputTextMessageContent,
    Message,
)

from app.config import get_settings
from app.db import SessionLocal
from app.enums import MediaType, ReportReason, Visibility, VoteValue
from app.governance import (
    GovernanceError,
    admin_remove,
    cast_removal_review_vote,
    cast_vote,
    community_downvote,
    file_report,
    notify_illegal_match,
    open_appeal,
    open_submission,
)
from app.logging_config import configure_logging, log_event
from app.models import Meme, PolicyDocument, Submission, User
from app.redis_client import rate_limit
from app.repo import (
    add_illegal_hash,
    get_meme,
    get_or_create_user,
    find_public_by_hash,
    is_illegal_hash,
    log_retrieval,
    private_usage,
    recent_removal_cases,
    remove_illegal_hash,
)
from app.search import search
from app.storage import download_bytes, key_for, purge_media, send_media, store_media
from app.i18n import t, normalize_locale, SUPPORTED_LOCALES, DEFAULT_LOCALE
from app.metrics import (
    INLINE_QUERIES,
    REPORTS_FILED,
    REMOVAL_REVIEWS,
    SUBMISSIONS_OPENED,
    VOTES_CAST,
)

settings = get_settings()
logger = logging.getLogger(__name__)

bot = Bot(token=settings.bot_token)


def _build_fsm_storage():
    # Multi-replica safe: share FSM state via Redis when available (spec §7.2).
    if settings.redis_url:
        try:
            from aiogram.fsm.storage.redis import RedisStorage

            return RedisStorage.from_url(settings.redis_url)
        except Exception:  # pragma: no cover - fall back to single-replica memory
            logger.warning("Redis FSM storage unavailable, using in-memory storage")
    from aiogram.fsm.storage.memory import MemoryStorage

    return MemoryStorage()


dp = Dispatcher(storage=_build_fsm_storage())


def is_admin(telegram_id: int) -> bool:
    return telegram_id in settings.admin_users


def is_banned(user: User) -> bool:
    return bool(user.is_banned)


def _loc(user: User | None) -> str:
    return normalize_locale(getattr(user, "locale", None))


@dp.error()
async def on_error(event: ErrorEvent) -> bool:
    """Catch unhandled exceptions in handlers: log and keep the dispatcher alive."""
    logger.exception("Unhandled error in update handler", exc_info=event.exception)
    return True


async def ensure_user(msg: Message | CallbackQuery) -> User:
    tg = msg.from_user
    async with SessionLocal() as session:
        user = await get_or_create_user(session, tg.id, tg.username)
        # Persist so the user row exists before later handlers insert memes
        # (which reference owner_id in a fresh session). See FK violation fix.
        await session.commit()
        await session.refresh(user)
        return user


# ── FSM ──────────────────────────────────────────────────────────────────────

class CaptureMedia(StatesGroup):
    waiting_for_title = State()
    waiting_for_tags = State()
    waiting_for_nsfw = State()


# ── media extraction ──────────────────────────────────────────────────────────

def _extract_media(message: Message):
    m = message
    if m.photo:
        p = m.photo[-1]
        return p.file_id, p.file_unique_id, MediaType.PHOTO
    if m.animation:
        return m.animation.file_id, m.animation.file_unique_id, MediaType.ANIMATION
    if m.video:
        return m.video.file_id, m.video.file_unique_id, MediaType.VIDEO
    if m.voice:
        return m.voice.file_id, m.voice.file_unique_id, MediaType.VOICE
    if m.audio:
        return m.audio.file_id, m.audio.file_unique_id, MediaType.AUDIO
    if m.sticker:
        return m.sticker.file_id, m.sticker.file_unique_id, MediaType.STICKER
    return None


# ── /start /menu ───────────────────────────────────────────────────────────────

USER_COMMANDS = [
    BotCommand(command="start", description="Start / help"),
    BotCommand(command="find", description="Search your + public memes"),
    BotCommand(command="add", description="Reply to media to save to private pool"),
    BotCommand(command="suggest", description="Reply to media to propose to public pool"),
    BotCommand(command="mystatus", description="Your quota, trust & penalties"),
    BotCommand(command="language", description="Set UI language (en/fa)"),
    BotCommand(command="report", description="Report a public meme"),
    BotCommand(command="appeal", description="Appeal a removal"),
    BotCommand(command="policy", description="Show governance policy"),
    BotCommand(command="cancel", description="Cancel current operation"),
]
ADMIN_COMMANDS = [
    *USER_COMMANDS,
    BotCommand(command="admin", description="Admin: remove <id> <clause>"),
]


async def register_commands() -> None:
    if not settings.admin_users:
        await bot.set_my_commands(USER_COMMANDS)
        return
    await bot.set_my_commands(USER_COMMANDS)
    for admin_id in settings.admin_users:
        await bot.set_my_commands(
            ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=admin_id)
        )


@dp.message(Command("start"))
async def cmd_start(msg: Message):
    user = await ensure_user(msg)
    await msg.answer(
        t("start", _loc(user), bot=settings.bot_username or "yourbot"),
        parse_mode="HTML",
    )


@dp.message(Command("cancel"))
async def cmd_cancel(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer(t("cancelled", _loc(await ensure_user(msg))))


# ── /add & /suggest ─────────────────────────────────────────────────────────────

@dp.message(Command("add"))
async def cmd_add(msg: Message, state: FSMContext):
    if not msg.reply_to_message or not _extract_media(msg.reply_to_message):
        await msg.answer(t("add_reply_prompt", _loc(await ensure_user(msg))))
        return
    fid, fuid, mtype = _extract_media(msg.reply_to_message)
    await state.set_state(CaptureMedia.waiting_for_title)
    await state.update_data(file_id=fid, file_unique_id=fuid, media_type=mtype.value, target="private")
    await msg.answer(t("title_prompt", _loc(await ensure_user(msg))), parse_mode="HTML")


@dp.message(Command("suggest"))
async def cmd_suggest(msg: Message, state: FSMContext):
    user = await ensure_user(msg)
    if not settings.review_channel_id:
        await msg.answer(t("suggest_not_configured", _loc(user)))
        return
    if not msg.reply_to_message or not _extract_media(msg.reply_to_message):
        await msg.answer(t("suggest_reply_prompt", _loc(user)))
        return
    fid, fuid, mtype = _extract_media(msg.reply_to_message)
    await state.set_state(CaptureMedia.waiting_for_title)
    await state.update_data(file_id=fid, file_unique_id=fuid, media_type=mtype.value, target="public")
    await msg.answer(
        t("suggest_title_prompt", _loc(user)), parse_mode="HTML"
    )


@dp.message(CaptureMedia.waiting_for_title, F.text)
async def on_title(msg: Message, state: FSMContext):
    await state.update_data(title=msg.text.strip())
    await state.set_state(CaptureMedia.waiting_for_tags)
    await msg.answer(t("tags_prompt", _loc(await ensure_user(msg))), parse_mode="HTML")


@dp.message(CaptureMedia.waiting_for_tags, F.text)
async def on_tags(msg: Message, state: FSMContext):
    tags = [t.strip().lower() for t in msg.text.split(",") if t.strip()]
    if not tags:
        await msg.answer(t("tags_empty", _loc(await ensure_user(msg))))
        return
    await state.update_data(tags=tags)
    await state.set_state(CaptureMedia.waiting_for_nsfw)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Yes", callback_data="nsfw:yes"),
            InlineKeyboardButton(text="No", callback_data="nsfw:no"),
        ]
    ])
    await msg.answer(t("nsfw_prompt", _loc(await ensure_user(msg))), reply_markup=kb)


@dp.callback_query(CaptureMedia.waiting_for_nsfw, F.data.startswith("nsfw:"))
async def on_nsfw(callback: CallbackQuery, state: FSMContext):
    nsfw = callback.data.endswith("yes")
    data = await state.get_data()
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(t("working", _loc(await ensure_user(callback))))
    await _finalize_capture(callback.message, data, nsfw)


async def _finalize_capture(msg: Message, data: dict, nsfw: bool) -> None:
    user = await ensure_user(msg)
    loc = _loc(user)
    if is_banned(user):
        await msg.answer(t("banned", loc))
        return
    file_id = data["file_id"]
    mtype = MediaType(data["media_type"])
    target = data["target"]

    raw = await download_bytes(bot, file_id)
    if raw:
        file_hash = hashlib.sha256(raw).hexdigest()
    else:
        file_hash = f"tg:{data['file_unique_id']}"  # fallback fingerprint

    # §5.3: illegal-content hash match → block before anything is stored/public.
    async with SessionLocal() as session:
        if raw and await is_illegal_hash(session, file_hash):
            await notify_illegal_match(bot, user, file_hash)
            # Purge any pre-existing durable copy of this hash.
            if raw:
                await purge_media(key_for(mtype, file_hash))
            return

    storage_key = None
    if raw:
        storage_key = await store_media(bot, file_id, file_hash, mtype)

    async with SessionLocal() as session:
        if target == "public":
            existing = await find_public_by_hash(session, file_hash)
            if existing:
                await msg.answer(t("duplicate_public", loc))
                return
            meme = Meme(
                owner_id=user.id,
                visibility=Visibility.PENDING,
                media_type=mtype,
                telegram_file_id=file_id,
                file_hash=file_hash,
                title=data.get("title", ""),
                tags=data["tags"],
                nsfw=nsfw,
                storage_object_key=storage_key,
                source_chat_id=msg.chat.id,
            )
            session.add(meme)
            await session.flush()
            await session.commit()
            await open_submission(bot, session, meme, user, locale=loc)
            await msg.answer(t("submitted_public", loc))
            SUBMISSIONS_OPENED.inc()
            log_event(logger, "submission_opened", meme_id=str(meme.id), user=user.telegram_id)
        else:
            count, quota = await private_usage(session, user.id)
            if count >= quota:
                await msg.answer(
                    t("quota_reached", loc, count=count, quota=quota)
                )
                return
            meme = Meme(
                owner_id=user.id,
                visibility=Visibility.PRIVATE,
                media_type=mtype,
                telegram_file_id=file_id,
                file_hash=file_hash,
                title=data.get("title", ""),
                tags=data["tags"],
                nsfw=nsfw,
                storage_object_key=storage_key,
            )
            session.add(meme)
            await session.commit()
            log_event(logger, "private_meme_added", meme_id=str(meme.id), user=user.telegram_id)
            await msg.answer(
                t("saved_private", loc, count=count + 1, quota=quota,
                  tags=", ".join(data["tags"])),
                parse_mode="HTML",
            )


# ── /find (DM browse with buttons) ─────────────────────────────────────────────

class FindFlow(StatesGroup):
    pass


async def _render_find(
    target: Message | CallbackQuery, state: FSMContext, owner_id: int, locale: str
) -> None:
    data = await state.get_data()
    query = data.get("query", "")
    offset = int(data.get("offset", 0))
    results = await search(query, owner_id, include_nsfw=False, limit=8, offset=offset)
    if not results:
        text = t("find_no_results", locale, query=query) if query else t("no_memes", locale)
        if isinstance(target, CallbackQuery):
            await target.message.edit_text(text)
        else:
            await target.answer(text)
        return
    lines = []
    buttons = []
    for i, r in enumerate(results):
        rank = offset + i + 1
        lines.append(f"{rank}. {r['title'] or ', '.join(r['tags'])} "
                     f"<code>[{r['media_type']}]</code>")
        buttons.append([InlineKeyboardButton(
            text=t("send_button", locale, rank=rank), callback_data=f"send:{r['id']}:{rank}")])
    if len(results) == 8:
        buttons.append([InlineKeyboardButton(text=t("more_button", locale), callback_data=f"more:{offset + 8}")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    header = t("find_header_query", locale, query=query) if query else t("find_header_recent", locale)
    text = header + "\n" + "\n".join(lines)
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        await target.answer()
    else:
        await target.answer(text, parse_mode="HTML", reply_markup=kb)


@dp.message(Command("find"))
async def cmd_find(msg: Message, state: FSMContext):
    user = await ensure_user(msg)
    q = msg.text.replace("/find", "", 1).strip()
    await state.update_data(query=q, offset=0)
    await _render_find(msg, state, user.id, _loc(user))


@dp.callback_query(F.data.startswith("more:"))
async def on_more(callback: CallbackQuery, state: FSMContext):
    user = await ensure_user(callback)
    offset = int(callback.data.split(":", 1)[1])
    await state.update_data(offset=offset)
    await _render_find(callback, state, user.id, _loc(user))


@dp.callback_query(F.data.startswith("send:"))
async def on_send(callback: CallbackQuery, state: FSMContext):
    _, meme_id, rank = callback.data.split(":")
    rank = int(rank)
    user = await ensure_user(callback)
    loc = _loc(user)
    async with SessionLocal() as session:
        meme = await get_meme(session, meme_id)
        if not meme:
            await callback.answer(t("send_not_found", loc), show_alert=True)
            return
        if meme.visibility == Visibility.PRIVATE and meme.owner_id != user.id:
            await callback.answer(t("send_not_yours", loc), show_alert=True)
            return
        meme_dict = {
            "id": str(meme.id),
            "media_type": meme.media_type,
            "telegram_file_id": meme.telegram_file_id,
            "storage_object_key": meme.storage_object_key,
        }
        new_fid = await send_media(bot, callback.from_user.id, meme_dict)
        data = await state.get_data()
        await log_retrieval(session, meme.id, user.id, data.get("query", ""), rank)
        await session.commit()
    await callback.answer(t("sent", loc))


# ── inline mode ─────────────────────────────────────────────────────────────

@dp.inline_query()
async def inline_handler(query: InlineQuery):
    results = []
    try:
        logger.info("inline_query recv q=%r user=%s", query.query, query.from_user.id)
        user = await ensure_user(query)
        if is_banned(user):
            await query.answer([], cache_time=1)
            return
        allowed = await rate_limit(
            f"rl:inline:{user.telegram_id}", settings.inline_rate_per_min, 60
        )
        if not allowed:
            await query.answer([], cache_time=5)
            return

        results_raw = await search(
            query.query, user.id, include_nsfw=False, limit=50
        )
        INLINE_QUERIES.inc()
        for item in results_raw:
            rid = str(uuid.uuid4())
            label = item["title"] or ", ".join(item["tags"])
            mt = MediaType(item["media_type"])
            fid = item["telegram_file_id"]
            if mt == MediaType.PHOTO:
                results.append(InlineQueryResultCachedPhoto(id=rid, photo_file_id=fid, title=label))
            elif mt == MediaType.ANIMATION:
                results.append(InlineQueryResultCachedMpeg4Gif(id=rid, mpeg4_file_id=fid, title=label))
            elif mt == MediaType.VIDEO:
                results.append(InlineQueryResultCachedVideo(id=rid, video_file_id=fid, title=label, description=label))
            elif mt == MediaType.VOICE:
                results.append(InlineQueryResultCachedVoice(id=rid, voice_file_id=fid, title=label))
            elif mt == MediaType.AUDIO:
                results.append(InlineQueryResultCachedAudio(id=rid, audio_file_id=fid, title=label))
            elif mt == MediaType.STICKER:
                results.append(InlineQueryResultCachedSticker(id=rid, sticker_file_id=fid))

        if not results:
            results = [InlineQueryResultArticle(
                id="noop", title=t("inline_no_results_title", _loc(user)),
                input_message_content=InputTextMessageContent(message_text="—"),
                description=t("find_no_results", _loc(user), query=query.query),
            )]
            # Do not cache empty results, otherwise new memes stay hidden for the
            # full cache window and inline looks broken.
            await query.answer(results, cache_time=1, is_personal=True)
            return

        await query.answer(results, cache_time=settings.inline_cache_seconds, is_personal=True)
    except Exception:
        logger.exception("inline_handler error query=%r", query.query)
        if not results:
            try:
                await query.answer([], cache_time=1)
            except Exception:
                pass


# ── review-channel voting ───────────────────────────────────────────────────────

@dp.callback_query(F.data.startswith("vote:"))
async def on_vote(callback: CallbackQuery):
    _, sub_id, value = callback.data.split(":")
    user = await ensure_user(callback)
    loc = _loc(user)
    try:
        async with SessionLocal() as session:
            result = await cast_vote(
                bot, session, UUID(sub_id), user, VoteValue(value)
            )
        if result["status"] == "closed":
            await callback.answer(
                t("vote_counted_closed", loc, decision=result["decision"]), show_alert=True
            )
        else:
            await callback.answer(t("vote_counted", loc, net=result["net"]))
        VOTES_CAST.inc()
    except GovernanceError as e:
        await callback.answer(str(e), show_alert=True)


@dp.callback_query(F.data.startswith("rrev:"))
async def on_removal_review(callback: CallbackQuery):
    _, meme_id, decision = callback.data.split(":")
    user = await ensure_user(callback)
    if is_banned(user):
        await callback.answer(t("banned", _loc(user)), show_alert=True)
        return
    try:
        async with SessionLocal() as session:
            await cast_removal_review_vote(bot, session, UUID(meme_id), user, keep=(decision == "keep"))
        await callback.answer(t("removal_vote_counted", _loc(user)))
    except GovernanceError as e:
        await callback.answer(str(e), show_alert=True)


# ── /report ────────────────────────────────────────────────────────────────────

@dp.message(Command("report"))
async def cmd_report(msg: Message, state: FSMContext):
    loc = _loc(await ensure_user(msg))
    parts = msg.text.split(maxsplit=2)
    if len(parts) < 2:
        await msg.answer(t("report_usage", loc))
        return
    meme_id = parts[1].strip()
    reasons = [r for r in ReportReason]
    buttons = [
        [InlineKeyboardButton(text=r.value, callback_data=f"rep:{meme_id}:{r.value}")]
        for r in reasons
    ]
    await msg.answer(t("report_pick_reason", loc), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@dp.callback_query(F.data.startswith("rep:"))
async def on_report_reason(callback: CallbackQuery):
    _, meme_id, reason = callback.data.split(":", 2)
    user = await ensure_user(callback)
    loc = _loc(user)
    try:
        async with SessionLocal() as session:
            outcome = await file_report(
                bot, session, UUID(meme_id), user, ReportReason(reason)
            )
        if outcome == "removal_review_started":
            await callback.answer(t("report_threshold", loc), show_alert=True)
            REMOVAL_REVIEWS.inc()
        else:
            await callback.answer(t("report_recorded", loc), show_alert=True)
        REPORTS_FILED.inc()
        await callback.message.edit_reply_markup(reply_markup=None)
    except GovernanceError as e:
        await callback.answer(str(e), show_alert=True)


# ── /appeal ─────────────────────────────────────────────────────────────────────

@dp.message(Command("appeal"))
async def cmd_appeal(msg: Message):
    loc = _loc(await ensure_user(msg))
    parts = msg.text.split(maxsplit=2)
    if len(parts) < 3:
        await msg.answer(t("appeal_usage", loc))
        return
    meme_id = parts[1].strip()
    reason = parts[2].strip()
    user = await ensure_user(msg)
    try:
        async with SessionLocal() as session:
            outcome = await open_appeal(bot, session, UUID(meme_id), user, reason)
        await msg.answer(t("appeal_opened", loc))
    except GovernanceError as e:
        await msg.answer(str(e))


# ── /mystatus ───────────────────────────────────────────────────────────────────

@dp.message(Command("mystatus", "status"))
async def cmd_mystatus(msg: Message):
    from app.policy import vote_weight
    from sqlalchemy import func, select

    user = await ensure_user(msg)
    loc = _loc(user)
    async with SessionLocal() as session:
        count, quota = await private_usage(session, user.id)
        open_subs = await session.scalar(
            select(func.count())
            .select_from(Submission)
            .where(Submission.submitter_id == user.id, Submission.status == "open")
        )
        open_subs = open_subs or 0
    weight = vote_weight(user)
    penalty = t("penalty", loc) if user.trust_score < 50 else ""
    await msg.answer(
        t(
            "mystatus", loc,
            count=count, quota=quota, trust=user.trust_score, penalty=penalty,
            weight=weight, open_subs=open_subs,
            banned="yes" if user.is_banned else "no",
        ),
        parse_mode="HTML",
    )


# ── /language ─────────────────────────────────────────────────────────────────────

@dp.message(Command("language"))
async def cmd_language(msg: Message):
    user = await ensure_user(msg)
    loc = _loc(user)
    parts = msg.text.split(maxsplit=1)
    if len(parts) < 2:
        await msg.answer(t("language_current", loc, lang=user.locale))
        return
    new_loc = normalize_locale(parts[1].strip().lower())
    if new_loc not in SUPPORTED_LOCALES:
        await msg.answer(t("language_usage", loc))
        return
    async with SessionLocal() as session:
        u = await session.get(User, user.id)
        u.locale = new_loc
        await session.commit()
    await msg.answer(t("language_set", new_loc, lang=new_loc))


# ── /policy ──────────────────────────────────────────────────────────────────────

@dp.message(Command("policy"))
async def cmd_policy(msg: Message):
    from app.policy import DEFAULT_POLICY_VERSION

    loc = _loc(await ensure_user(msg))
    async with SessionLocal() as session:
        doc = await session.get(PolicyDocument, DEFAULT_POLICY_VERSION)
    body = doc.body if doc else t("policy_not_found", loc)
    # Send in chunks to respect Telegram message limits.
    for i in range(0, len(body), 4000):
        await msg.answer(body[i:i + 4000])


# ── /downvote (community downvote after the fact, spec §5.5.4) ──────────────────

@dp.message(Command("downvote"))
async def cmd_downvote(msg: Message):
    loc = _loc(await ensure_user(msg))
    parts = msg.text.split(maxsplit=1)
    if len(parts) < 2:
        await msg.answer(t("downvote_usage", loc))
        return
    user = await ensure_user(msg)
    try:
        async with SessionLocal() as session:
            outcome = await community_downvote(bot, session, UUID(parts[1].strip()), user)
        if outcome == "removal_review_started":
            await msg.answer(t("downvote_threshold", loc))
        else:
            await msg.answer(t("downvote_recorded", loc))
    except GovernanceError as e:
        await msg.answer(str(e))


# ── /removals (public anonymized audit log, spec §5.7) ──────────────────────────

@dp.message(Command("removals"))
async def cmd_removals(msg: Message):
    loc = _loc(await ensure_user(msg))
    async with SessionLocal() as session:
        rows = await recent_removal_cases(session, limit=20)
    if not rows:
        await msg.answer(t("removals_none", loc))
        return
    lines = []
    for r in rows:
        lines.append(
            f"• <code>{r['title']}</code> — {r['decision']} "
            f"<i>({r['clause']})</i> {r['created_at'][:10] if r['created_at'] else ''}"
        )
    await msg.answer(t("removals_header", loc) + "\n" + "\n".join(lines), parse_mode="HTML")


# ── admin blocklist / policy management ────────────────────────────────────────

@dp.message(Command("admin"))
async def cmd_admin(msg: Message):
    if not is_admin(msg.from_user.id):
        await msg.answer(t("not_authorized", _loc(await ensure_user(msg))))
        return
    loc = _loc(await ensure_user(msg))
    parts = msg.text.split(maxsplit=3)
    if len(parts) < 2:
        await msg.answer(t("admin_usage", loc))
        return
    sub = parts[1]
    user = await ensure_user(msg)

    if sub == "remove":
        if len(parts) < 4:
            await msg.answer(t("remove_usage", loc))
            return
        try:
            async with SessionLocal() as session:
                await admin_remove(bot, session, UUID(parts[2].strip()), user, parts[3].strip())
            await msg.answer(t("removed_admin", loc))
        except GovernanceError as e:
            await msg.answer(str(e))
        return

    if sub == "block":
        h = parts[2].strip() if len(parts) > 2 else ""
        if not h:
            await msg.answer(t("block_usage", loc))
            return
        async with SessionLocal() as session:
            await add_illegal_hash(session, h, note=f"by {user.telegram_id}")
            await session.commit()
        await msg.answer(t("blocklist_added", loc))
        return

    if sub == "unblock":
        h = parts[2].strip() if len(parts) > 2 else ""
        if not h:
            await msg.answer(t("unblock_usage", loc))
            return
        async with SessionLocal() as session:
            removed = await remove_illegal_hash(session, h)
            await session.commit()
        await msg.answer(t("blocklist_removed", loc) if removed else t("blocklist_not_found", loc))
        return

    if sub == "policy":
        body = parts[2] if len(parts) > 2 else ""
        if not body:
            await msg.answer(t("policy_usage", loc))
            return
        from app.policy import DEFAULT_POLICY_VERSION

        async with SessionLocal() as session:
            doc = await session.get(PolicyDocument, DEFAULT_POLICY_VERSION)
            if doc:
                doc.body = body
            else:
                doc = PolicyDocument(version=DEFAULT_POLICY_VERSION, body=body)
                session.add(doc)
            await session.commit()
        await msg.answer(t("policy_updated", loc, ver=DEFAULT_POLICY_VERSION))
        return

    await msg.answer(t("unknown_admin_sub", loc))


# ── main ─────────────────────────────────────────────────────────────────────────
# Orchestration (migrate, register commands, run loop, background jobs) lives in
# app/main.py so this module stays focused on handlers.

__all__ = ["bot", "dp", "is_admin"]

