from app.services import normalize as nz


def test_normalize_strips_service_symbols():
    assert nz.normalize_identifier("  9yscsf3  ") == "9YSCSF3"
    assert nz.normalize_identifier("*CN0Y71R3TV*") == "CN0Y71R3TV"
    assert nz.normalize_identifier("CN0Y 71R3 TV") == "CN0Y71R3TV"


def test_cyrillic_homoglyphs_are_transliterated():
    # У и С здесь кириллические — типичный результат OCR на смешанном шрифте
    assert nz.normalize_identifier("9\u0423S\u0421SF3") == "9YSCSF3"
    assert nz.clean_text("\u0421/N: \u0410\u0412\u0421123").startswith("C/N")


def test_noise_values_become_none():
    for value in ("null", "N/A", "-", "  ", "none"):
        assert nz.normalize_value(value) is None


def test_service_tag_validation():
    assert nz.is_valid_service_tag("9YSCSF3")
    assert not nz.is_valid_service_tag("9YSCSF")
    assert not nz.is_valid_service_tag("9YSCSF34")
    assert not nz.is_valid_service_tag("9YSC-F3")


def test_serial_validation_requires_digit():
    assert nz.is_valid_serial("CN0Y71R3TV20019B13QT")
    assert nz.is_valid_serial("ABC-1234")
    assert not nz.is_valid_serial("ABCDEFGH")
    assert not nz.is_valid_serial("A1")


def test_repair_only_touches_invalid_values():
    value, fixed = nz.repair_identifier("9YSCSF3", nz.is_valid_service_tag)
    assert (value, fixed) == ("9YSCSF3", False)

    value, fixed = nz.repair_identifier("ABCDEFG", nz.is_valid_service_tag)
    assert (value, fixed) == ("ABCDEFG", False)


def test_repair_fixes_confusable_characters():
    value, fixed = nz.repair_identifier("ABCDEFGH", nz.is_valid_serial)
    assert fixed is True
    assert value is not None and any(char.isdigit() for char in value)


def test_brand_matching_tolerates_one_error():
    assert nz.match_brand("DELL INC") == "DELL"
    assert nz.match_brand("SAMSVNG ELECTRONICS") == "SAMSUNG"
    assert nz.match_brand("что-то постороннее") is None


def test_regex_extracts_dell_fields():
    text = nz.clean_text("Dell E2722H  Service Tag: 9YSCSF3  S/N: CN0Y71R3TV20019B13QT")
    assert nz.service_tag_label().search(text).group(1) == "9YSCSF3"
    assert nz.serial_label().search(text).group(1) == "CN0Y71R3TV20019B13QT"


def test_regex_tolerates_label_variants():
    variants = [
        "SERIAL NO. ABC12345",
        "SN: ABC12345",
        "S/N ABC12345",
        "SERIAL NUMBER: ABC12345",
    ]
    for variant in variants:
        match = nz.serial_label().search(nz.clean_text(variant))
        assert match is not None and match.group(1) == "ABC12345", variant


def test_dell_ppid_reveals_brand():
    assert nz.infer_brand_from_serial("CN011PWCWSL001B9BF8BA05") == "DELL"
    assert nz.infer_brand_from_serial("CN0DMCK5WSL0028NCA4UA03") == "DELL"
    assert nz.infer_brand_from_serial("ABC12345") is None
    assert nz.infer_brand_from_serial(None) is None


def test_sn_inside_a_word_is_not_a_label():
    # Реальный мусор OCR с наклейки энергоэффективности телевизора Samsung
    garbage = nz.clean_text("SHEPTTTHYECKAR SSNATSUNT ROROBNTENI UEAOHUTOOQU NEN")
    assert nz.serial_label().search(garbage) is None


def test_mac_address_is_not_a_serial():
    text = nz.clean_text("MAC: 00:1A:2B:3C:4D:5E")
    assert nz.looks_like_noise(text, "00:1A:2B:3C:4D:5E".upper())
