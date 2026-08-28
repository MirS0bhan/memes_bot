"""Data-access helpers used by handlers and governance (spec §2, §3)."""

import hashlib
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.enums import Visibility
from app.models import IllegalHash, Meme, RemovalCase, User

settings = get_settings()


def sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def get_or_create_user(
    session: AsyncSession, telegram_id: int, username: str | None = None
) -> User:
    user = await session.scalar(
        select(User).where(User.telegram_id == telegram_id)
    )
    if user is None:
        user = User(
            telegram_id=telegram_id,
            username=username,
            private_quota=settings.default_private_quota,
        )
        session.add(user)
        try:
            await session.flush()
        except IntegrityError:
            # Another request created the user concurrently; roll back and re-read.
            await session.rollback()
            user = await session.scalar(
                select(User).where(User.telegram_id == telegram_id)
            )
    elif username and user.username != username:
        user.username = username
    return user


async def get_user_by_telegram(session: AsyncSession, telegram_id: int) -> User | None:
    return await session.scalar(select(User).where(User.telegram_id == telegram_id))


async def private_usage(session: AsyncSession, owner_id: int) -> tuple[int, int]:
    quota = await session.scalar(
        select(User.private_quota).where(User.id == owner_id)
    )
    quota = quota if quota is not None else settings.default_private_quota
    count = await session.scalar(
        select(func.count())
        .select_from(Meme)
        .where(Meme.owner_id == owner_id, Meme.visibility == Visibility.PRIVATE)
    )
    return (count or 0), quota


async def add_private_meme(
    session: AsyncSession,
    owner_id: int,
    file_id: str,
    file_hash: str,
    media_type: str,
    title: str,
    tags: list[str],
    nsfw: bool = False,
    description: str | None = None,
    storage_object_key: str | None = None,
) -> Meme:
    meme = Meme(
        owner_id=owner_id,
        visibility=Visibility.PRIVATE,
        media_type=media_type,
        telegram_file_id=file_id,
        file_hash=file_hash,
        title=title,
        description=description,
        tags=[t.lower() for t in tags],
        nsfw=nsfw,
        storage_object_key=storage_object_key,
    )
    session.add(meme)
    await session.flush()
    return meme


async def find_public_by_hash(session: AsyncSession, file_hash: str) -> Meme | None:
    return await session.scalar(
        select(Meme).where(
            Meme.file_hash == file_hash, Meme.visibility == Visibility.PUBLIC
        )
    )


async def get_meme(session: AsyncSession, meme_id: UUID | str) -> Meme | None:
    if isinstance(meme_id, str):
        try:
            meme_id = UUID(meme_id)
        except ValueError:
            return None
    return await session.get(Meme, meme_id)


async def log_retrieval(
    session: AsyncSession,
    meme_id: UUID,
    user_id: int,
    query_text: str,
    chosen_rank: int | None,
) -> None:
    from app.models import RetrievalEvent

    session.add(
        RetrievalEvent(
            meme_id=meme_id,
            user_id=user_id,
            query_text=query_text,
            chosen_rank=chosen_rank,
        )
    )
    await session.execute(
        text("UPDATE memes SET popularity = popularity + 1 WHERE id = :mid"),
        {"mid": meme_id},
    )


async def is_illegal_hash(session: AsyncSession, file_hash: str) -> bool:
    return bool(
        await session.scalar(
            select(IllegalHash).where(IllegalHash.file_hash == file_hash.lower())
        )
    )


async def add_illegal_hash(session: AsyncSession, file_hash: str, note: str | None = None) -> None:
    file_hash = file_hash.strip().lower()
    if not await is_illegal_hash(session, file_hash):
        session.add(IllegalHash(file_hash=file_hash, note=note))


async def remove_illegal_hash(session: AsyncSession, file_hash: str) -> bool:
    row = await session.scalar(
        select(IllegalHash).where(IllegalHash.file_hash == file_hash.strip().lower())
    )
    if row:
        await session.delete(row)
        return True
    return False


async def recent_removal_cases(session: AsyncSession, limit: int = 20) -> list[dict]:
    """Public, anonymized removal audit log (spec §5.7)."""
    from sqlalchemy import select as _select

    rows = await session.execute(
        _select(
            RemovalCase.id,
            RemovalCase.policy_clause,
            RemovalCase.decision,
            RemovalCase.trigger,
            RemovalCase.created_at,
            Meme.title,
        )
        .join(Meme, Meme.id == RemovalCase.meme_id)
        .order_by(RemovalCase.created_at.desc())
        .limit(limit)
    )
    return [
        {
            "id": str(r.id),
            "title": r.title,
            "clause": r.policy_clause,
            "trigger": r.trigger,
            "decision": r.decision,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows.all()
    ]
