# Search & Retrieval (spec §6)

## Tiered matching, cheapest-first (§6.1)

Implemented in `app/search.py`. For a query `q` (lowercased), the candidate set
is **public** memes + the requesting user's **own private** memes, with NSFW
excluded from default results unless `include_nsfw` is set. Scoring blends:

1. **Tag overlap** — `cardinality(tags & string_to_array(lower(q), ' '))` over a
   GIN index on `tags`.
2. **Full-text** — `ts_rank(search_tsv, plainto_tsquery('simple', q))` over a
   GIN index on a generated `to_tsvector('simple', title || ' ' || description)`
   column.
3. **Fuzzy** — `similarity(title, q)` / `similarity(description, q)` via `pg_trgm`
   (threshold 0.3) for typo tolerance ("pikahcu" → "pikachu").

### Rank blend
```
score = w1 * (text_rank + tag_overlap + 0.6 * fuzzy)
      + w2 * ln(popularity + 1)
      + w3 * exp(-age_days / 30)
      - w4 * report_count
```
Weights `RANK_TEXT_WEIGHT`, `RANK_POPULARITY_WEIGHT`, `RANK_RECENCY_WEIGHT`,
`RANK_REPORT_PENALTY` are env-configurable (§7.4). Empty query returns the most
popular/recent memes.

## Media delivery — the Telegram-specific trick (§6.2)

- Telegram resends media by `file_id` without re-uploading, but `file_id`s are
  bot-specific and can go stale (deleted source message, long time spans).
- `Meme.telegram_file_id` is the **fast path** (cache).
- Raw media is also mirrored to S3-compatible storage keyed by `file_hash` as the
  **durable source of truth** (`storage_object_key`).

`app/storage.py`:
- `store_media(bot, file_id, file_hash, media_type)` — downloads from Telegram
  and writes to durable storage **exactly once** at ingest.
- `send_media(bot, chat_id, meme)` — sends by `file_id`; on a stale-`file_id`
  error, loads from durable storage and re-uploads once, then refreshes the
  cached `file_id` (self-healing). The happy path never reads durable storage.

This contract is verified by `tests/test_storage.py` (store-once on ingest;
no durable-store read on the normal send path; single re-upload only on
staleness).

## Inline mode specifics (§6.3)
Inline queries have a strict latency budget. Search is indexed and synchronous
(no LLM in the hot path for v1). Results are returned with `cache_time` and
`is_personal=True` (per-user private pool scoping is server-enforced). "Show
more" beyond the first page is handled via the `/find` `More` button (offset).
