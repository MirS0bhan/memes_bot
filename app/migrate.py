"""Migration runner.

Creates the schema (via SQLAlchemy metadata) plus Postgres-specific extensions,
indexes, and seeds the versioned policy document (spec §5.7).
"""

import asyncio
import logging

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import SessionLocal, engine
from app.logging_config import configure_logging, log_event
from app.models import Base, PolicyDocument
from app.policy import DEFAULT_POLICY_VERSION, default_policy_text

settings = get_settings()
logger = logging.getLogger(__name__)


async def migrate() -> None:
    configure_logging()
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm;"))
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_memes_search_tsv "
                "ON memes USING GIN (search_tsv);"
            )
        )

    async with SessionLocal() as session:
        existing = await session.get(PolicyDocument, DEFAULT_POLICY_VERSION)
        if not existing:
            session.add(
                PolicyDocument(version=DEFAULT_POLICY_VERSION, body=default_policy_text())
            )
        await _seed_illegal_hashes(session)
        await session.commit()

    log_event(logger, "migrate_complete")


async def _seed_illegal_hashes(session: AsyncSession) -> None:
    from app.models import IllegalHash

    for h in settings.illegal_hashes:
        h = h.strip().lower()
        if not h:
            continue
        present = await session.scalar(
            select(IllegalHash).where(IllegalHash.file_hash == h)
        )
        if not present:
            session.add(IllegalHash(file_hash=h, note="seeded from env"))


if __name__ == "__main__":
    asyncio.run(migrate())
