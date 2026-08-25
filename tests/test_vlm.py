from app.models import Source
from app.services.vlm import card_from_payload, extract_json

CLEAN = (
    '{"brand": "Dell", "model": "E2722H", '
    '"serial_number": "CN0Y71R3TV", "service_tag": "9YSCSF3"}'
)


def test_extract_json_from_clean_answer():
    assert extract_json(CLEAN)["service_tag"] == "9YSCSF3"


def test_extract_json_from_wrapped_answer():
    wrapped = f"Вот данные с наклейки:\n```json\n{CLEAN}\n```\nГотово."
    assert extract_json(wrapped)["model"] == "E2722H"


def test_extract_json_returns_none_on_garbage():
    assert extract_json("не удалось распознать") is None
    assert extract_json("") is None


def test_card_from_payload_drops_invalid_identifiers():
    payload = {
        "brand": "Dell",
        "model": None,
        "serial_number": "CN0Y71R3TV",
        "service_tag": "СЛИШКОМДЛИННЫЙ",
    }
    card = card_from_payload(payload, "raw")
    assert card is not None
    assert card.service_tag is None
    assert card.serial_number == "CN0Y71R3TV"
    assert card.source is Source.VLM


def test_card_from_payload_returns_none_without_identifiers():
    assert card_from_payload({"brand": "Dell", "model": "E2722H"}, "raw") is None


def test_string_nulls_are_ignored():
    payload = {"brand": "null", "model": "n/a", "serial_number": "ABC12345", "service_tag": "-"}
    card = card_from_payload(payload, "raw")
    assert card.service_tag is None
    assert card.model is None
