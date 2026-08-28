"""Internationalization / localization for user-facing strings.

The DB `User.locale` column already exists (data-model §). This module is the
runtime half: a tiny key→template dictionary (no external deps) with English and
Persian translations. Handlers resolve the caller's locale and call ``t()``.

Missing keys fall back to English, so partially-translated locales still render.
"""

from __future__ import annotations

DEFAULT_LOCALE = "en"
SUPPORTED_LOCALES = ["en", "fa"]

EN = {
    "start": (
        "👋 <b>MemeBot</b>\n"
        "• Type <code>@{bot}</code> inline in any chat to search.\n"
        "• <code>/find &lt;keyword&gt;</code> to browse with buttons.\n"
        "• <code>/add</code> (reply to media) saves to your private pool.\n"
        "• <code>/suggest</code> (reply to media) proposes to the public pool.\n"
        "• <code>/policy</code> for governance rules. Use /language to switch."
    ),
    "find_no_results": "No memes found for “{query}”.",
    "no_memes": "No memes yet.",
    "add_reply_prompt": "Reply to a photo / GIF / video / voice / sticker with /add.",
    "suggest_reply_prompt": "Reply to a photo / GIF / video / voice / sticker with /suggest.",
    "suggest_not_configured": "Public suggestions are not configured (REVIEW_CHANNEL_ID missing).",
    "title_prompt": "Saving to your <b>private</b> pool. Send a short title.",
    "suggest_title_prompt": "Proposing to the <b>public</b> pool. Send a short title.",
    "tags_prompt": "Now send tags (comma-separated, e.g. <code>cat, surprised, funny</code>).",
    "tags_empty": "No tags detected. Send at least one, comma-separated.",
    "nsfw_prompt": "Is this meme NSFW? (affects visibility rules)",
    "working": "Working…",
    "saved_private": "💾 Saved to your private pool ({count}/{quota}). Tags: <b>{tags}</b>",
    "submitted_public": "✅ Submitted to the public pool! It will be voted on in the review channel.",
    "duplicate_public": "ℹ️ This media is already in the public pool — not creating a duplicate.",
    "quota_reached": "⚠️ Private quota reached ({count}/{quota}). Delete an old meme or /suggest it instead.",
    "banned": "You are banned.",
    "cancelled": "Cancelled.",
    "penalty": " (penalized)",
    "invalid_media": "Reply to a photo / GIF / video / voice / sticker with the command.",
    "mystatus": (
        "📊 <b>Your status</b>\n"
        "• Private pool: {count}/{quota}\n"
        "• Trust score: {trust}{penalty}\n"
        "• Vote weight: {weight}\n"
        "• Open submissions: {open_subs}\n"
        "• Banned: {banned}"
    ),
    "policy_not_found": "Policy not found.",
    "not_authorized": "Not authorized.",
    "admin_usage": "Usage: /admin &lt;remove|block|unblock|policy&gt; …",
    "remove_usage": "Usage: /admin remove &lt;meme_id&gt; &lt;policy clause&gt;",
    "block_usage": "Usage: /admin block &lt;sha256_hash&gt;",
    "unblock_usage": "Usage: /admin unblock &lt;sha256_hash&gt;",
    "policy_usage": "Usage: /admin policy &lt;new markdown body&gt;",
    "removed_admin": "Removed (admin manual).",
    "blocklist_added": "Blocklist entry added.",
    "blocklist_removed": "Blocklist entry removed.",
    "blocklist_not_found": "Not found.",
    "unknown_admin_sub": "Unknown admin subcommand.",
    "report_usage": "Usage: /report &lt;meme_id&gt; — a reason picker will appear.",
    "report_recorded": "Report recorded. Thank you.",
    "report_threshold": "Reported — threshold reached, removal review opened.",
    "appeal_usage": "Usage: /appeal &lt;meme_id&gt; &lt;reason&gt;",
    "appeal_opened": "📨 Appeal opened for admin review.",
    "downvote_usage": "Usage: /downvote &lt;meme_id&gt;",
    "downvote_recorded": "👎 Downvote recorded.",
    "downvote_threshold": "Downvote recorded — threshold reached, removal review opened.",
    "removals_none": "No removals recorded yet.",
    "removals_header": "🗂 <b>Recent removal cases</b>",
    "vote_counted": "Vote counted (net {net:.1f}).",
    "vote_counted_closed": "Vote counted — submission {decision}.",
    "removal_vote_counted": "Removal review vote counted.",
    "channel_submission_caption": (
        "🆕 New submission\nTitle: {title}\nTags: {tags}\nNSFW: {nsfw}\nBy: {by}"
    ),
    "channel_vote_help": "Vote with 👍 (approve) or 👎 (reject).",
    "channel_voting_progress": "Voting… net={net:.1f} 👍={up}",
    "channel_voting_closed": "Voting closed — net={net:.1f} 👍={up}: {verdict}",
    "channel_removal_caption": "🚨 Removal review for meme <code>{meme_id}</code> ({cause}). Vote keep / remove.",
    "channel_removal_closed": "Removal review closed — keep={keep} remove={remove}: {verdict}",
    "submission_approved": "✅ Your meme was approved and is now in the public pool!",
    "submission_rejected": "❌ Your submission was rejected (did not meet the public threshold). You may re-submit once after the cool-down.",
    "illegal_submitter": "Your submission was auto-rejected: it matched the illegal-content blocklist.",
    "language_set": "🌐 Language set to {lang}.",
    "language_current": "🌐 Current language: {lang}. Use /language &lt;en|fa&gt; to change.",
    "language_usage": "Usage: /language &lt;en|fa&gt;",
    "error_generic": "Something went wrong. Please try again later.",
}

FA = {
    "start": (
        "👋 <b>ممه‌بات</b>\n"
        "• در هر چت تایپ کنید <code>@{bot}</code> برای جستجوی اینلاین.\n"
        "• <code>/find &lt;کلمه&gt;</code> برای مرور با دکمه‌ها.\n"
        "• <code>/add</code> (ریپلای به مدیا) در حافظه خصوصی ذخیره می‌کند.\n"
        "• <code>/suggest</code> (ریپلای به مدیا) به حافظه عمومی پیشنهاد می‌دهد.\n"
        "• <code>/policy</code> برای قوانین حکمرانی. برای تغییر زبان از /language استفاده کنید."
    ),
    "find_no_results": "میمی برای «{query}» پیدا نشد.",
    "no_memes": "هنوز میمی وجود ندارد.",
    "add_reply_prompt": "ریپلای به عکس / GIF / ویدیو / ویس / استیکر با دستور /add.",
    "suggest_reply_prompt": "ریپلای به عکس / GIF / ویدیو / ویس / استیکر با دستور /suggest.",
    "suggest_not_configured": "پیشنهاد عمومی پیکربندی نشده است (REVIEW_CHANNEL_ID تنظیم نیست).",
    "title_prompt": "در حال ذخیره در حافظه <b>خصوصی</b>. یک عنوان کوتاه بفرستید.",
    "suggest_title_prompt": "در حال پیشنهاد به حافظه <b>عمومی</b>. یک عنوان کوتاه بفرستید.",
    "tags_prompt": "حالا برچسب‌ها را بفرستید (با کاما جدا شود، مثلاً <code>cat, surprised, funny</code>).",
    "tags_empty": "برچسبی تشخیص داده نشد. حداقل یک مورد با کاما بفرستید.",
    "nsfw_prompt": "آیا این میم NSFW است؟ (روی قوانین نمایش اثر می‌گذارد)",
    "working": "در حال انجام…",
    "saved_private": "💾 در حافظه خصوصی شما ذخیره شد ({count}/{quota}). برچسب‌ها: <b>{tags}</b>",
    "submitted_public": "✅ به حافظه عمومی پیشنهاد شد! در کانال بازبینی به رأی گذاشته می‌شود.",
    "duplicate_public": "ℹ️ این مدیا قبلاً در حافظه عمومی هست — تکرار ایجاد نمی‌شود.",
    "quota_reached": "⚠️ سهمیه خصوصی پر شده ({count}/{quota}). یک میم قدیمی را حذف کنید یا آن را /suggest کنید.",
    "banned": "شما مسدود شده‌اید.",
    "cancelled": "لغو شد.",
    "penalty": " (محروم)",
    "invalid_media": "ریپلای به عکس / GIF / ویدیو / ویس / استیکر با دستور مربوطه.",
    "mystatus": (
        "📊 <b>وضعیت شما</b>\n"
        "• حافظه خصوصی: {count}/{quota}\n"
        "• امتیاز اعتماد: {trust}{penalty}\n"
        "• وزن رأی: {weight}\n"
        "• پیشنهادهای باز: {open_subs}\n"
        "• مسدود: {banned}"
    ),
    "policy_not_found": "سیاست پیدا نشد.",
    "not_authorized": "مجاز نیستید.",
    "admin_usage": "کاربرد: /admin &lt;remove|block|unblock|policy&gt; …",
    "remove_usage": "کاربرد: /admin remove &lt;meme_id&gt; &lt;بند سیاست&gt;",
    "block_usage": "کاربرد: /admin block &lt;sha256_hash&gt;",
    "unblock_usage": "کاربرد: /admin unblock &lt;sha256_hash&gt;",
    "policy_usage": "کاربرد: /admin policy &lt;متن جدید&gt;",
    "removed_admin": "حذف شد (دستی توسط ادمین).",
    "blocklist_added": "ورودی لیست مسدودها اضافه شد.",
    "blocklist_removed": "ورودی لیست مسدودها حذف شد.",
    "blocklist_not_found": "پیدا نشد.",
    "unknown_admin_sub": "زیر‌دستور ادمین نامشخص.",
    "report_usage": "کاربرد: /report &lt;meme_id&gt; — منوی دلیل نمایش داده می‌شود.",
    "report_recorded": "گزارش ثبت شد. ممنون.",
    "report_threshold": "گزارش شد — آستانه رسید، بازبینی حذف باز شد.",
    "appeal_usage": "کاربرد: /appeal &lt;meme_id&gt; &lt;دلیل&gt;",
    "appeal_opened": "📨 درخواست تجدیدنظر برای بازبینی ادمین باز شد.",
    "downvote_usage": "کاربرد: /downvote &lt;meme_id&gt;",
    "downvote_recorded": "👎 رأی منفی ثبت شد.",
    "downvote_threshold": "رأی منفی ثبت شد — آستانه رسید، بازبینی حذف باز شد.",
    "removals_none": "هنوز حذفی ثبت نشده است.",
    "removals_header": "🗂 <b>موارد حذف اخیر</b>",
    "vote_counted": "رأی ثبت شد (تفاضل {net:.1f}).",
    "vote_counted_closed": "رأی ثبت شد — نتیجه: {decision}.",
    "removal_vote_counted": "رأی بازبینی حذف ثبت شد.",
    "channel_submission_caption": (
        "🆕 پیشنهاد جدید\nعنوان: {title}\nبرچسب‌ها: {tags}\nNSFW: {nsfw}\nتوسط: {by}"
    ),
    "channel_vote_help": "با 👍 (تأیید) یا 👎 (رد) رأی بدهید.",
    "channel_voting_progress": "رأی‌گیری… تفاضل={net:.1f} 👍={up}",
    "channel_voting_closed": "رأی‌گیری بسته شد — تفاضل={net:.1f} 👍={up}: {verdict}",
    "channel_removal_caption": "🚨 بازبینی حذف برای میم <code>{meme_id}</code> ({cause}). رأی نگه‌داشتن / حذف.",
    "channel_removal_closed": "بازبینی حذف بسته شد — نگه‌داشتن={keep} حذف={remove}: {verdict}",
    "submission_approved": "✅ میم شما تأیید شد و اکنون در حافظه عمومی است!",
    "submission_rejected": "❌ پیشنهاد شما رد شد (به آستانه عمومی نرسید). پس از زمان انتظار می‌توانید دوباره بفرستید.",
    "illegal_submitter": "پیشنهاد شما به‌طور خودکار رد شد: با لیست محتوای غیرمجاز تطبیق داشت.",
    "language_set": "🌐 زبان روی {lang} تنظیم شد.",
    "language_current": "🌐 زبان فعلی: {lang}. برای تغییر از /language &lt;en|fa&gt; استفاده کنید.",
    "language_usage": "کاربرد: /language &lt;en|fa&gt;",
    "error_generic": "خطایی رخ داد. لطفاً بعداً دوباره تلاش کنید.",
}

_TABLES = {"en": EN, "fa": FA}


def normalize_locale(locale: str | None) -> str:
    if locale in SUPPORTED_LOCALES:
        return locale
    return DEFAULT_LOCALE


def t(key: str, locale: str = DEFAULT_LOCALE, **kwargs) -> str:
    """Resolve a translation, falling back to English then to the key itself."""
    locale = normalize_locale(locale)
    template = _TABLES[locale].get(key) or EN.get(key, key)
    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return template
    return template
