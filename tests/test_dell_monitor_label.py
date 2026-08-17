"""Разбор реального шильдика монитора Dell E2722H с китайскими подписями.

Блоки воспроизводят то, что EasyOCR с OCR_LANGS=en возвращает для такой наклейки:
латиница читается, иероглифы (型号, 液晶显示器) в результат не попадают.
"""

from app.services import normalize as nz
from app.services.ocr import Block, parse_blocks

LINE_HEIGHT = 26


def line(text: str, index: int, x1: float = 60, width: float = 300) -> Block:
    y1 = 40 + index * (LINE_HEIGHT + 8)
    return Block(text=text, confidence=0.9, x1=x1, y1=y1, x2=x1 + width, y2=y1 + LINE_HEIGHT)


def label_blocks() -> list[Block]:
    return [
        line("DELL", 0, x1=60, width=90),
        line("E2722H", 0, x1=700, width=120),
        line("E2722H", 2, x1=150, width=120),
        line("100-240V~ 50/60HZ,1.5A", 3, width=330),
        line("Sep. 2021", 5, x1=430, width=140),
        line("Service Tag:", 6, width=160),
        line("84ZCSF3", 7, width=120),
        line("Express Serv", 8, width=160),
        line("Code:", 9, width=80),
        line("1771550665", 10, width=160),
        line("S/N: CN-0Y71R3", 6, x1=520, width=230),
        line("-TV200-19B-1EHT", 7, x1=520, width=230),
        line("-A01", 8, x1=520, width=90),
        line("F40G270I79017A--HF XY", 10, x1=520, width=260),
    ]


def test_model_is_found_without_latin_label():
    card = parse_blocks(label_blocks())
    assert card is not None
    assert card.model == "E2722H"


def test_service_tag_and_multiline_serial():
    card = parse_blocks(label_blocks())
    assert card.service_tag == "84ZCSF3"
    assert card.serial_number == "CN-0Y71R3-TV200-19B-1EHT-A01"


def test_express_service_code_is_not_taken_for_service_tag():
    card = parse_blocks(label_blocks())
    assert card.service_tag != "1771550"
    assert "1771550665" not in (card.serial_number or "")


def test_part_number_and_voltage_are_not_taken_for_model():
    card = parse_blocks(label_blocks())
    assert card.model not in {"F40G270I79017A", "240V", "TV200", "2021"}


def test_hyphenated_ppid_reveals_dell():
    assert nz.infer_brand_from_serial("CN-0Y71R3-TV200-19B-1EHT-A01") == "DELL"


def test_letter_o_after_country_code_becomes_zero():
    assert nz.polish_serial("CN-OY71R3-TV200-19B-1EHT-A01") == (
        "CN-0Y71R3-TV200-19B-1EHT-A01",
        True,
    )
    # Значение уже каноничное — трогать его нельзя
    assert nz.polish_serial("CN-0Y71R3-TV200-19B-1EHT-A01")[1] is False
    # Не PPID — правка не применяется
    assert nz.polish_serial("ABCO1234")[1] is False


def test_model_candidate_ignores_serial_fragments():
    text = "DELL E2722H S/N CN-0Y71R3-TV200-19B-1EHT-A01 E2722H"
    assert nz.find_model_candidate(text, exclude=("CN-0Y71R3-TV200-19B-1EHT-A01",)) == "E2722H"
