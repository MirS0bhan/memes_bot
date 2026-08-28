# MemeBot — Community-Curated Meme Retrieval Bot for Telegram

MemeBot is a Telegram bot that retrieves memes by natural-language keywords from
two pools:

- **Private pool** — memes you save yourself (per-user, quota-capped).
- **Public pool** — community-curated memes that pass a public vote in a review
  channel. Submissions, removals, appeals, and illegal-content handling all run
  through a transparent, audited governance pipeline.

Results are returned both **in chat** (`/find`) and via **inline mode**
(`@YourBot <query>` in any chat). Media is mirrored from Telegram once and sent
by cached `file_id` with automatic re-upload if a file id goes stale.

> Cloud-native: a stateless bot process, Postgres as the system of record, Redis
> for rate limiting / FSM / caches, and optional S3-compatible storage as a
> durable media fallback.

A Persian version of this document is available in [`README.fa.md`](README.fa.md).
Detailed design docs live in [`docs/`](docs/README.md).

---

## Features

- **Private pool** — `/add` saves media to your own pool, with quota enforcement.
- **Inline & in-chat search** — keyword + tag search over public and your private memes.
- **Tiered ranking** — tag-overlap + full-text search + `pg_trgm` fuzzy match,
  with a tunable blend of popularity and recency.
- **Community curation** — `/suggest` opens a public submission that is voted on
  in a review channel before it enters the public pool.
- **Governance** — report → removal-review → appeals pipeline, admin/legal
  removal, community downvote, and an illegal-content hash blocklist.
- **Transparency** — `/policy`, `/mystatus`, `/removals`, and a versioned policy doc.
- **Production hygiene** — Redis-backed FSM, Prometheus `/metrics`, structured
  JSON logs, and per-action rate limiting.

---

## Architecture

```
┌────────────┐   updates    ┌────────────────────┐
│ Telegram   │ ───────────▶ │  MemeBot (ROLE=*)   │
└────────────┘              │  - handlers/FSM     │
                           │  - search           │
                           └──────────┬─────────┘
                  ┌──────────────────┼──────────────────┐
                  ▼                  ▼                  ▼
           ┌────────────┐   ┌──────────────┐   ┌──────────────┐
           │  Postgres  │   │    Redis     │   │ S3 / storage │
           │ (record)   │   │(rate/FSM/cache)│  │ (media blob) │
           └────────────┘   └──────────────┘   └──────────────┘
```

| Role (`ROLE`) | Responsibility |
|---|---|
| `web`    | Receives Telegram updates (polling or webhook) and serves `/metrics`. |
| `worker` | Runs scheduled jobs (vote closing, report windows, appeals expiry). |
| `both`   | Runs everything in a single process (default for `docker compose`). |

See [`docs/architecture.md`](docs/architecture.md) for the full component
breakdown, [`docs/data-model.md`](docs/data-model.md) for entities and the
state machine, and [`docs/search.md`](docs/search.md) for ranking details.

---

## Quick start

Requirements: Docker + Docker Compose, and a Telegram bot token from
[@BotFather](https://t.me/BotFather).

```bash
cp .env.example .env
# Edit .env and set at least: BOT_TOKEN, BOT_USERNAME, ADMIN_USERS, REVIEW_CHANNEL_ID
docker compose up -d --build
```

This starts Postgres, Redis, and the bot (`ROLE=both`). Watch the logs:

```bash
docker compose logs -f bot
```

On first run the bot auto-applies database migrations, then starts long polling
(or serves a webhook if `WEBHOOK_URL` is set).

> **Inline mode won't return anything until** (a) inline mode is enabled for the
> bot in BotFather, and (b) there is at least one public meme in the database.
> Empty results are cached for only ~1s, so new memes appear immediately.

For larger deployments, run `ROLE=web` replicas behind a load balancer and a
separate `ROLE=worker` for scheduled jobs. See
[`docs/deployment.md`](docs/deployment.md).

---

## Configuration

All configuration is via environment variables (see `.env.example`). Key groups:

| Variable | Purpose |
|---|---|
| `BOT_TOKEN`, `BOT_USERNAME` | Telegram credentials from BotFather. |
| `ROLE` | `web` \| `worker` \| `both`. |
| `WEBHOOK_URL` | If set (https), run in webhook mode; otherwise long polling. |
| `DATABASE_URL` | Postgres DSN (`postgresql+asyncpg://…`). |
| `REDIS_URL` | Redis for FSM / rate limits / caches. |
| `ADMIN_USERS` | Comma-separated Telegram ids with admin powers. |
| `REVIEW_CHANNEL_ID` | Channel/group where public submissions are voted. |
| `DEFAULT_PRIVATE_QUOTA` | Max memes per user in the private pool. |
| `VOTE_WINDOW_HOURS`, `APPROVE_NET_SCORE`, `APPROVE_MIN_UPVOTES`, … | Public voting thresholds (§5.2). |
| `REPORT_THRESHOLD`, `REVIEW_VOTE_WINDOW_HOURS`, `APPEAL_WINDOW_DAYS` | Removal policy (§5.5). |
| `RANK_*_WEIGHT` | Search ranking blend. |
| `INLINE_RATE_PER_MIN`, `SUGGEST_RATE_PER_HOUR`, `REPORT_RATE_PER_HOUR` | Rate limits. |
| `S3_ENDPOINT_URL`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` | Optional S3 media fallback. |
| `ILLEGAL_HASHES` | Comma-separated SHA-256 blocklist. |
| `METRICS_PORT`, `LOG_LEVEL`, `INLINE_CACHE_SECONDS` | Observability / caching. |

---

## Commands

| Command / interaction | Scope | Effect |
|---|---|---|
| inline `@YourBot <query>` | any chat | search public + your private pool, return media |
| `/find <query>` | DM | same search with buttons + "More" pagination |
| `/add` (reply to media) | DM | save to **private** pool (quota enforced) |
| `/suggest` (reply to media) | DM | open a **public** submission → review vote |
| `/mystatus` | DM | quota, trust score, open submissions, penalties |
| `/report <meme_id>` | DM | reason picker → feeds removal policy |
| `/downvote <meme_id>` | DM | community downvote |
| `/appeal <meme_id> <reason>` | DM | appeal a removal |
| `/language <en\|fa>` | DM | switch UI language (i18n/l10n) |
| `/status` | DM | alias of `/mystatus` |
| `/policy` | DM | current governance policy text |
| `/removals` | DM | public, anonymized removal audit log |
| review-channel 👍/👎 | channel | vote on an open submission |
| review-channel Keep/Remove | channel | removal-review vote |
| `/admin remove <id> <clause>` | admin | manual removal (requires policy clause) |
| `/admin block <hash>` / `unblock <hash>` | admin | manage illegal-content blocklist |
| `/admin policy <body>` | admin | bump the versioned policy document |

Full interaction flows are documented in [`docs/commands.md`](docs/commands.md)
and governance rules in [`docs/governance.md`](docs/governance.md).

---

## Development & testing

```bash
uv venv && uv pip install -r requirements.txt
pytest -q
```

The test suite covers the store-once media contract (§6.2) and the governance
policy math (§5.2 / §5.4). A live end-to-end run additionally needs Postgres,
Redis, and a real Telegram token.

Run locally without Docker:

```bash
export ROLE=both
uv run python -m app.main        # or: uvicorn app.main:app ... for webhook/web
```

---

## Observability

- **Metrics**: Prometheus scrape endpoint at `http://<host>:<METRICS_PORT>/metrics`
  (default `9090`). Tracks inline queries, retrievals, vote events, and more.
- **Logs**: structured JSON to stdout. Filter by `logger`, `level`, or the
  `event` field.

---

## Documentation

- [Architecture](docs/architecture.md)
- [Data model](docs/data-model.md)
- [Governance](docs/governance.md)
- [Search](docs/search.md)
- [Commands](docs/commands.md)
- [Deployment](docs/deployment.md)
