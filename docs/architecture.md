# Architecture (spec §7)

MemeBot is built cloud-native from day one: a **stateless** bot process, a
**Postgres** system of record, **Redis** for rate limiting / caches / FSM, and
optional **S3-compatible** object storage as a durable media fallback.

## Components

```
                         ┌────────────────────┐
 Telegram servers  ───►  │  Webhook Ingress     │  (aiohttp, TLS-terminated at LB)
 (webhook push)          └─────────┬───────────┘
                                    │
                          ┌─────────▼──────────┐
                          │  Bot API Service     │  stateless, horizontally scaled
                          │  (aiogram + aiohttp) │  - validates Telegram secret token
                          │                      │  - fast ack, enqueues work
                          └───┬───────────┬──────┘
                              │           │
                    ┌─────────▼───┐   ┌───▼─────────────┐
                    │  Postgres    │   │  Redis           │
                    │ (memes,      │   │ - rate limiting  │
                    │  users,      │   │ - inline cache   │
                    │  votes,      │   │ - FSM state      │
                    │  reports,    │   │ - removal tallies│
                    │  audit)      │   └──────────────────┘
                    └──────────────┘
                              │
                    ┌─────────▼──────────┐
                    │  Async jobs          │  - close expired vote windows
                    │  (scheduler loop)    │  - close removal reviews
                    └─────────┬────────────┘
                              │
                    ┌─────────▼──────────┐
                    │  S3-compatible       │  durable media, keyed by file_hash
                    │  object storage      │  (self-heals stale file_ids)
                    └────────────────────┘
```

## Runtime roles (`ROLE` env)

| Role | Responsibility |
|---|---|
| `web` | Serve webhook (or long-poll) updates only |
| `worker` | Run the background scheduler (`app/jobs.py`) only |
| `both` | Both in a single process (default, simplest for modest load) |

For real scale, run `ROLE=web` replicas behind an L7 load balancer and one or
more `ROLE=worker` containers.

## Webhook vs long polling (§7.2)

- **Webhook** (production): `WEBHOOK_URL` is set → the bot runs an aiohttp server
  on `LISTEN_HOST:LISTEN_PORT` at `WEBHOOK_PATH`, verifies the
  `X-Telegram-Bot-Api-Secret-Token` header, and feeds updates via
  `dp.feed_update`. Stateless and horizontally scalable.
- **Long polling** (dev / no public URL): `WEBHOOK_URL` empty → `dp.start_polling`.

Webhook is preferred at scale because any replica can accept any request and you
get natural back-pressure via the queue, unlike a single `getUpdates` loop.

## FSM storage

Conversation state (`/add`, `/suggest`, `/find`) uses `RedisStorage`
(`aiogram.fsm.storage.redis`) when `REDIS_URL` is configured, falling back to
in-memory `MemoryStorage` for single-replica/dev. Redis FSM is required for
correct behavior when running multiple `web` replicas.

## Durable media store (§6.2)

`app/storage.py` mirrors each meme from Telegram to durable storage **once** at
ingest (`store_media`). `send_media` then sends by the cached `telegram_file_id`
and only re-uploads from durable storage if Telegram reports the id as stale
(self-healing cache). Backends: S3-compatible (when `S3_*` set) or local
filesystem (`STORAGE_PATH`, default) otherwise.

## Observability (§7.5)

- **Structured JSON logs** for every state transition (submission opened, vote
  cast, removal case created, …) — these form the governance audit trail.
- **Prometheus metrics** served at `GET /metrics` on `METRICS_PORT`:
  `memebot_update_latency_seconds`, `memebot_inline_queries_total`,
  `memebot_submissions_opened_total`, `memebot_votes_cast_total`,
  `memebot_reports_filed_total`, `memebot_removal_reviews_total`,
  `memebot_errors_total`.
- An update outer-middleware records latency and error counts automatically.

## Abuse controls (§7.6)

Per-user fixed-window counters in Redis: inline queries, `/suggest`, `/report`.
Global back-pressure is provided by the queue/webhook model.
