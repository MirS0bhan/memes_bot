# MemeBot — Community-Curated Meme Retrieval Bot for Telegram (v1)

A Telegram bot that retrieves memes by natural keywords from a **private** pool
(per-user, quota-capped) and a **public** pool (community-curated via voting in a
review channel). Public additions pass through a public vote; removals follow an
explicit published policy; everything is observable and audit-logged.

> Implemented per the spec milestone order (§10). Cloud-native: stateless bot
> process, Postgres system of record, Redis for rate limiting / FSM / caches,
> optional S3-compatible object storage as a durable media fallback.

## Documentation

Full, separated docs live in [`docs/`](docs/README.md):

- [Architecture](docs/architecture.md) — components, roles, webhook/polling, storage, observability
- [Data model](docs/data-model.md) — entities & state machine (§2, §4)
- [Governance](docs/governance.md) — voting, thresholds, removal, appeals, trust (§5)
- [Search](docs/search.md) — tiered ranking + media delivery (§6)
- [Commands](docs/commands.md) — full command/inline surface (§8)
- [Deployment](docs/deployment.md) — Docker, env vars, scaling, limitations

## Quick start

```bash
cp .env.example .env        # set BOT_TOKEN, BOT_USERNAME, ADMIN_USERS, REVIEW_CHANNEL_ID
docker compose up -d --build
```

`docker-compose.yml` starts Postgres, Redis, and the bot (`ROLE=both`). For
larger scale, run `ROLE=web` replicas behind a load balancer and a separate
`ROLE=worker` for scheduled jobs.

## What's implemented (v1)

- Private pool: `/add`, `/find`, quota enforcement, inline search.
- Tiered search ranking (tag overlap + FTS + pg_trgm) with tunable blend.
- Public submissions + review-channel voting + state machine.
- Report → removal-review pipeline, admin/legal removal, community downvote,
  appeals, illegal-content blocklist.
- Transparency: `/policy`, `/mystatus`, `/removals`, versioned policy doc.
- Redis FSM, Prometheus `/metrics`, JSON structured logs, rate limiting.
- Media mirrored from Telegram **once**; sent by cached `file_id` with
  self-healing re-upload on staleness (verified by tests).

## Verification

`pytest` (9 tests) covers the §6.2 store-once contract and the §5.2/§5.4 policy
math. A live end-to-end run additionally needs Postgres, Redis, and a real
Telegram token.

```bash
uv venv && uv pip install -r requirements.txt
pytest -q
```
