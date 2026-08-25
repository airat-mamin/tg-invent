"""Новые шильдики: BenQ GW2475-T, HP N246V, Dell с одним только Service Tag."""

from app.models import Card, Source
from app.services import barcode
from app.services import normalize as nz
from app.services.normalize import rules
from app.services.ocr import Block, parse_blocks

rules.cache_clear()


def test_benq_and_hp_templates_load():
    assert rules().by_brand("BENQ") is not None
    assert rules().by_brand("HP INC").brand == "HP"


def test_benq_model_id_is_not_taken_as_model():
    text = (
        "BENQ LCD MONITOR MODEL ID / KOD MODELS: GW2475-T "
        "TYPE G P/N 9H.LFELA.TBE S/N ETW8M00952019"
    )
    assert nz.match_brand(text) == "BENQ"
    assert nz.polish_model("IDI", "BENQ") == (None, False)
    assert nz.find_model_candidate(text, brand="BENQ") == "GW2475-T"


def test_benq_label_is_parsed_from_blocks():
    blocks = [
        Block("BENQ", 0.99, 10, 10, 80, 40),
        Block("MODEL ID", 0.8, 10, 50, 120, 80),
        Block("IDI", 0.4, 140, 50, 200, 80),
        Block("GW2475-T", 0.9, 10, 90, 160, 120),
        Block("S/N: ETW8M00952019", 0.95, 10, 160, 280, 190),
    ]
    card = parse_blocks(blocks)
    assert card is not None
    assert card.brand == "BENQ"
    assert card.model == "GW2475-T"
    assert card.serial_number == "ETW8M00952019"


def test_hp_product_numbers_are_not_model():
    text = (
        "HP N246V MONITOR SERIAL NO. 1CR9400173 "
        "PRODUCT NO. 3NS59AA/3NS59AS/3TL42AV 48/449/99G"
    )
    assert nz.match_brand(text) == "HP"
    assert nz.polish_model("48/449/99G", "HP") == (None, False)
    assert nz.find_model_candidate(text, brand="HP") == "N246V"


def test_hp_label_is_parsed_from_blocks():
    blocks = [
        Block("HP INC", 0.99, 10, 10, 80, 40),
        Block("HP N246V MONITOR", 0.8, 10, 50, 280, 80),
        Block("SERIAL NO. 1CR9400173", 0.95, 10, 120, 280, 150),
        Block("PRODUCT NO. 3NS59AA/3NS59AS", 0.7, 10, 160, 320, 190),
    ]
    card = parse_blocks(blocks)
    assert card is not None
    assert card.brand == "HP"
    assert card.model == "N246V"
    assert card.serial_number == "1CR9400173"


def test_revision_code_is_not_enough_to_stop_barcode_search():
    assert barcode._is_inventory_payload("A03") is False
    assert barcode._is_inventory_payload("JYK27D2") is False
    assert barcode._is_inventory_payload("CN018GJ7FCC0078BAADBA00") is True


def test_dell_part_from_new_labels():
    assert nz.part_number("CN018GJ7FCC0078BAADBA00") == ("DELL", "018GJ7")
    assert nz.model_from_part("DELL", "018GJ7") == "E2318HN"
    assert nz.display_serial("CN05FYJ56418054S15NT") == "CN-05FYJ5-64180-54S-15NT"
    assert nz.model_from_part("DELL", "05FYJ5") == "S2340LC"


def test_barcode_card_picks_up_missing_serial_from_ocr():
    barcode_card = Card(service_tag="JYK27D2", source=Source.BARCODE)
    ocr_card = Card(
        brand="DELL",
        model="E2318HN",
        serial_number="CN018GJ7FCC0078BAADBA00",
        serial_display="CN-018GJ7-FCC00-78B-AADB-A00",
        source=Source.OCR,
    )
    barcode_card.merge_missing_from(ocr_card)
    assert barcode_card.service_tag == "JYK27D2"
    assert barcode_card.serial_number == "CN018GJ7FCC0078BAADBA00"
    assert barcode_card.model == "E2318HN"
    assert barcode_card.brand == "DELL"
