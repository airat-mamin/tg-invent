"""iiyama ProLite, Samsung S22B370H и Lenovo ThinkVision E24-10."""

from app.services import normalize as nz
from app.services.normalize import rules
from app.services.ocr import Block, parse_blocks

rules.cache_clear()


def test_iiyama_does_not_take_rating_as_model():
    text = (
        "HDMI DP XB2474H5 IIYAMA PROLTE XB2474HS-B2 50/60HZ 1.SA "
        "RATING 100-240V SERIAL NO 1166911418964"
    )
    assert nz.match_brand(text) == "IIYAMA"
    assert nz.polish_model("RATING", "IIYAMA") == (None, False)
    assert nz.find_model_candidate(text, brand="IIYAMA") == "XB2474HS-B2"


def test_iiyama_label_is_parsed_from_blocks():
    blocks = [
        Block("IIYAMA PROLITE", 0.9, 10, 10, 200, 40),
        Block("XB2474HS-B2", 0.8, 10, 50, 180, 80),
        Block("RATING 100-240V", 0.7, 10, 90, 220, 120),
        Block("SERIAL NO 1166911418964", 0.95, 10, 160, 300, 190),
    ]
    card = parse_blocks(blocks)
    assert card is not None
    assert card.brand == "IIYAMA"
    assert card.model == "XB2474HS-B2"
    assert card.serial_number == "1166911418964"


def test_samsung_s22_from_garbled_ocr():
    text = (
        "COLOR DISPLAY UNIT KNMSUNG MEDEL 18228370H LS2283T0HSCI "
        "SAMSUNG ELECTRONICS CEPHAAEIN KOMEP : 2 433HLNC8QQ394F"
    )
    assert nz.match_brand(text) == "SAMSUNG"
    assert nz.polish_model("18228370H", "SAMSUNG") == ("S22B370H", True)
    assert nz.find_model_candidate(text, brand="SAMSUNG") == "S22B370H"


def test_samsung_serial_is_read_after_komep():
    blocks = [
        Block("SAMSUNG", 0.99, 10, 10, 120, 40),
        Block("S22B370H", 0.8, 10, 50, 160, 80),
        Block("KOMEP : 2 433HLNC8QQ394F", 0.6, 10, 120, 320, 150),
    ]
    card = parse_blocks(blocks)
    assert card is not None
    assert card.brand == "SAMSUNG"
    assert card.model == "S22B370H"
    assert card.serial_number.replace("Q", "0") == "2433HLNC800394F"


def test_lenovo_thinkvision_model_and_serial():
    text = "LENOVO THINKVISTON E24 10 MONITOR MODEL D17238FE0 SERIOL NUMBER: V9-04T4BB"
    assert nz.match_brand(text) == "LENOVO"
    assert nz.find_model_candidate(text, brand="LENOVO") == "E24-10"
    assert nz.polish_model("E24 10", "LENOVO") == ("E24-10", True)


def test_lenovo_label_is_parsed_from_blocks():
    blocks = [
        Block("LENOVO", 0.99, 10, 10, 100, 40),
        Block("THINKVISION E24 10", 0.8, 10, 50, 260, 80),
        Block("FRU NUMBER: 00PC193", 0.7, 10, 90, 240, 120),
        Block("SERIOL NUMBER: V9-04T4BB", 0.9, 10, 160, 280, 190),
    ]
    card = parse_blocks(blocks)
    assert card is not None
    assert card.brand == "LENOVO"
    assert card.model == "E24-10"
    assert card.serial_number == "V9-04T4BB"
    assert card.serial_number != "00PC193"


def test_iiyama_serial_typo_seral_is_accepted():
    text = "IIYAMA PROLTE XB2474HS-B2 CAUTION: SERAL NO 1166911418964 TO PREVENT"
    card = parse_blocks([Block(text, 0.9, 0, 0, 400, 40)])
    assert card is not None
    assert card.brand == "IIYAMA"
    assert card.model == "XB2474HS-B2"
    assert card.serial_number == "1166911418964"


def test_lenovo_date_of_manufacture_is_not_model():
    text = (
        "LENOVO THINKVISTON E24 10 MONITOR FRU NUMBER: OOPC193 "
        "DATE OF MANUFACTURE: 2019-08-16 SERIOL NUMBER: V9-04T4BB"
    )
    assert nz.polish_model("2019-08-16", "LENOVO") == (None, False)
    assert nz.find_model_candidate(text, brand="LENOVO") == "E24-10"
    card = parse_blocks([Block(text, 0.9, 0, 0, 400, 40)])
    assert card is not None
    assert card.model == "E24-10"
    assert card.serial_number == "V9-04T4BB"
