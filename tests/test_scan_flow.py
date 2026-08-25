from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.database import Database
from app.export import exporter
from app.handlers import edit, scan
from app.models import Card, Confidence, Source, Status
from app.services import normalize as nz
from app.texts import ASK_LOCATION
from tests.factories import SERIAL, SERVICE_TAG, barcode_image, sticker_bytes


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "test.db")
    await database.connect()
    yield database
    await database.close()


def make_message(user_id: int = 42, username: str = "tester"):
    status_message = AsyncMock()
    message = MagicMock()
    message.from_user.id = user_id
    message.from_user.username = username
    message.answer = AsyncMock(return_value=status_message)
    return message, status_message


def make_bot(payload: bytes):
    async def download(_file_id, destination):
        destination.write(payload)

    bot = MagicMock()
    bot.download = AsyncMock(side_effect=download)
    return bot


def make_callback(scan_id: int, action: str = "confirm"):
    callback = MagicMock()
    callback.data = f"scan:{action}:{scan_id}"
    callback.from_user.id = 42
    callback.message.edit_text = AsyncMock()
    callback.message.answer = AsyncMock()
    callback.answer = AsyncMock()
    return callback


async def test_photo_to_confirmed_record(db):
    payload = sticker_bytes(barcode_image(SERIAL), barcode_image(SERVICE_TAG))
    message, status_message = make_message()

    await scan._process(message, make_bot(payload), db, "file-id", len(payload))

    status_message.edit_text.assert_awaited_once()
    text = status_message.edit_text.await_args.args[0]
    assert SERVICE_TAG in text
    assert SERIAL in text or nz.display_serial(SERIAL) in text
    assert "<code>" in text
    assert status_message.edit_text.await_args.kwargs["reply_markup"] is not None

    row = await db.get_scan(1)
    assert row["status"] == Status.PENDING
    assert row["serial_number"] == SERIAL
    assert row["source"] == "barcode"

    state = AsyncMock()
    await edit._finalize(make_callback(1), db, state, 1, Status.CONFIRMED)
    row = await db.get_scan(1)
    assert row["status"] == Status.CONFIRMED

    rows = await db.export_rows(user_id=42, since=None)
    assert len(rows) == 1
    assert exporter.to_csv(rows).startswith(b"\xef\xbb\xbf")
    assert exporter.to_xlsx(rows)[:2] == b"PK"


async def test_unreadable_photo_reports_failure(db):
    import cv2
    import numpy as np

    blank = cv2.imencode(".png", np.full((400, 400, 3), 255, dtype=np.uint8))[1].tobytes()
    message, status_message = make_message()

    await scan._process(message, make_bot(blank), db, "file-id", len(blank))

    text = status_message.edit_text.await_args.args[0]
    assert "Не удалось распознать" in text

    # Отказ фиксируется в базе: без этого нельзя посчитать долю неудач
    row = await db.get_scan(1)
    assert row["status"] == Status.DISCARDED
    assert row["source"] == "none"
    assert row["serial_number"] is None
    # В выгрузку подтверждённых записей отказы не попадают
    assert await db.export_rows(user_id=42, since=None) == []


async def test_broken_file_reports_decode_error(db):
    message, status_message = make_message()
    await scan._process(message, make_bot(b"not-an-image"), db, "file-id", 12)
    assert "Не удалось открыть изображение" in status_message.edit_text.await_args.args[0]


async def test_oversized_file_is_rejected(db):
    message, _ = make_message()
    await scan._process(message, make_bot(b""), db, "file-id", 21 * 1024 * 1024)
    assert "20 МБ" in message.answer.await_args.args[0]


async def test_download_failure_is_reported(db):
    message, status_message = make_message()
    bot = MagicMock()
    bot.download = AsyncMock(side_effect=RuntimeError("network"))
    await scan._process(message, bot, db, "file-id", 1000)
    assert "Не удалось загрузить файл" in status_message.edit_text.await_args.args[0]


async def test_duplicate_is_detected(db):
    payload = sticker_bytes(barcode_image(SERIAL))
    for _ in range(2):
        message, _ = make_message()
        await scan._process(message, make_bot(payload), db, "file-id", len(payload))

    await edit._finalize(make_callback(1), db, AsyncMock(), 1, Status.CONFIRMED)
    callback = make_callback(2)
    await edit._finalize(callback, db, AsyncMock(), 2, Status.CONFIRMED)

    assert "уже сканировалось" in callback.message.edit_text.await_args.args[0]


async def _add_scan(db: Database, user_id: int = 42) -> int:
    return await db.add_scan(
        Card(
            serial_number=SERIAL,
            source=Source.BARCODE,
            confidence=Confidence.HIGH,
        ),
        user_id=user_id,
        username="tester",
        status=Status.PENDING,
    )


async def test_confirm_offers_location_when_empty(db):
    scan_id = await _add_scan(db)
    callback = make_callback(scan_id)
    await edit._finalize(callback, db, AsyncMock(), scan_id, Status.CONFIRMED)
    sent = [call.args[0] for call in callback.message.answer.await_args_list]
    assert any(ASK_LOCATION[:20] in text for text in sent)


async def test_confirm_skips_location_prompt_when_already_set(db):
    scan_id = await _add_scan(db)
    await db.update_field(scan_id, "location", "Москва, Ленина 5, кабинет 12")
    callback = make_callback(scan_id)
    await edit._finalize(callback, db, AsyncMock(), scan_id, Status.CONFIRMED)
    callback.message.answer.assert_not_awaited()


async def test_location_is_stored_as_city_street_room(db):
    scan_id = await _add_scan(db)
    state = AsyncMock()
    state.get_data = AsyncMock(
        return_value={
            "scan_id": scan_id,
            "place": {
                "city": "Москва",
                "street": "Ленина",
                "house": "5",
                "latitude": 55.75,
                "longitude": 37.61,
            },
        }
    )
    message = MagicMock()
    message.answer = AsyncMock()
    await edit._commit_location(message, db, state, 42, "12")

    row = await db.get_scan(scan_id)
    assert row["location"] == "Москва, Ленина 5, кабинет 12"
    saved = await db.get_user_place(42)
    assert saved["city"] == "Москва"
    assert saved["street"] == "Ленина"
    assert saved["house"] == "5"
