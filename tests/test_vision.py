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
