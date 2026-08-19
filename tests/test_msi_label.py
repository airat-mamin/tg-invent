"""Разбор шильдика монитора MSI PRO MP275QPG.

На наклейке два обозначения модели: короткое MODEL NAME (3PC3) и маркетинговое
имя PRO MP275QPG. В инвентаризацию должно попадать второе. EasyOCR с языком en
читает его как PRO MP27SOPG или склеивает в VPROMP275OPG, а серийник
PC3M695500148 — как PC3M6955Q0T48.
"""

from app.services import normalize as nz
from app.services.normalize import rules
from app.services.ocr import Block, parse_blocks

rules.cache_clear()


def test_msi_template_is_loaded():
    assert rules().by_brand("MSI") is not None
    assert rules().match_serial("PC3M695500148").brand == "MSI"


def test_marketing_name_is_preferred_to_internal_code():
    text = (
        "MSI PRODUCT NAME LCD MONITOR "
        "MODEL NAME / MOPENT / 3PC3 "
        "MARKETING NAME / MAPRETWHROEOE HANNEHOBAHHE PRO MP27SOPG "
        "S/N: PC3M6955Q0T48"
    )
    assert nz.match_brand(text) == "MSI"
    assert nz.find_model_candidate(text, brand="MSI") == "PRO MP275QPG"
    assert nz.polish_model("3PC3", "MSI") == (None, False)
    assert nz.polish_model("I988", "MSI") == (None, False)
    assert nz.polish_model("BZ418UALONC", "MSI") == (None, False)
    assert nz.polish_model("PRO MP272L", "MSI") == ("PRO MP272L", False)
    assert nz.polish_model("MPG321URXDF", "MSI") == ("MPG321URXDF", False)


def test_glued_ocr_token_still_yields_marketing_name():
    text = "VPROMP275OPG SN: PC3M6955Q0T48"
    assert nz.find_model_candidate(text, brand="MSI") == "PRO MP275QPG"


def test_serial_q_and_t_become_digits():
    assert nz.polish_serial("PC3M6955Q0T48") == ("PC3M695500148", True)
    assert nz.polish_serial("PC3M695500148")[1] is False


def test_pro_mp272l_is_not_replaced_by_ocr_garbage():
    """Живой шильдик PRO MP272L: внутренний код 3PD6, EasyOCR давал BZ418UALONC."""
    text = (
        "msi LCD Monitor MARKETING NAME PRO MP272L "
        "Model Name 3PD6 S/N:PD6T086500464 CHK:ZJ4 "
        "BZ418UALONC QADGG27N755950"
    )
    assert rules().match_serial("PD6T086500464").brand == "MSI"
    assert nz.find_model_candidate(text, brand="MSI") == "PRO MP272L"
    blocks = [
        Block("msi", 0.9, 10, 10, 80, 40),
        Block("Marketing name PRO MP272L", 0.7, 10, 90, 400, 120),
        Block("Model Name 3PD6", 0.5, 10, 50, 360, 80),
        Block("S/N:PD6T086500464 CHK:ZJ4", 0.9, 10, 160, 280, 190),
        Block("BZ418UALONC", 0.4, 10, 200, 200, 230),
    ]
    card = parse_blocks(blocks)
    assert card is not None
    assert card.brand == "MSI"
    assert card.model == "PRO MP272L"
    assert card.serial_number == "PD6T086500464"


def test_msi_label_is_parsed_from_blocks():
    blocks = [
        Block("MSI", 0.9, 10, 10, 80, 40),
        Block("MODEL NAME / MOPENT / 3PC3", 0.5, 10, 50, 360, 80),
        Block("MARKETING NAME PRO MP27SOPG", 0.4, 10, 90, 400, 120),
        Block("S/N: PC3M6955Q0T48", 0.9, 10, 160, 280, 190),
    ]
    card = parse_blocks(blocks)
    assert card is not None
    assert card.brand == "MSI"
    assert card.model == "PRO MP275QPG"
    assert card.serial_number == "PC3M695500148"
