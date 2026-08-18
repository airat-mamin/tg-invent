import pytest

from app.config import settings
from app.services import normalize as nz
from app.services.vendors import TemplateError, load_registry

COMPACT = "CN0Y71R3TV20019B13QTA01"


def test_shipped_templates_load():
    registry = load_registry(settings.templates_dir)
    assert registry.by_brand("DELL") is not None
    assert registry.by_brand("MSI") is not None
    assert registry.by_brand("BENQ") is not None
    assert registry.by_brand("HP") is not None
    assert "SAMSUNG" in registry.brand_names


def test_vendor_is_recognised_by_serial_format():
    registry = load_registry(settings.templates_dir)
    assert registry.match_serial(COMPACT).brand == "DELL"
    assert registry.match_serial("ABC12345") is None


def test_part_number_and_model_come_from_template():
    assert nz.part_number(COMPACT) == ("DELL", "0Y71R3")
    assert nz.model_from_part("DELL", "0Y71R3") == "E2722H"
    assert nz.model_from_part("DELL", "НЕИЗВЕСТНО") is None
    assert nz.part_number("ABC12345") is None


def _write(tmp_path, vendor_yaml: str) -> None:
    (tmp_path / "vendors").mkdir(parents=True, exist_ok=True)
    (tmp_path / "common.yaml").write_text(
        (settings.templates_dir / "common.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "vendors" / "test.yaml").write_text(vendor_yaml, encoding="utf-8")


def test_minimal_vendor_template_is_enough(tmp_path):
    _write(tmp_path, "brand: ACME\naliases: [ACME CORP]\n")
    registry = load_registry(tmp_path)
    assert registry.by_brand("ACME CORP").brand == "ACME"
    assert registry.match_serial("ANYTHING") is None


def test_broken_regex_stops_startup(tmp_path):
    _write(tmp_path, "brand: ACME\nserial:\n  pattern: '([unclosed'\n")
    with pytest.raises(TemplateError, match="serial.pattern"):
        load_registry(tmp_path)


def test_group_sizes_must_match_length(tmp_path):
    _write(tmp_path, "brand: ACME\nserial:\n  pattern: '^A.*$'\n  groups:\n    10: [2, 3]\n")
    with pytest.raises(TemplateError, match="groups"):
        load_registry(tmp_path)


def test_missing_brand_is_reported(tmp_path):
    _write(tmp_path, "aliases: [ACME]\n")
    with pytest.raises(TemplateError, match="brand"):
        load_registry(tmp_path)


def test_missing_common_file_is_reported(tmp_path):
    with pytest.raises(TemplateError, match="общих правил"):
        load_registry(tmp_path)
