"""Verify the store-once delivery contract (spec §6.2):

- At ingest, media is downloaded from Telegram and mirrored to durable storage
  exactly once.
- At send time, the cached `telegram_file_id` is used — durable storage is NOT
  read (no re-upload) on the happy path.
- Only if Telegram reports the `file_id` as stale does the bot load from durable
  storage, re-upload once, and refresh the cached id.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import TelegramBadRequest

from app.enums import MediaType
from app.storage import LocalFSBackend, get_backend, key_for, send_media, store_media


def _make_bot(content: bytes):
    import io

    bot = MagicMock()
    bot.get_file = AsyncMock(return_value=MagicMock(file_path="fp"))
    bot.download_file = AsyncMock(return_value=io.BytesIO(content))
    return bot


@pytest.fixture
def backend(tmp_path):
    import app.storage as s

    b = LocalFSBackend(str(tmp_path))
    s._backend = b
    return b


@pytest.mark.asyncio
async def test_store_once(backend):
    bot = _make_bot(b"hello-world")
    key = await store_media(bot, "fid1", "deadbeef", MediaType.PHOTO)
    assert key == "photo/deadbeef"
    assert backend._path(key).read_bytes() == b"hello-world"
    # Downloaded from Telegram exactly once at ingest.
    assert bot.get_file.await_count == 1
    assert bot.download_file.await_count == 1


@pytest.mark.asyncio
async def test_send_uses_cache_no_reupload(backend):
    bot = MagicMock()
    bot.send_photo = AsyncMock()
    reads = []
    orig = backend.get

    async def spy(k):
        reads.append(k)
        return await orig(k)

    backend.get = spy
    meme = {
        "id": "x",
        "media_type": "photo",
        "telegram_file_id": "fid-cached",
        "storage_object_key": "photo/h",
    }
    result = await send_media(bot, 42, meme)
    assert result == "fid-cached"
    bot.send_photo.assert_awaited_once()
    # Durable store was never touched on the happy path.
    assert reads == []


@pytest.mark.asyncio
async def test_send_self_heals_on_stale(backend, monkeypatch):
    # Pre-populate durable store with the media bytes.
    await backend.put("photo/h", b"recovered-bytes")

    recovered = MagicMock()
    recovered.photo = [MagicMock(file_id="fid-refreshed")]

    bot = MagicMock()
    # First call (cached id) fails as stale; second (re-upload) succeeds.
    stale = TelegramBadRequest(MagicMock(), "wrong file_id")
    bot.send_photo = AsyncMock(side_effect=[stale, recovered])
    monkeypatch.setattr("app.storage._update_file_id", AsyncMock())

    meme = {
        "id": "x",
        "media_type": "photo",
        "telegram_file_id": "fid-stale",
        "storage_object_key": "photo/h",
    }
    result = await send_media(bot, 42, meme)
    assert result == "fid-refreshed"
    # Stale path: loaded from durable store, re-uploaded once.
    assert bot.send_photo.await_count == 2
    assert await backend.get("photo/h") == b"recovered-bytes"
