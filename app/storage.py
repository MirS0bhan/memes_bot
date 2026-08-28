"""Media storage with self-healing file_id cache (spec §6.2).

Behaviour:
- Media is mirrored from Telegram to durable storage **exactly once**, at ingest
  time (`store_media`). The stored `file_id` is the fast path for sending.
- `send_media` sends by `file_id` and only re-uploads from storage if Telegram
  reports the id as stale (rare) — it never re-uploads on the normal path.

Two backends are supported: S3-compatible (aioboto3) when S3 is configured, else a
local filesystem backend (useful for dev/test and fully verifies the store-once
contract without external services).
"""

import logging
import os
from pathlib import Path

from aiogram import Bot
from aiogram.types import BufferedInputFile
from aiogram.exceptions import TelegramBadRequest

from app.config import get_settings
from app.enums import MediaType

logger = logging.getLogger(__name__)
settings = get_settings()


class StorageBackend:
    async def put(self, key: str, data: bytes) -> None: ...
    async def get(self, key: str) -> bytes | None: ...
    async def delete(self, key: str) -> None: ...


class LocalFSBackend(StorageBackend):
    def __init__(self, root: str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Guard against path traversal in keys.
        safe = key.lstrip("/").replace("..", "")
        return self.root / safe

    async def put(self, key: str, data: bytes) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    async def get(self, key: str) -> bytes | None:
        p = self._path(key)
        return p.read_bytes() if p.exists() else None

    async def delete(self, key: str) -> None:
        p = self._path(key)
        if p.exists():
            p.unlink()


class S3Backend(StorageBackend):
    def __init__(self) -> None:
        import aioboto3

        self._session = aioboto3.Session()
        self._bucket = settings.s3_bucket

    def _client(self):
        return self._session.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
        )

    async def put(self, key: str, data: bytes) -> None:
        async with self._client() as s3:
            await s3.put_object(Bucket=self._bucket, Key=key, Body=data)

    async def get(self, key: str) -> bytes | None:
        try:
            async with self._client() as s3:
                obj = await s3.get_object(Bucket=self._bucket, Key=key)
                async with obj["Body"] as stream:
                    return await stream.read()
        except Exception:
            logger.exception("Failed to load from S3 key=%s", key)
            return None

    async def delete(self, key: str) -> None:
        try:
            async with self._client() as s3:
                await s3.delete_object(Bucket=self._bucket, Key=key)
        except Exception:
            logger.exception("Failed to delete S3 key=%s", key)


_backend: StorageBackend | None = None


def get_backend() -> StorageBackend:
    global _backend
    if _backend is None:
        if settings.s3_endpoint_url and settings.s3_bucket:
            _backend = S3Backend()
        else:
            _backend = LocalFSBackend(settings.storage_path)
    return _backend


def key_for(media_type: MediaType, file_hash: str) -> str:
    return f"{media_type.value}/{file_hash}"


# ── ingest path (runs once per meme, spec §6.2) ───────────────────────────────

async def download_bytes(bot: Bot, file_id: str) -> bytes | None:
    """Download raw media bytes from Telegram (best effort)."""
    try:
        tg_file = await bot.get_file(file_id)
        data = await bot.download_file(tg_file.file_path)
        return data.read() if hasattr(data, "read") else data
    except Exception:
        logger.exception("Failed to download media file_id=%s", file_id)
        return None


async def store_media(bot: Bot, file_id: str, file_hash: str, media_type: MediaType) -> str | None:
    """Mirror media from Telegram to durable storage exactly once. Returns key."""
    content = await download_bytes(bot, file_id)
    if not content:
        return None
    key = key_for(media_type, file_hash)
    await get_backend().put(key, content)
    logger.info("Stored media once in durable store key=%s (%d bytes)", key, len(content))
    return key


# ── delivery path (uses cached file_id; re-upload only on staleness) ──────────

_STALE_HINTS = ("wrong file_id", "file not found", "file is too big", "MEDIA_NOT_FOUND")


async def send_media(bot: Bot, chat_id: int, meme: dict) -> str | None:
    """Send a meme. Returns the (possibly refreshed) telegram_file_id.

    Normal path: send by cached `telegram_file_id` — no re-upload.
    Self-healing path: only if Telegram reports the id stale do we load from
    durable storage and re-upload once, then cache the new id.
    """
    mtype = MediaType(meme["media_type"])
    file_id = meme["telegram_file_id"]

    senders = {
        MediaType.PHOTO: bot.send_photo,
        MediaType.VIDEO: bot.send_video,
        MediaType.ANIMATION: bot.send_animation,
        MediaType.VOICE: bot.send_voice,
        MediaType.AUDIO: bot.send_audio,
    }

    try:
        if mtype in senders:
            await senders[mtype](chat_id, file_id)
        else:  # sticker: cannot re-upload from bytes
            await bot.send_sticker(chat_id, file_id)
        return file_id
    except TelegramBadRequest as exc:
        if not any(h in str(exc).lower() for h in _STALE_HINTS):
            raise
        logger.warning("Stale file_id for meme %s, recovering from durable store", meme["id"])

    key = meme.get("storage_object_key")
    if not key:
        logger.error("Cannot recover meme %s: no storage_object_key", meme["id"])
        return None
    data = await get_backend().get(key)
    if not data:
        return None
    try:
        if mtype in senders:
            msg = await senders[mtype](chat_id, BufferedInputFile(data, filename="meme"))
        else:
            return None
    except TelegramBadRequest:
        logger.error("Re-upload failed for meme %s", meme["id"])
        return None

    new_file_id = _extract_file_id(msg, mtype)
    if new_file_id:
        await _update_file_id(meme["id"], new_file_id)
    return new_file_id


async def purge_media(key: str) -> None:
    """Hard-delete media from durable store (illegal-content purge, spec §9.4)."""
    await get_backend().delete(key)


async def _update_file_id(meme_id: str, new_file_id: str) -> None:
    from sqlalchemy import text

    from app.db import SessionLocal

    async with SessionLocal() as session:
        await session.execute(
            text("UPDATE memes SET telegram_file_id = :fid WHERE id = :mid"),
            {"fid": new_file_id, "mid": meme_id},
        )
        await session.commit()


def _extract_file_id(msg, mtype: MediaType) -> str | None:
    mapping = {
        MediaType.PHOTO: lambda m: m.photo[-1].file_id,
        MediaType.VIDEO: lambda m: m.video.file_id,
        MediaType.ANIMATION: lambda m: m.animation.file_id,
        MediaType.VOICE: lambda m: m.voice.file_id,
        MediaType.AUDIO: lambda m: m.audio.file_id,
    }
    fn = mapping.get(mtype)
    return fn(msg) if fn else None
