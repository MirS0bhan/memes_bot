# Memes Bot

A personal Telegram inline bot to store and search media (photos, GIFs, videos, voice) by keywords.

[فارسی](README.fa.md)

---

### Requirements

- A server with [Docker](https://docs.docker.com/engine/install/) installed
- A Telegram bot token from [@BotFather](https://t.me/BotFather)

### Setup

**1. Create the bot in BotFather**
- `/newbot` → get your token
- `/setinline` → enable inline mode, set a placeholder (e.g. `Search memes...`)

**2. Find your Telegram user ID**

You need your numeric Telegram user ID to whitelist yourself.

- **Easiest:** forward any message to [@userinfobot](https://t.me/userinfobot) — it replies with your ID
- **Alternative:** open Telegram Web, click your profile, the number in the URL is your ID
- **For multiple users:** repeat for each person and separate IDs with commas

**3. Clone and configure**

```bash
git clone https://git.goyban.com/goyban/memes_bot
cd memes_bot
cp .env.example .env
```

Edit `.env`:

```env
BOT_TOKEN=your_telegram_bot_token_here
ALLOWED_USERS=123456789,987654321
```

**4. Run**

```bash
docker compose up -d --build
```

The database will be saved in `./bot_db/media.db`.

### Usage

**Adding media** — send the bot a photo, GIF, video, or voice message, then type keywords when prompted (comma-separated or one per message), then `/done`.

**Searching inline** — in any chat type `@yourbotusername keyword` to search and send.

Telegram suggests these commands as you type `/`, with a short description beside each suggestion.

**Commands**

| Command | Description |
|---|---|
| `/start` | Start the bot and show usage instructions |
| `/menu` | Show the available commands |
| `/list` | Show all saved media |
| `/edit [search]` | Select a meme and edit its keywords (admin only) |
| `/delete <id>` | Remove an entry (get ID from `/list`; admin only) |
| `/cancel` | Cancel current add operation |

### Moving to another server

The only files you need to transfer are:

- `.env`
- `bot_db/media.db`
