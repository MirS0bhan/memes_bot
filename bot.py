import asyncio
import logging
import os
import uuid

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineQuery,
    InlineQueryResultCachedMpeg4Gif,
    InlineQueryResultCachedPhoto,
    InlineQueryResultCachedVideo,
    InlineQueryResultCachedVoice,
    InlineQueryResultArticle,
    InputTextMessageContent,
    Message,
)

import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]
ALLOWED_USERS: set[int] = {
    int(uid.strip()) for uid in os.environ.get("ALLOWED_USERS", "").split(",") if uid.strip()
}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


def is_allowed(user_id: int) -> bool:
    return not ALLOWED_USERS or user_id in ALLOWED_USERS


class AddMedia(StatesGroup):
    waiting_for_keywords = State()


# ── /start ───────────────────────────────────────────────────────────────────

@dp.message(Command("start"))
async def cmd_start(msg: Message):
    if not is_allowed(msg.from_user.id):
        return
    await msg.answer(
        "Send me any <b>photo, GIF, video, or voice</b>.\n"
        "I'll ask you for keywords next.\n\n"
        "/list — show all saved media\n"
        "/delete &lt;file_unique_id&gt; — remove an entry\n"
        "/cancel — cancel current operation",
        parse_mode="HTML",
    )


# ── /cancel ──────────────────────────────────────────────────────────────────

@dp.message(Command("cancel"))
async def cmd_cancel(msg: Message, state: FSMContext):
    if not is_allowed(msg.from_user.id):
        return
    await state.clear()
    await msg.answer("Cancelled.")


# ── step 1: receive media ────────────────────────────────────────────────────

async def _receive_media(msg: Message, state: FSMContext, file_id: str, file_unique_id: str, media_type: str):
    await state.set_state(AddMedia.waiting_for_keywords)
    await state.update_data(
        file_id=file_id,
        file_unique_id=file_unique_id,
        media_type=media_type,
        keywords=[],
    )
    await msg.reply(
        "Got it! Now send keywords — one per message or comma-separated.\n"
        "Send /done when finished.",
        parse_mode="HTML",
    )


@dp.message(F.photo, StateFilter(None))
async def on_photo(msg: Message, state: FSMContext):
    if not is_allowed(msg.from_user.id):
        return
    photo = msg.photo[-1]
    await _receive_media(msg, state, photo.file_id, photo.file_unique_id, "photo")


@dp.message(F.animation, StateFilter(None))
async def on_gif(msg: Message, state: FSMContext):
    if not is_allowed(msg.from_user.id):
        return
    await _receive_media(msg, state, msg.animation.file_id, msg.animation.file_unique_id, "gif")


@dp.message(F.video, StateFilter(None))
async def on_video(msg: Message, state: FSMContext):
    if not is_allowed(msg.from_user.id):
        return
    await _receive_media(msg, state, msg.video.file_id, msg.video.file_unique_id, "video")


@dp.message(F.voice, StateFilter(None))
async def on_voice(msg: Message, state: FSMContext):
    if not is_allowed(msg.from_user.id):
        return
    await _receive_media(msg, state, msg.voice.file_id, msg.voice.file_unique_id, "voice")


# ── step 2: collect keywords ─────────────────────────────────────────────────

@dp.message(AddMedia.waiting_for_keywords, Command("done"))
async def cmd_done(msg: Message, state: FSMContext):
    data = await state.get_data()
    keywords: list[str] = data.get("keywords", [])
    if not keywords:
        await msg.answer("You haven't added any keywords yet. Send some, then /done.")
        return
    await db.add_media(
        msg.from_user.id,
        data["file_id"],
        data["file_unique_id"],
        data["media_type"],
        keywords,
    )
    await state.clear()
    kw_display = ", ".join(keywords)
    await msg.answer(f"Saved with keywords: <b>{kw_display}</b>", parse_mode="HTML")


@dp.message(AddMedia.waiting_for_keywords, F.text)
async def on_keyword(msg: Message, state: FSMContext):
    new_kws = [k.strip().lower() for k in msg.text.split(",") if k.strip()]
    if not new_kws:
        return
    data = await state.get_data()
    existing: list[str] = data.get("keywords", [])
    merged = existing + [k for k in new_kws if k not in existing]
    await state.update_data(keywords=merged)
    await msg.reply(f"Keywords so far: <b>{', '.join(merged)}</b>\nSend more or /done.", parse_mode="HTML")


# handle media sent while already in keyword-collection state
@dp.message(AddMedia.waiting_for_keywords, F.photo | F.animation | F.video | F.voice)
async def on_media_during_keywords(msg: Message):
    await msg.reply("Still waiting for keywords. Send /done first to save the current item, or /cancel to discard.")


# ── /list & /delete ──────────────────────────────────────────────────────────

@dp.message(Command("list"))
async def cmd_list(msg: Message):
    if not is_allowed(msg.from_user.id):
        return
    items = await db.list_media(msg.from_user.id)
    if not items:
        await msg.answer("No media saved yet.")
        return
    lines = []
    for item in items[:30]:
        lines.append(f"<code>{item['file_unique_id']}</code> [{item['media_type']}] — {item['keywords']}")
    text = "\n".join(lines)
    if len(items) > 30:
        text += f"\n…and {len(items) - 30} more."
    await msg.answer(text, parse_mode="HTML")


@dp.message(Command("delete"))
async def cmd_delete(msg: Message):
    if not is_allowed(msg.from_user.id):
        return
    parts = msg.text.split(maxsplit=1)
    if len(parts) < 2:
        await msg.answer("Usage: /delete &lt;file_unique_id&gt;", parse_mode="HTML")
        return
    removed = await db.delete_media(msg.from_user.id, parts[1].strip())
    await msg.answer("Deleted." if removed else "Not found or not yours.")


# ── inline mode ──────────────────────────────────────────────────────────────

@dp.inline_query()
async def inline_handler(query: InlineQuery):
    if not is_allowed(query.from_user.id):
        await query.answer([], cache_time=1)
        return

    try:
        results_raw = await db.search_media(query.from_user.id, query.query)
        results = []

        for item in results_raw:
            rid = str(uuid.uuid4())
            kw_display = item["keywords"].replace(",", ", ")
            mtype = item["media_type"]

            if mtype == "photo":
                results.append(InlineQueryResultCachedPhoto(
                    id=rid, photo_file_id=item["file_id"],
                    title=kw_display, description=kw_display,
                ))
            elif mtype == "gif":
                # Telegram animations are MPEG4, not raw GIF
                results.append(InlineQueryResultCachedMpeg4Gif(
                    id=rid, mpeg4_file_id=item["file_id"], title=kw_display,
                ))
            elif mtype == "video":
                results.append(InlineQueryResultCachedVideo(
                    id=rid, video_file_id=item["file_id"],
                    title=kw_display, description=kw_display,
                ))
            elif mtype == "voice":
                results.append(InlineQueryResultCachedVoice(
                    id=rid, voice_file_id=item["file_id"], title=kw_display,
                ))

        if not results:
            results = [InlineQueryResultArticle(
                id="noop", title="No results found",
                input_message_content=InputTextMessageContent(message_text="—"),
                description=f"No media matching '{query.query}'",
            )]

        await query.answer(results, cache_time=5, is_personal=True)

    except Exception:
        log.exception("inline_handler error for user %s query %r", query.from_user.id, query.query)
        await query.answer([], cache_time=1)


# ── main ─────────────────────────────────────────────────────────────────────

async def main():
    await db.init_db()
    log.info("Bot starting…")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
