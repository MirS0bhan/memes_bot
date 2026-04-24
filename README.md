# Memes Bot

A personal Telegram inline bot to store and search media (photos, GIFs, videos, voice) by keywords.

---

## English

### Requirements

- A server with [Docker](https://docs.docker.com/engine/install/) installed
- A Telegram bot token from [@BotFather](https://t.me/BotFather)

### Setup

**1. Create the bot in BotFather**
- `/newbot` → get your token
- `/setinline` → enable inline mode, set a placeholder (e.g. `Search memes...`)

**2. Get your Telegram user ID**

Send a message to [@userinfobot](https://t.me/userinfobot) to find your numeric user ID.

**3. Clone and configure**

```bash
git clone https://git.goyban.space/goyban/memes_bot
cd memes_bot
cp .env.example .env
```

Edit `.env`:

```env
BOT_TOKEN=your_telegram_bot_token_here
ALLOWED_USERS=123456789
```

`ALLOWED_USERS` is a comma-separated list of Telegram user IDs allowed to use the bot.

**4. Run**

```bash
docker compose up -d --build
```

The database will be saved in `./bot_db/media.db`.

### Usage

**Adding media** — send the bot a photo, GIF, video, or voice message, then type keywords when prompted (comma-separated or one per message), then `/done`.

**Searching inline** — in any chat type `@yourbotusername keyword` to search and send.

**Commands**

| Command | Description |
|---|---|
| `/list` | Show all saved media |
| `/delete <id>` | Remove an entry (get ID from `/list`) |
| `/cancel` | Cancel current add operation |

### Moving to another server

The only files you need to transfer are:

- `.env`
- `bot_db/media.db`

---

## فارسی

### پیش‌نیازها

- یک سرور با [Docker](https://docs.docker.com/engine/install/) نصب‌شده
- توکن ربات تلگرام از [@BotFather](https://t.me/BotFather)

### راه‌اندازی

**۱. ساخت ربات در BotFather**
- `/newbot` ← توکن بگیرید
- `/setinline` ← حالت اینلاین را فعال کنید (مثلاً: `جستجوی میم...`)

**۲. دریافت شناسه تلگرام**

یک پیام به [@userinfobot](https://t.me/userinfobot) بفرستید تا ID عددی‌تان را بگیرید.

**۳. کلون و تنظیم**

```bash
git clone https://git.goyban.space/goyban/memes_bot
cd memes_bot
cp .env.example .env
```

فایل `.env` را ویرایش کنید:

```env
BOT_TOKEN=توکن_ربات_شما
ALLOWED_USERS=123456789
```

`ALLOWED_USERS` لیستی از شناسه‌های تلگرامی است که اجازه استفاده دارند (با کاما جدا کنید).

**۴. اجرا**

```bash
docker compose up -d --build
```

دیتابیس در مسیر `./bot_db/media.db` ذخیره می‌شود.

### نحوه استفاده

**افزودن میم** — یک عکس، گیف، ویدیو یا صدا برای ربات بفرستید. ربات از شما کلیدواژه می‌خواهد. کلیدواژه‌ها را یکی‌یکی یا با کاما جدا بفرستید، سپس `/done` بزنید.

**جستجوی اینلاین** — در هر چتی بنویسید `@نام_ربات کلیدواژه` تا نتایج نمایش داده شود.

**دستورات**

| دستور | توضیح |
|---|---|
| `/list` | نمایش همه رسانه‌های ذخیره‌شده |
| `/delete <id>` | حذف یک مورد (ID را از `/list` بگیرید) |
| `/cancel` | لغو عملیات جاری |

### انتقال به سرور دیگر

فقط کافی است این دو فایل را منتقل کنید:

- `.env`
- `bot_db/media.db`
