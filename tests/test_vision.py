from types import SimpleNamespace

from app.config import settings
from app.models import Source
from app.services import vision
from app.services.ocr import Block


def _word(text: str, x1: float, y1: float, x2: float, y2: float, confidence: float = 0.95):
    symbols = [SimpleNamespace(text=char) for char in text]
    vertices = [
        SimpleNamespace(x=x1, y=y1),
        SimpleNamespace(x=x2, y=y1),
        SimpleNamespace(x=x2, y=y2),
        SimpleNamespace(x=x1, y=y2),
    ]
    return SimpleNamespace(
        symbols=symbols,
        confidence=confidence,
        bounding_box=SimpleNamespace(vertices=vertices),
    )


def test_blocks_from_annotation_read_words():
    annotation = SimpleNamespace(
        pages=[
            SimpleNamespace(
                blocks=[
                    SimpleNamespace(
                        paragraphs=[
                            SimpleNamespace(
                                words=[
                                    _word("LENOVO", 10, 10, 80, 30),
                                    _word("S/N", 10, 40, 40, 60),
                                    _word("V9-04T4BB", 50, 40, 160, 60),
                                ]
                            )
                        ]
                    )
                ]
            )
        ]
    )
    blocks = vision.blocks_from_annotation(annotation)
    assert [block.text for block in blocks] == ["LENOVO", "S/N", "V9-04T4BB"]


def test_card_from_vision_text_parses_lenovo_label():
    blocks = [
        Block("LENOVO", 0.99, 10, 10, 100, 40),
        Block("THINKVISION E24 10", 0.8, 10, 50, 260, 80),
        Block("SERIAL NUMBER: V9-04T4BB", 0.9, 10, 160, 280, 190),
        Block("61B7JAR6WWV904T4BB", 0.9, 10, 200, 300, 230),
    ]
    card = vision.card_from_vision_text("LENOVO THINKVISION E24 10", blocks)
    assert card is not None
    assert card.source is Source.VISION
    assert card.brand == "LENOVO"
    assert card.serial_number == "61B7JAR6WWV904T4BB"


def test_barcode_payloads_from_lenovo_text():
    text = (
        "Lenovo ThinkVision E24-10 Serial Number: V9-04T4BB "
        "61B7JAR6WWV904T4BB FRU Number: 00PC193 MONITOR 2019-08-16 SERVICE TAG JYK27D2"
    )
    payloads = vision.barcode_payloads_from_text(text)
    assert "61B7JAR6WWV904T4BB" in payloads
    assert "V904T4BB" not in payloads
    assert "MONITOR" not in payloads
    assert "2019-08-16" not in payloads
    assert "00PC193" not in payloads
    assert "JYK27D2" in payloads


def test_overlay_prefers_full_lenovo_barcode_line():
    ocr_card = vision.card_from_vision_text(
        "LENOVO",
        [
            Block("LENOVO", 0.99, 10, 10, 100, 40),
            Block("SERIAL NUMBER: V9-04T4BB", 0.9, 10, 160, 280, 190),
        ],
    )
    payloads = ["V904T4BB", "61B7JAR6WWV904T4BB"]
    card = vision._overlay_barcode_payloads(ocr_card, payloads)
    assert card is not None
    assert card.serial_number == "61B7JAR6WWV904T4BB"
    assert card.barcode_payloads == payloads


def test_type_no_is_not_taken_as_lenovo_barcode():
    text = (
        "SAMSUNG Model: S22B370H Type No: L8228370 "
        "S/N / Серийный номер: 2133HLNC800394F"
    )
    payloads = vision.barcode_payloads_from_text(text)
    assert "L8228370" not in payloads
    assert "2133HLNC800394F" in payloads


def test_samsung_vision_text_takes_sn_not_type_no():
    text = (
        "SAMSUNG Color Display Unit Model/ Модель: 32237ОН "
        "Тип на: L8228370 Model Code: LS22B370HS/CI "
        "S/N / Серийный номер: 2133HLNC800394F"
    )
    card = vision.card_from_vision_text(text, [Block(text, 0.9, 0, 0, 400, 80)])
    card = vision._overlay_barcode_payloads(card, vision.barcode_payloads_from_text(text))
    assert card is not None
    assert card.serial_number == "2133HLNC800394F"
    assert card.serial_number != "L8228370"


def test_split_dell_ppid_becomes_vision_barcode_payload():
    text = "S/N:\nCN-0DMCK5-\nWSL00-28N-\nCA4U-A03\nP2722H"
    assert "CN0DMCK5WSL0028NCA4UA03" in vision.barcode_payloads_from_text(text)
    card = vision.card_from_vision_text(text, [Block(text, 0.9, 0, 0, 400, 80)])
    card = vision._overlay_barcode_payloads(card, vision.barcode_payloads_from_text(text))
    assert card is not None
    assert card.serial_number == "CN0DMCK5WSL0028NCA4UA03"


def test_card_from_vision_text_returns_none_without_identifiers():
    assert vision.card_from_vision_text("DELL MADE IN CHINA", []) is None


def test_enabled_requires_flag_and_existing_key(tmp_path, monkeypatch):
    key = tmp_path / "gcp.json"
    key.write_text("{}")
    monkeypatch.setattr(settings, "vision_enabled", True)
    monkeypatch.setattr(settings, "vision_credentials", key)
    assert vision.enabled()
    monkeypatch.setattr(settings, "vision_enabled", False)
    assert not vision.enabled()
    monkeypatch.setattr(settings, "vision_enabled", True)
    monkeypatch.setattr(settings, "vision_credentials", tmp_path / "missing.json")
    assert not vision.enabled()


def test_scan_is_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(vision, "enabled", lambda: False)
    assert vision.scan(b"img") == (None, "")


def test_billing_error_is_shortened():
    message = vision._short_error(
        '403 This API method requires billing to be enabled. Please enable billing'
    )
    assert message == "нужно включить биллинг в проекте Google Cloud"
