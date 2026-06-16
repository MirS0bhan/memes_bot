import aiosqlite
import os

DB_PATH = os.getenv("DB_PATH", "/data/media.db")


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS media (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER NOT NULL,
                file_id TEXT NOT NULL,
                file_unique_id TEXT NOT NULL UNIQUE,
                media_type TEXT NOT NULL,
                keywords TEXT NOT NULL,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_owner ON media(owner_id)")
        await db.commit()


async def add_media(owner_id: int, file_id: str, file_unique_id: str, media_type: str, keywords: list[str]):
    kw = ",".join(k.strip().lower() for k in keywords if k.strip())
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO media (owner_id, file_id, file_unique_id, media_type, keywords) VALUES (?,?,?,?,?)",
            (owner_id, file_id, file_unique_id, media_type, kw),
        )
        await db.commit()


async def search_media(query: str) -> list[dict]:
    query = query.strip().lower()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if query:
            cursor = await db.execute(
                """
                SELECT id, file_id, file_unique_id, media_type, keywords
                FROM media
                WHERE (',' || keywords || ',') LIKE ?
                ORDER BY added_at DESC
                LIMIT 50
                """,
                (f"%,{query}%",),
            )
        else:
            cursor = await db.execute(
                """
                SELECT id, file_id, file_unique_id, media_type, keywords
                FROM media
                ORDER BY added_at DESC
                LIMIT 50
                """,
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def list_media() -> list[dict]:
    return await search_media("")


async def get_media_by_id(media_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT id, file_id, file_unique_id, media_type, keywords FROM media WHERE id = ?",
            (media_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def update_media_keywords(media_id: int, keywords: list[str]) -> bool:
    kw = ",".join(k.strip().lower() for k in keywords if k.strip())
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "UPDATE media SET keywords = ? WHERE id = ?",
            (kw, media_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def delete_media(media_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("DELETE FROM media WHERE id = ?", (media_id,))
        await db.commit()
        return cur.rowcount > 0
