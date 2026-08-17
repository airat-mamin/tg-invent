"""Наклейки DEXP и Samsung: русская метка «Модель», которую OCR читает как MONENB."""

from app.services import normalize as nz
from app.services.normalize import rules
from app.services.ocr import Block, parse_blocks

rules.cache_clear()


def test_dexp_model_is_recovered_from_garbled_ocr():
    # Реальный вывод EasyOCR с наклейки DF24H1: «Модель/Үлгісі» → MONENB/YNRICI
    text = "DEXP MOWUTOP MONENB/YNRICI: DFZ4HI 12 B 3A 36 BT 0UJ340085836"
    assert nz.match_brand(text) == "DEXP"
    assert nz.find_model_candidate(text, brand="DEXP") == "DF24H1"
    model, fixed = nz.polish_model("DFZ4HI", "DEXP")
    assert (model, fixed) == ("DF24H1", True)


def test_dexp_label_is_parsed_from_blocks():
    blocks = [
        Block("DEXP", 0.99, 10, 10, 80, 40),
        Block("MONENB/YNRICI: DFZ4HI", 0.8, 10, 50, 320, 80),
        Block("S/N: OUJ340085836", 0.9, 10, 120, 220, 150),
    ]
    card = parse_blocks(blocks)
    assert card is not None
    assert card.brand == "DEXP"
    assert card.model == "DF24H1"
    assert card.serial_number == "OUJ340085836"


def test_samsung_model_recovers_digit_three():
    text = 'ISAMSUNG MONENE; | UEJ2D5000PW" MCTOYHHK NWTAHWA'
    assert nz.match_brand(text) == "SAMSUNG"
    assert nz.find_model_candidate(text, brand="SAMSUNG") == "UE32D5000PW"
    model, fixed = nz.polish_model("UEJ2D5000PW", "SAMSUNG")
    assert (model, fixed) == ("UE32D5000PW", True)


def test_garbage_is_not_accepted_as_samsung_model():
    assert nz.polish_model("MCTOYHHK", "SAMSUNG") == (None, False)


def test_samsung_label_is_parsed_from_blocks():
    blocks = [
        Block("SAMSUNG", 0.99, 10, 10, 120, 40),
        Block('MONENE; | UEJ2D5000PW"', 0.7, 10, 50, 360, 80),
        Block("SERIAL NUMBER: 15193LHB800558K", 0.9, 10, 120, 400, 150),
    ]
    card = parse_blocks(blocks)
    assert card is not None
    assert card.brand == "SAMSUNG"
    assert card.model == "UE32D5000PW"
    assert card.serial_number == "15193LHB800558K"
