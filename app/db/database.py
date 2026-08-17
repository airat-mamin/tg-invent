import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from app.models import Card, Confidence, Source, Status
from app.services import normalize

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT    NOT NULL,
    tg_user_id      INTEGER NOT NULL,
    tg_username     TEXT,
    brand           TEXT,
    model           TEXT,
    serial_number   TEXT,
    serial_display  TEXT,
    service_tag     TEXT,
    source          TEXT    NOT NULL,
    confidence      TEXT    NOT NULL,
    status          TEXT    NOT NULL,
    raw_text        TEXT,
    image_path      TEXT,
    duration_ms     INTEGER NOT NULL DEFAULT 0,
    location        TEXT
);
CREATE TABLE IF NOT EXISTS part_models (
    brand       TEXT NOT NULL,
    part        TEXT NOT NULL,
    model       TEXT NOT NULL,
    source      TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (brand, part)
);
CREATE INDEX IF NOT EXISTS idx_scans_serial  ON scans (serial_number);
CREATE INDEX IF NOT EXISTS idx_scans_tag     ON scans (service_tag);
CREATE INDEX IF NOT EXISTS idx_scans_user    ON scans (tg_user_id);
CREATE INDEX IF NOT EXISTS idx_scans_created ON scans (created_at);
"""

MIGRATIONS = ("ALTER TABLE scans ADD COLUMN serial_display TEXT",)

EXPORT_COLUMNS = (
    "id",
    "created_at",
    "tg_user_id",
    "tg_username",
    "brand",
    "model",
    "serial_number",
    "serial_display",
    "service_tag",
    "source",
    "confidence",
    "status",
    "location",
)


class Database:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._migrate()
        await self._conn.commit()
        logger.info("База данных готова: %s", self._path)

    async def _migrate(self) -> None:
        """Досоздаёт колонки, появившиеся после первого запуска бота."""
        for statement in MIGRATIONS:
            try:
                await self.conn.execute(statement)
            except aiosqlite.OperationalError as error:
                if "duplicate column" not in str(error).lower():
                    raise

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Соединение с БД не инициализировано")
        return self._conn

    async def add_scan(
        self,
        card: Card,
        user_id: int,
        username: str | None,
        status: Status = Status.PENDING,
        image_path: str | None = None,
    ) -> int:
        cursor = await self.conn.execute(
            """
            INSERT INTO scans (created_at, tg_user_id, tg_username, brand, model, serial_number,
                               serial_display, service_tag, source, confidence, status, raw_text,
                               image_path, duration_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                user_id,
                username,
                card.brand,
                card.model,
                card.serial_number,
                card.serial_display,
                card.service_tag,
                str(card.source),
                str(card.confidence),
                str(status),
                card.raw_text,
                image_path,
                card.duration_ms,
            ),
        )
        await self.conn.commit()
        return int(cursor.lastrowid or 0)

    async def get_scan(self, scan_id: int) -> aiosqlite.Row | None:
        async with self.conn.execute("SELECT * FROM scans WHERE id = ?", (scan_id,)) as cursor:
            return await cursor.fetchone()

    async def set_status(self, scan_id: int, status: Status) -> None:
        await self.conn.execute("UPDATE scans SET status = ? WHERE id = ?", (str(status), scan_id))
        await self.conn.commit()

    async def update_field(self, scan_id: int, field: str, value: str | None) -> None:
        if field not in {"brand", "model", "serial_number", "service_tag", "location"}:
            raise ValueError(f"Недопустимое поле: {field}")
        if field == "serial_number":
            # Оба представления серийного номера должны меняться вместе.
            canonical = normalize.canonical_serial(value)
            await self.conn.execute(
                "UPDATE scans SET serial_number = ?, serial_display = ? WHERE id = ?",
                (canonical, normalize.display_serial(canonical, value), scan_id),
            )
        else:
            await self.conn.execute(f"UPDATE scans SET {field} = ? WHERE id = ?", (value, scan_id))
        await self.conn.commit()

    async def find_duplicate(
        self, serial: str | None, tag: str | None, exclude_id: int
    ) -> aiosqlite.Row | None:
        if not serial and not tag:
            return None
        query = """
            SELECT * FROM scans
            WHERE id != ? AND status IN ('confirmed', 'corrected')
              AND ((? IS NOT NULL AND serial_number = ?) OR (? IS NOT NULL AND service_tag = ?))
            ORDER BY created_at DESC LIMIT 1
        """
        async with self.conn.execute(
            query, (exclude_id, serial, serial, tag, tag)
        ) as cursor:
            return await cursor.fetchone()

    async def last_scans(self, user_id: int, limit: int = 10) -> list[aiosqlite.Row]:
        async with self.conn.execute(
            """
            SELECT * FROM scans
            WHERE tg_user_id = ? AND status IN ('confirmed', 'corrected')
            ORDER BY id DESC LIMIT ?
            """,
            (user_id, limit),
        ) as cursor:
            return list(await cursor.fetchall())

    async def export_rows(
        self, user_id: int | None, since: datetime | None
    ) -> list[dict[str, Any]]:
        clauses = ["status IN ('confirmed', 'corrected')"]
        params: list[Any] = []
        if user_id is not None:
            clauses.append("tg_user_id = ?")
            params.append(user_id)
        if since is not None:
            clauses.append("created_at >= ?")
            params.append(since.isoformat(timespec="seconds"))
        query = (
            f"SELECT {', '.join(EXPORT_COLUMNS)} FROM scans "
            f"WHERE {' AND '.join(clauses)} ORDER BY id"
        )
        async with self.conn.execute(query, params) as cursor:
            return [dict(row) for row in await cursor.fetchall()]

    async def get_part_model(self, brand: str, part: str) -> str | None:
        async with self.conn.execute(
            "SELECT model FROM part_models WHERE brand = ? AND part = ?",
            (brand.upper(), part.upper()),
        ) as cursor:
            row = await cursor.fetchone()
        return row["model"] if row else None

    async def set_part_model(self, brand: str, part: str, model: str, source: str) -> bool:
        """Запоминает соответствие. Ручная правка пользователя приоритетнее накопленной."""
        async with self.conn.execute(
            "SELECT model, source FROM part_models WHERE brand = ? AND part = ?",
            (brand.upper(), part.upper()),
        ) as cursor:
            existing = await cursor.fetchone()
        if existing is not None:
            if existing["model"] == model.upper():
                return False
            if existing["source"] == "manual" and source != "manual":
                return False
        await self.conn.execute(
            """
            INSERT INTO part_models (brand, part, model, source, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (brand, part) DO UPDATE
                SET model = excluded.model,
                    source = excluded.source,
                    updated_at = excluded.updated_at
            """,
            (
                brand.upper(),
                part.upper(),
                model.upper(),
                source,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )
        await self.conn.commit()
        return True

    async def list_part_models(self) -> list[aiosqlite.Row]:
        async with self.conn.execute(
            "SELECT brand, part, model, source, updated_at FROM part_models ORDER BY brand, part"
        ) as cursor:
            return list(await cursor.fetchall())

    async def stats(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        async with self.conn.execute("SELECT COUNT(*) FROM scans") as cursor:
            result["total"] = (await cursor.fetchone())[0]
        async with self.conn.execute(
            "SELECT source, COUNT(*) FROM scans GROUP BY source"
        ) as cursor:
            result["by_source"] = {row[0]: row[1] for row in await cursor.fetchall()}
        async with self.conn.execute(
            "SELECT status, COUNT(*) FROM scans GROUP BY status"
        ) as cursor:
            result["by_status"] = {row[0]: row[1] for row in await cursor.fetchall()}
        async with self.conn.execute(
            "SELECT AVG(duration_ms) FROM scans WHERE duration_ms > 0"
        ) as cursor:
            result["avg_ms"] = int((await cursor.fetchone())[0] or 0)
        return result

    async def purge_images(self, retention_days: int, image_dir: Path) -> int:
        """Удаляет изображения старше срока хранения вместе со ссылками в БД."""
        threshold = datetime.now(timezone.utc) - timedelta(days=retention_days)
        removed = 0
        async with self.conn.execute(
            "SELECT id, image_path FROM scans WHERE image_path IS NOT NULL AND created_at < ?",
            (threshold.isoformat(timespec="seconds"),),
        ) as cursor:
            rows = await cursor.fetchall()
        for row in rows:
            path = Path(row["image_path"])
            if not path.is_absolute():
                path = image_dir.parent / path
            path.unlink(missing_ok=True)
            await self.conn.execute(
                "UPDATE scans SET image_path = NULL WHERE id = ?", (row["id"],)
            )
            removed += 1
        if removed:
            await self.conn.commit()
        return removed


def row_to_card(row: aiosqlite.Row) -> Card:
    columns = set(row.keys())
    return Card(
        brand=row["brand"],
        model=row["model"],
        serial_number=row["serial_number"],
        serial_display=row["serial_display"] if "serial_display" in columns else None,
        service_tag=row["service_tag"],
        source=Source(row["source"]),
        confidence=Confidence(row["confidence"]),
        raw_text=row["raw_text"] if "raw_text" in columns else None,
        duration_ms=row["duration_ms"] if "duration_ms" in columns else 0,
    )
