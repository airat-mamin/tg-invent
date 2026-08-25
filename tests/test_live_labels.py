"""Живые шильдики 19.08.2026: BenQ XL2411, HP P24h/P27q, GW2475, IRBIS, Acer."""

from app.models import Card, Confidence, Source
from app.services import barcode, reconcile
from app.services import normalize as nz
from app.services.normalize import rules
from app.services.ocr import Block, parse_blocks
from app.services.vision import card_from_vision_text

rules.cache_clear()


def test_benq_serial_is_recognised_and_fragment_is_not_model():
    assert rules().match_serial("ETM5M02273SL0").brand == "BENQ"
    assert rules().match_serial("ET69M04907019").brand == "BENQ"
    assert nz.polish_serial("ETMSM02273SL0") == ("ETM5M02273SL0", True)
    assert nz.polish_model("SM0227", "BENQ") == (None, False)
    assert nz.polish_model("SO6012", "BENQ") == (None, False)
    assert nz.polish_model("XL2411-B", "BENQ") == ("XL2411-B", False)


def test_benq_xl2411_label():
    text = (
        "BenQ Model ID XL2411-B Type XL2411P "
        "P/N 9H.LGPLB.QPE S/N ETMSM02273SLØ"
    )
    assert nz.match_brand(text) == "BENQ"
    assert nz.find_model_candidate(text, brand="BENQ") == "XL2411-B"
    blocks = [
        Block("BenQ", 0.9, 10, 10, 80, 40),
        Block("Model ID XL2411-B", 0.8, 10, 50, 280, 80),
        Block("Type XL2411P", 0.7, 10, 90, 200, 120),
        Block("S/N ETMSM02273SL0", 0.9, 10, 160, 280, 190),
    ]
    card = parse_blocks(blocks)
    assert card is not None
    assert card.brand == "BENQ"
    assert card.model == "XL2411-B"
    assert card.serial_number == "ETM5M02273SL0"
    barcode_card = barcode.card_from_payloads(["ETM5M02273SL0"])
    assert barcode_card is not None
    assert barcode_card.brand == "BENQ"
    assert barcode_card.model is None
    assert barcode_card.serial_number == "ETM5M02273SL0"


def test_benq_gw2475_type_code_is_not_service_tag():
    assert barcode.card_from_payloads(["GW2475H"]) is None
    text = (
        "BenQ Model ID GW2475-T Type GW2475H "
        "P/N 9H.LFELA.TBE S/N ET69M04907019"
    )
    assert nz.find_model_candidate(text, brand="BENQ") == "GW2475-T"
    blocks = [
        Block("BenQ", 0.9, 10, 10, 80, 40),
        Block("Model ID GW2475-T", 0.8, 10, 50, 280, 80),
        Block("Type GW2475H", 0.7, 10, 90, 200, 120),
        Block("S/N ET69M04907019", 0.95, 10, 160, 280, 190),
    ]
    card = parse_blocks(blocks)
    assert card is not None
    assert card.model == "GW2475-T"
    assert card.serial_number == "ET69M04907019"
    assert card.service_tag is None


def test_hp_p24h_g4_is_not_dell():
    assert rules().match_serial("3CM0351N70").brand == "HP"
    assert nz.polish_model("P24H G4", "HP") == ("P24H G4", False)
    assert barcode._is_inventory_payload("7VH44AA") is False
    card = barcode.card_from_payloads(["3CM0351N70", "7VH44AA", "7VH44AS"])
    assert card is not None
    assert card.brand == "HP"
    assert card.serial_number == "3CM0351N70"
    assert card.service_tag is None
    assert card.model is None
    text = "hp HP P24h G4 23.8-inch Monitor Serial No.: 3CM0351N70 Product No.: 7VH44AA"
    assert nz.match_brand(text) == "HP"
    assert nz.find_model_candidate(text, brand="HP") == "P24H G4"
    primary = Card(
        brand="DELL",
        model="JCM0351NTO",
        serial_number="3CM0351N70",
        source=Source.BARCODE,
        confidence=Confidence.HIGH,
        barcode_payloads=["3CM0351N70"],
    )
    extra = Card(
        brand="HP",
        model="P24H G4",
        serial_number="3CM0351N70",
        source=Source.VISION,
    )
    result = reconcile.reconcile(primary, extra)
    assert result.brand == "HP"
    assert result.model == "P24H G4"


def test_hp_p27q_g4_serial_is_not_dell_model():
    assert rules().match_serial("CNC2480XG3").brand == "HP"
    card = barcode.card_from_payloads(["CNC2480XG3", "8MB11AA"])
    assert card is not None
    assert card.brand == "HP"
    assert card.serial_number == "CNC2480XG3"
    assert card.model is None
    assert card.service_tag is None
    text = "hp P27q G4 Serial No. CNC2480XG3 Product No. 8MB11AA"
    assert nz.find_model_candidate(text, brand="HP") == "P27Q G4"


def test_irbis_smartview_label():
    text = (
        "ЖК-монитор Модель: IRBIS SmartView 24 "
        "P/N: ISM24FIDW S/N: S061SM24FIDW0330429"
    )
    assert nz.match_brand(text) == "IRBIS"
    assert nz.polish_serial("S061SM24FIDW0330429") == ("S06ISM24FIDW0330429", True)
    assert nz.find_model_candidate(text, brand="IRBIS") == "SMARTVIEW 24"
    blocks = [
        Block("IRBIS", 0.9, 10, 10, 80, 40),
        Block("Модель: IRBIS SmartView 24", 0.8, 10, 50, 360, 90),
        Block("P/N: ISM24FIDW", 0.7, 10, 100, 220, 130),
        Block("S/N: S061SM24FIDW0330429", 0.9, 10, 140, 360, 180),
    ]
    card = parse_blocks(blocks)
    assert card is not None
    assert card.brand == "IRBIS"
    assert card.model == "SMARTVIEW 24"
    assert card.serial_number == "S06ISM24FIDW0330429"
    vision = card_from_vision_text(text, blocks)
    assert vision is not None
    assert vision.serial_number == "S06ISM24FIDW0330429"


def test_acer_ean_is_not_serial():
    assert barcode._is_inventory_payload("4712196183660") is False
    assert rules().match_serial("MMLV4EE009235009534204").brand == "ACER"
    assert barcode._is_inventory_payload("MMLV4EE009235009534204") is True
    assert barcode.card_from_payloads(["4712196183660"]) is None
    card = barcode.card_from_payloads(["MMLV4EE009235009534204", "4712196183660"])
    assert card is not None
    assert card.brand == "ACER"
    assert card.serial_number == "MMLV4EE009235009534204"
    text = (
        "acer LCD Monitor Model No. Version "
        "V235HL Serial Number MMLV4EE009235009534204 EAN 4 712196 183660"
    )
    assert nz.match_brand(text) == "ACER"
    assert nz.polish_model("VERSION", "ACER") == (None, False)
    assert nz.find_model_candidate(text, brand="ACER") == "V235HL"
    blocks = [
        Block("acer", 0.9, 10, 10, 80, 40),
        Block("Model No.", 0.8, 10, 50, 120, 80),
        Block("Version", 0.5, 140, 50, 220, 80),
        Block("V235HL", 0.9, 10, 90, 160, 120),
        Block("Serial Number MMLV4EE009235009534204", 0.9, 10, 140, 400, 180),
        Block("EAN 4712196183660", 0.9, 10, 200, 280, 230),
    ]
    parsed = parse_blocks(blocks)
    assert parsed is not None
    assert parsed.brand == "ACER"
    assert parsed.model == "V235HL"
    assert parsed.serial_number == "MMLV4EE009235009534204"


def test_asus_vw226tl_label():
    """Живой шильдик ASUS: модель VW226TL, S/N B8LMQS065420, OCR даёт 88LMQS… и NI3219."""
    assert rules().match_serial("B8LMQS065420").brand == "ASUS"
    assert nz.polish_serial("88LMQS065420") == ("B8LMQS065420", True)
    assert nz.polish_model("NI3219", "ASUS") == (None, False)
    assert nz.polish_model("VW226TL", "ASUS") == ("VW226TL", False)
    text = (
        "ASUS LCD MONITOR MODEL NO. VW226 VERSION NO.: VW226TL "
        "S/N: 88LMQS065420 8202 N13219 R31018 ASUSTEK COMPUTER INC."
    )
    assert nz.match_brand(text) == "ASUS"
    assert nz.find_model_candidate(text, brand="ASUS") == "VW226TL"
    blocks = [
        Block("ASUS", 0.9, 10, 10, 80, 40),
        Block("VW226 Version No.: VW226TL", 0.8, 10, 50, 360, 90),
        Block("S/N: 88LMQS065420", 0.95, 10, 140, 300, 180),
        Block("8202 N13219 R31018", 0.4, 10, 200, 280, 230),
    ]
    card = parse_blocks(blocks)
    assert card is not None
    assert card.brand == "ASUS"
    assert card.model == "VW226TL"
    assert card.serial_number == "B8LMQS065420"
    vision = card_from_vision_text(text, blocks)
    assert vision is not None
    assert vision.model == "VW226TL"
    assert vision.serial_number == "B8LMQS065420"


def test_benq_gw2480_serial_ends_with_q() -> None:
    """GW2480-T: напечатанный S/N оканчивается на Q, EasyOCR ставит 0 и O."""
    assert rules().match_serial("ETR4M0262001Q").brand == "BENQ"
    assert nz.polish_serial("ETR4MO2620010") == ("ETR4M02620010", True)
    text = (
        "BenQ Product Name LCD Monitor Model ID GW2480-T Type GW2480 "
        "S/N: ETR4M0262001Q P/N 9H.LGDLA.CPE"
    )
    assert nz.match_brand(text) == "BENQ"
    assert nz.find_model_candidate(text, brand="BENQ") == "GW2480-T"
    blocks = [
        Block("BenQ", 0.9, 10, 10, 80, 40),
        Block("Model ID GW2480-T", 0.8, 10, 50, 280, 80),
        Block("Type GW2480", 0.7, 10, 90, 200, 120),
        Block("S/N: ETR4M0262001Q", 0.95, 10, 160, 300, 190),
    ]
    card = parse_blocks(blocks)
    assert card is not None
    assert card.brand == "BENQ"
    assert card.model == "GW2480-T"
    assert card.serial_number == "ETR4M0262001Q"
    vision = card_from_vision_text(text, blocks)
    assert vision is not None
    assert vision.serial_number == "ETR4M0262001Q"


def test_benq_gw2480_ocr_then_vision_serial() -> None:
    """EasyOCR: O после M и хвост 0; Cloud Vision читает 0 и Q — берём Vision."""
    assert reconcile.serials_agree("ETR4MO2620010", "ETR4M0262001Q")
    ocr = Card(
        brand="BENQ",
        model="GW2480-T",
        serial_number="ETR4MO2620010",
        source=Source.OCR,
        confidence=Confidence.MEDIUM,
    )
    vision = Card(
        brand="BENQ",
        model="GW2480-T",
        serial_number="ETR4M0262001Q",
        source=Source.VISION,
    )
    rec = reconcile.reconcile(ocr, vision)
    assert rec.serial_number == "ETR4M0262001Q"
    assert any("уточнил Cloud Vision" in note for note in rec.notes)


def test_ssn24_label_from_cyrillic_model() -> None:
    """Живой шильдик Huawei: Модель:SSN-24, S/N SHQUN23616001465."""
    assert rules().match_serial("SHQUN23616001465").brand == "HUAWEI"
    assert nz.polish_model("SSN-24", "HUAWEI") == ("SSN-24", False)
    text = "S/N:SHQUN23616001465 Модель:SSN-24 HDMI CE EAC CCC"
    assert nz.match_brand(text) is None
    assert nz.find_model_candidate(text, brand="HUAWEI") == "SSN-24"
    blocks = [
        Block("S/N:SHQUN23616001465", 0.95, 10, 10, 320, 40),
        Block("Модель:SSN-24", 0.9, 330, 10, 480, 40),
    ]
    card = parse_blocks(blocks)
    assert card is not None
    assert card.brand == "HUAWEI"
    assert card.model == "SSN-24"
    assert card.serial_number == "SHQUN23616001465"
    vision = card_from_vision_text(text, blocks)
    assert vision is not None
    assert vision.brand == "HUAWEI"
    assert vision.model == "SSN-24"
    assert vision.serial_number == "SHQUN23616001465"
    barcode_card = barcode.card_from_payloads(["SHQUN23616001465"])
    assert barcode_card is not None
    assert barcode_card.brand == "HUAWEI"
    assert barcode_card.serial_number == "SHQUN23616001465"
    filled = reconcile.reconcile(barcode_card, vision)
    assert filled.brand == "HUAWEI"
    assert filled.model == "SSN-24"


def test_huawei_mateview_se_label() -> None:
    """MateView SE: S/N SHQUH…, QR 90106-45981 не серийник, RBN110N не модель."""
    assert rules().match_serial("SHQUH22915000579").brand == "HUAWEI"
    assert not nz.is_valid_serial("90106-45981")
    assert barcode.card_from_payloads(["90106-45981"]) is None
    assert nz.polish_model("RBN110N", "HUAWEI") == (None, False)
    assert nz.polish_model("MATEVIEW SE", "HUAWEI") == ("MATEVIEW SE", False)
    text = (
        "HUAWEI HUAWEI MateView SE LCD Monitor "
        "S/N:SHQUH22915000579 Made in China"
    )
    assert nz.match_brand(text) == "HUAWEI"
    assert nz.find_model_candidate(text, brand="HUAWEI") == "MATEVIEW SE"
    blocks = [
        Block("HUAWEI", 0.99, 10, 10, 120, 40),
        Block("HUAWEI MateView SE", 0.9, 10, 50, 280, 80),
        Block("S/N:SHQUH22915000579", 0.95, 300, 50, 520, 80),
    ]
    card = parse_blocks(blocks)
    assert card is not None
    assert card.brand == "HUAWEI"
    assert card.model == "MATEVIEW SE"
    assert card.serial_number == "SHQUH22915000579"


def test_digma_dm_monb_label() -> None:
    """Наклейка DIGMA: модель линейки DM-MON, бренд с шильдика, серийник с S/N."""
    assert rules().by_brand("DIGMA") is not None
    assert nz.polish_model("DM-MONB2705", "DIGMA") == ("DM-MONB2705", False)
    assert nz.polish_model("DM-MLF24C", "DIGMA") == ("DM-MLF24C", False)
    assert nz.polish_model("PROGRESS 24P401F", "DIGMA") == ("PROGRESS 24P401F", False)
    assert nz.polish_model("RBN110N", "DIGMA") == (None, False)
    text = (
        "DIGMA LCD Monitor Модель: DM-MONB2705 "
        "S/N: ABC12345XYZ Input 12V"
    )
    assert nz.match_brand(text) == "DIGMA"
    assert nz.find_model_candidate(text, brand="DIGMA") == "DM-MONB2705"
    blocks = [
        Block("DIGMA", 0.99, 10, 10, 100, 40),
        Block("Модель: DM-MONB2705", 0.9, 10, 50, 280, 80),
        Block("S/N: ABC12345XYZ", 0.95, 10, 120, 280, 150),
    ]
    card = parse_blocks(blocks)
    assert card is not None
    assert card.brand == "DIGMA"
    assert card.model == "DM-MONB2705"
    assert card.serial_number == "ABC12345XYZ"
    vision = card_from_vision_text(text, blocks)
    assert vision is not None
    assert vision.brand == "DIGMA"
    assert vision.model == "DM-MONB2705"
