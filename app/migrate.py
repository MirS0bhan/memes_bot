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
from app.enums import Visibility  # adjust to wherever this enum actually lives
from app.logging_config import configure_logging, log_event
from app.models import Base, PolicyDocument
from app.policy import DEFAULT_POLICY_VERSION, default_policy_text

settings = get_settings()
logger = logging.getLogger(__name__)

# Postgres ENUM type name -> Python StrEnum defining its labels.
# Extend this mapping whenever a new Postgres ENUM column is added --
# create_all alone will never keep these in sync after first creation.
_PG_ENUMS = {
    "visibility": Visibility,
}


async def _sync_pg_enum(enum_name: str, python_enum) -> None:
    """Ensure the live Postgres enum type has every label the Python enum defines.

    `Base.metadata.create_all` only issues `CREATE TYPE IF NOT EXISTS`: once
    the type exists, create_all never adds new labels to it. That's the
    actual cause of the recurring 'invalid input value for enum visibility:
    "public"' errors -- the type was created in this DB before some values
    existed in code, and every subsequent migrate() run silently no-ops.

    ALTER TYPE ... ADD VALUE must run outside the surrounding transaction
    (its new value also can't be used inside the same transaction it was
    added in), so this runs on its own autocommit connection.
    """
    autocommit_engine = engine.execution_options(isolation_level="AUTOCOMMIT")
    async with autocommit_engine.connect() as conn:
        result = await conn.execute(
            text("SELECT enumlabel FROM pg_enum WHERE enumtypid = :t::regtype"),
            {"t": enum_name},
        )
        existing = {row[0] for row in result}
        missing = [m.value for m in python_enum if m.value not in existing]
        for label in missing:
            log_event(logger, "pg_enum_add_value", enum=enum_name, value=label)
            # Values come only from our own trusted Python enum, not user
            # input, so building the literal here is safe.
            await conn.execute(
                text(f"ALTER TYPE {enum_name} ADD VALUE IF NOT EXISTS '{label}'")
            )


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

    # Must run after create_all's transaction commits (so the types already
    # exist) and on a separate autocommit connection (ALTER TYPE ADD VALUE
    # requirement).
    for enum_name, python_enum in _PG_ENUMS.items():
        await _sync_pg_enum(enum_name, python_enum)

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