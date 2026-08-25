import pytest

from app.db.database import Database
from app.models import Card
from app.services import parts

# Мониторы Dell: номер детали 0Y71R3 соответствует E2722H, 07MT01 — другой модели
E2722H_SERIAL = "CN0Y71R3TV20019B13QTA01"
OTHER_SERIAL = "CN07MT01QDC0074Q0DDSA04"


@pytest.fixture
async def db(tmp_path):
    database = Database(tmp_path / "parts.db")
    await database.connect()
    yield database
    await database.close()


async def test_model_comes_from_template_when_photo_is_unreadable(db):
    card = Card(serial_number=E2722H_SERIAL)
    assert await parts.fill_model(card, db) is True
    assert card.model == "E2722H"
    assert card.model_inferred is True
    assert card.brand == "DELL"


async def test_read_model_is_not_overwritten(db):
    card = Card(serial_number=E2722H_SERIAL, model="U2419H")
    assert await parts.fill_model(card, db) is False
    assert card.model == "U2419H"
    assert card.model_inferred is False


async def test_unknown_part_leaves_model_empty(db):
    card = Card(serial_number=OTHER_SERIAL)
    assert await parts.fill_model(card, db) is False
    assert card.model is None


async def test_confirmed_card_teaches_the_mapping(db):
    await parts.remember(Card(serial_number=OTHER_SERIAL, model="P2419H"), db, parts.LEARNED)
    assert await db.get_part_model("DELL", "07MT01") == "P2419H"

    card = Card(serial_number=OTHER_SERIAL)
    await parts.fill_model(card, db)
    assert (card.model, card.model_inferred) == ("P2419H", True)


async def test_manual_correction_wins_over_learned(db):
    await parts.remember(Card(serial_number=OTHER_SERIAL, model="WRONG1"), db, parts.LEARNED)
    await parts.remember(Card(serial_number=OTHER_SERIAL, model="P2419H"), db, parts.MANUAL)
    assert await db.get_part_model("DELL", "07MT01") == "P2419H"

    # Накопленное значение больше не затирает ручную правку
    await parts.remember(Card(serial_number=OTHER_SERIAL, model="WRONG2"), db, parts.LEARNED)
    assert await db.get_part_model("DELL", "07MT01") == "P2419H"


async def test_inferred_model_is_not_learned_again(db):
    card = Card(serial_number=E2722H_SERIAL, model="E2722H", model_inferred=True)
    await parts.remember(card, db, parts.LEARNED)
    assert await db.get_part_model("DELL", "0Y71R3") is None


async def test_yaml_snippet_is_ready_to_paste(db):
    await parts.remember(Card(serial_number=OTHER_SERIAL, model="P2419H"), db, parts.MANUAL)
    snippet = parts.as_yaml(await db.list_part_models())
    assert "model:" in snippet
    assert "  by_part:" in snippet
    assert "    07MT01: P2419H" in snippet
