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
