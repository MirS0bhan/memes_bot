# Deployment (spec §7.4)

12-factor: every threshold and credential is an environment variable. Copy
`.env.example` to `.env` and fill in. The compose file brings Postgres, Redis,
and the bot.

## Docker Compose (default)

The `bot` service pulls a prebuilt image from GHCR (produced by the CI workflow).
Set `MEMEBOT_IMAGE` to your registry path, e.g.:

```bash
export MEMEBOT_IMAGE=ghcr.io/<your-org>/<your-repo>:main
cp .env.example .env
# edit: BOT_TOKEN, BOT_USERNAME, ADMIN_USERS, REVIEW_CHANNEL_ID
docker compose up -d
```

To build locally instead, replace `image:` with `build: .` under `bot` in
`docker-compose.yml` (or `docker compose up -d --build`).

`docker-compose.yml` starts `postgres`, `redis`, and `bot` (`ROLE=both`). For
scale, split roles:

```bash
ROLE=web MEMEBOT_IMAGE=ghcr.io/<org>/<repo>:main docker compose up -d --scale bot=3   # webhook replicas
ROLE=worker MEMEBOT_IMAGE=ghcr.io/<org>/<repo>:main docker compose run --rm bot       # scheduler only
```

## Key environment variables

### Core
| Var | Default | Purpose |
|---|---|---|
| `BOT_TOKEN` | — | Telegram bot token (required) |
| `BOT_USERNAME` | — | for inline help text |
| `DATABASE_URL` | `postgresql+asyncpg://memebot:memebot@postgres:5432/memebot` | asyncpg DSN |
| `REDIS_URL` | `redis://redis:6379/0` | rate limit, FSM, caches |
| `ROLE` | `both` | `web` / `worker` / `both` |
| `WEBHOOK_URL` | empty | if set → webhook mode; else long polling |
| `WEBHOOK_PATH` | `/webhook` | |
| `WEBHOOK_SECRET` | empty | `X-Telegram-Bot-Api-Secret-Token` |
| `LISTEN_HOST` / `LISTEN_PORT` | `0.0.0.0:8080` | webhook bind |
| `METRICS_PORT` | `9090` | Prometheus `/metrics` bind |

### Public pool / voting (§5.2)
`VOTE_WINDOW_HOURS=48`, `APPROVE_NET_SCORE=10`, `APPROVE_MIN_UPVOTES=5`,
`REJECT_NET_SCORE=-5`, `NSFW_APPROVE_NET_SCORE=20`, `RESUBMIT_COOLDOWN_DAYS=30`.

### Removal (§5.5)
`REPORT_THRESHOLD=5`, `REPORT_WINDOW_HOURS=72`, `REVIEW_VOTE_WINDOW_HOURS=24`,
`APPEAL_WINDOW_DAYS=7`, `COMMUNITY_DOWNVOTE_THRESHOLD=20`.

### Trust / weighting (§5.4)
`NEW_ACCOUNT_AGE_DAYS=1`, `NEW_ACCOUNT_WEIGHT=0.5`, `ESTABLISHED_WEIGHT=1.0`,
`PENALIZED_WEIGHT=0.25`, `ESTABLISHED_AGE_DAYS=30`.

### Private pool / search / abuse
`DEFAULT_PRIVATE_QUOTA=200`; `RANK_TEXT_WEIGHT=1.0`,
`RANK_POPULARITY_WEIGHT=0.3`, `RANK_RECENCY_WEIGHT=0.2`, `RANK_REPORT_PENALTY=0.5`;
`INLINE_RATE_PER_MIN=20`, `SUGGEST_RATE_PER_HOUR=10`, `REPORT_RATE_PER_HOUR=20`.

### Storage (§6.2)
`S3_ENDPOINT_URL`, `S3_BUCKET`, `S3_REGION`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`
(leave empty → local filesystem at `STORAGE_PATH`). `ILLEGAL_HASHES` seeds the
blocklist.

### Admins
`ADMIN_USERS` — comma-separated Telegram ids; unlocks `/admin *` and the admin
command set.

## Migrations
`app/migrate.py` runs on every start: creates the schema (via SQLAlchemy
metadata), enables `pg_trgm`, adds the GIN/FTS indexes, seeds the policy
document, and seeds `ILLEGAL_HASHES`. Idempotent.

## Scaling & HA notes
- **Stateless**: any `web` replica handles any update. Scale on CPU/request-rate.
- **FSM**: use Redis storage (automatic when `REDIS_URL` set) for multi-replica.
- **DB**: managed Postgres with connection pooling; `pool_size`/`max_overflow`
  tuned in `app/db.py`.
- **Back-pressure**: webhook + queue; circuit-break on Telegram 429 (retry/queue).
- **Observability**: scrape `:METRICS_PORT/metrics`; ship JSON logs to your
  log backend.

## Known limitations (v1)
- **Semantic/embedding search** (§6.1 v2) is intentionally out of scope.
- **Per-chat NSFW opt-in** (Open Question #1) is v2; NSFW is excluded from
  default results today.
- **Illegal-content hash list** must be supplied (env or `/admin block`); the
  auto-reject *mechanism* exists, the *list* is operational data.
- **Postgres/Redis/Telegram** are required for a live run; the build sandbox
  validates imports + unit tests only.
- Secrets must never be committed; use your deploy target's secret store.
