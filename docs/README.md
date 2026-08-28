# MemeBot Documentation

A community-curated Telegram meme retrieval bot. This directory holds the full
design and operations documentation. The implementation follows the product spec
(§10 build order) and lives in `app/`.

| Document | What it covers |
|---|---|
| [architecture.md](architecture.md) | Components, runtime roles, webhook/polling, storage, observability |
| [data-model.md](data-model.md) | Entities, fields, relationships, state machine (spec §2, §4) |
| [governance.md](governance.md) | Voting, thresholds, removal policy, appeals, trust, transparency (§5) |
| [search.md](search.md) | Tiered retrieval ranking + media delivery (§6) |
| [commands.md](commands.md) | Full command/inline surface (§8) |
| [deployment.md](deployment.md) | Docker, env config, scaling, limitations |

## Quick start

```bash
cp .env.example .env        # set BOT_TOKEN, BOT_USERNAME, ADMIN_USERS, REVIEW_CHANNEL_ID
docker compose up -d --build
```

See [deployment.md](deployment.md) for the full variable reference and scaling notes.

## Verification status

- `pytest` covers the §6.2 store-once contract and the §5.2/§5.4 policy math
  (9 tests, all passing in CI/local).
- Requires a running **Postgres**, **Redis**, and a real **Telegram bot token**
  for an end-to-end live run (not available in the build sandbox).
