"""Tiered search & retrieval ranking (spec §6.1).

Cheapest-first blend of: tag overlap (GIN), full-text rank (tsvector), and
pg_trgm fuzzy similarity, combined with popularity / recency / report signals.
All weights live in Settings (env) so they are tunable without a redeploy.
"""

from sqlalchemy import text

from app.config import get_settings
from app.db import SessionLocal

settings = get_settings()


async def search(
    query: str,
    user_id: int,
    *,
    include_nsfw: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    q = (query or "").strip().lower()
    params = {
        "q": q,
        "owner": user_id,
        "nsfw": include_nsfw,
        "limit": limit,
        "offset": offset,
        "w1": settings.rank_text_weight,
        "w2": settings.rank_popularity_weight,
        "w3": settings.rank_recency_weight,
        "w4": settings.rank_report_penalty,
    }
    sql = """
    WITH matched AS (
      SELECT m.id, m.owner_id, m.visibility, m.media_type, m.telegram_file_id,
             m.title, m.tags, m.nsfw, m.popularity,
        cardinality(tags & string_to_array(lower(:q), ' ')) AS tag_overlap,
        ts_rank(m.search_tsv, plainto_tsquery('simple', :q)) AS text_rank,
        GREATEST(similarity(m.title, :q),
                 similarity(coalesce(m.description, ''), :q), 0) AS fuzzy,
        (SELECT count(*) FROM reports r WHERE r.meme_id = m.id) AS report_count,
        EXTRACT(EPOCH, now() - m.submitted_at) / 86400.0 AS age_days
      FROM memes m
      WHERE (
              (m.visibility = 'public'
               OR (m.visibility = 'private' AND m.owner_id = :owner))
              AND (m.nsfw = false OR :nsfw)
            )
        AND (
              (:q = '')
              OR (tags && string_to_array(lower(:q), ' '))
              OR (m.search_tsv @@ plainto_tsquery('simple', :q))
              OR (similarity(m.title, :q) > 0.3)
              OR (similarity(coalesce(m.description, ''), :q) > 0.3)
            )
    )
    SELECT id, owner_id, visibility, media_type, telegram_file_id, title, tags,
           nsfw, popularity,
           (:w1 * (COALESCE(text_rank, 0) + tag_overlap + 0.6 * fuzzy))
           + (:w2 * LN(popularity + 1))
           + (:w3 * EXP(-age_days / 30.0))
           - (:w4 * report_count) AS score
    FROM matched
    ORDER BY score DESC
    LIMIT :limit OFFSET :offset
    """
    async with SessionLocal() as session:
        result = await session.execute(text(sql), params)
        rows = result.mappings().all()
    return [
        {
            "id": str(r["id"]),
            "owner_id": r["owner_id"],
            "visibility": r["visibility"],
            "media_type": r["media_type"],
            "telegram_file_id": r["telegram_file_id"],
            "title": r["title"],
            "tags": r["tags"] or [],
            "nsfw": r["nsfw"],
            "popularity": r["popularity"],
            "score": round(float(r["score"]), 4),
        }
        for r in rows
    ]
