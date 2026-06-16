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
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultCachedMpeg4Gif,
    InlineQueryResultCachedPhoto,
    InlineQueryResultCachedSticker,
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
ADMIN_USERS: set[int] = {
    int(uid.strip()) for uid in os.environ.get("ADMIN_USERS", "").split(",") if uid.strip()
}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


def is_allowed(user_id: int) -> bool:
    if user_id in ADMIN_USERS:
        return True
    return not ALLOWED_USERS or user_id in ALLOWED_USERS


def is_admin(user_id: int) -> bool:
    # If no ADMIN_USERS set, fall back to ALLOWED_USERS behaviour (backward compat)
    if ADMIN_USERS:
        return user_id in ADMIN_USERS
    return not ALLOWED_USERS or user_id in ALLOWED_USERS


class AddMedia(StatesGroup):
    waiting_for_keywords = State()


class EditMedia(StatesGroup):
    waiting_for_new_keywords = State()


# ── /start ───────────────────────────────────────────────────────────────────

@dp.message(Command("start"))
async def cmd_start(msg: Message):
    if not is_allowed(msg.from_user.id):
        return
    if is_admin(msg.from_user.id):
        await msg.answer(
            "Send me any <b>photo, GIF, video, voice, or sticker</b>.\n"
            "I'll ask you for keywords next.\n\n"
            "/list — show all saved memes\n"
            "/edit [search] — edit keywords of a meme\n"
            "/delete &lt;id&gt; — remove a meme by ID\n"
            "/cancel — cancel current operation",
            parse_mode="HTML",
        )
    else:
        await msg.answer(
            "Use me inline: type <code>@botname keyword</code> in any chat.\n\n"
            "/list — browse all saved memes",
            parse_mode="HTML",
        )


# ── /cancel ──────────────────────────────────────────────────────────────────

@dp.message(Command("cancel"))
async def cmd_cancel(msg: Message, state: FSMContext):
    if not is_allowed(msg.from_user.id):
        return
    await state.clear()
    await msg.answer("Cancelled.")


# ── step 1: receive media (admin only) ───────────────────────────────────────

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
    if not is_admin(msg.from_user.id):
        return
    photo = msg.photo[-1]
    await _receive_media(msg, state, photo.file_id, photo.file_unique_id, "photo")


@dp.message(F.animation, StateFilter(None))
async def on_gif(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id):
        return
    await _receive_media(msg, state, msg.animation.file_id, msg.animation.file_unique_id, "gif")


@dp.message(F.video, StateFilter(None))
async def on_video(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id):
        return
    await _receive_media(msg, state, msg.video.file_id, msg.video.file_unique_id, "video")


@dp.message(F.voice, StateFilter(None))
async def on_voice(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id):
        return
    await _receive_media(msg, state, msg.voice.file_id, msg.voice.file_unique_id, "voice")


@dp.message(F.sticker, StateFilter(None))
async def on_sticker(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id):
        return
    await _receive_media(msg, state, msg.sticker.file_id, msg.sticker.file_unique_id, "sticker")


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
    await msg.answer(f"Saved with keywords: <b>{', '.join(keywords)}</b>", parse_mode="HTML")


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


@dp.message(AddMedia.waiting_for_keywords, F.photo | F.animation | F.video | F.voice | F.sticker)
async def on_media_during_keywords(msg: Message):
    await msg.reply("Still waiting for keywords. Send /done to save the current item, or /cancel to discard.")


# ── /list ────────────────────────────────────────────────────────────────────

@dp.message(Command("list"))
async def cmd_list(msg: Message):
    if not is_allowed(msg.from_user.id):
        return
    items = await db.list_media()
    if not items:
        await msg.answer("No memes saved yet.")
        return
    lines = []
    for item in items[:30]:
        lines.append(f"<code>{item['id']}</code> [{item['media_type']}] — {item['keywords']}")
    text = "\n".join(lines)
    if len(items) > 30:
        text += f"\n…and {len(items) - 30} more."
    await msg.answer(text, parse_mode="HTML")


# ── /delete ──────────────────────────────────────────────────────────────────

@dp.message(Command("delete"))
async def cmd_delete(msg: Message):
    if not is_admin(msg.from_user.id):
        await msg.answer("Only admins can delete memes.")
        return
    parts = msg.text.split(maxsplit=1)
    if len(parts) < 2:
        await msg.answer("Usage: /delete &lt;id&gt; — use the numeric ID from /list", parse_mode="HTML")
        return
    try:
        media_id = int(parts[1].strip())
    except ValueError:
        await msg.answer("Invalid ID. Use the numeric ID from /list.")
        return
    removed = await db.delete_media(media_id)
    await msg.answer("Deleted." if removed else "Not found.")


# ── /edit ────────────────────────────────────────────────────────────────────

@dp.message(Command("edit"))
async def cmd_edit(msg: Message):
    if not is_admin(msg.from_user.id):
        await msg.answer("Only admins can edit memes.")
        return
    parts = msg.text.split(maxsplit=1)
    query = parts[1].strip() if len(parts) > 1 else ""
    items = await db.search_media(query)
    if not items:
        no_match = f" matching '{query}'" if query else ""
        await msg.answer(f"No memes found{no_match}.")
        return
    buttons = []
    for item in items[:10]:
        label = f"[{item['media_type']}] {item['keywords'][:45]}"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"edit:{item['id']}")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await msg.answer("Select a meme to edit its keywords:", reply_markup=keyboard)


@dp.callback_query(F.data.startswith("edit:"))
async def on_edit_select(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Not allowed.", show_alert=True)
        return
    media_id = int(callback.data.split(":", 1)[1])
    item = await db.get_media_by_id(media_id)
    if not item:
        await callback.answer("Meme not found.", show_alert=True)
        return
    await state.set_state(EditMedia.waiting_for_new_keywords)
    await state.update_data(media_id=media_id, keywords=[])
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"Editing <b>#{item['id']}</b> [{item['media_type']}]\n"
        f"Current keywords: <b>{item['keywords']}</b>\n\n"
        "Send the new keywords (comma-separated or one per message).\n"
        "Send /done when finished, or /cancel to abort.",
        parse_mode="HTML",
    )
    await callback.answer()


@dp.message(EditMedia.waiting_for_new_keywords, Command("done"))
async def cmd_edit_done(msg: Message, state: FSMContext):
    data = await state.get_data()
    keywords: list[str] = data.get("keywords", [])
    if not keywords:
        await msg.answer("You haven't entered any keywords yet. Send some, then /done.")
        return
    updated = await db.update_media_keywords(data["media_id"], keywords)
    await state.clear()
    if updated:
        await msg.answer(f"Updated keywords: <b>{', '.join(keywords)}</b>", parse_mode="HTML")
    else:
        await msg.answer("Failed to update (meme may have been deleted).")


@dp.message(EditMedia.waiting_for_new_keywords, Command("cancel"))
async def cmd_edit_cancel(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer("Edit cancelled.")


@dp.message(EditMedia.waiting_for_new_keywords, F.text)
async def on_edit_keyword(msg: Message, state: FSMContext):
    new_kws = [k.strip().lower() for k in msg.text.split(",") if k.strip()]
    if not new_kws:
        return
    data = await state.get_data()
    existing: list[str] = data.get("keywords", [])
    merged = existing + [k for k in new_kws if k not in existing]
    await state.update_data(keywords=merged)
    await msg.reply(f"Keywords so far: <b>{', '.join(merged)}</b>\nSend more or /done.", parse_mode="HTML")


# ── inline mode ──────────────────────────────────────────────────────────────

@dp.inline_query()
async def inline_handler(query: InlineQuery):
    if not is_allowed(query.from_user.id):
        await query.answer([], cache_time=1)
        return

    try:
        results_raw = await db.search_media(query.query)
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
            elif mtype == "sticker":
                results.append(InlineQueryResultCachedSticker(
                    id=rid, sticker_file_id=item["file_id"],
                ))

        if not results:
            results = [InlineQueryResultArticle(
                id="noop", title="No results found",
                input_message_content=InputTextMessageContent(message_text="—"),
                description=f"No memes matching '{query.query}'",
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
