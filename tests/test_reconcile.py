import pytest

from app.models import Card, Confidence, Source
from app.services import pipeline, reconcile
from app.texts import render_card


def test_serials_agree_on_equal_and_lenovo_suffix():
    assert reconcile.serials_agree("61B7JAR6WWV904T4BB", "V904T4BB")
    assert reconcile.serials_agree("V9-04T4BB", "61B7JAR6WWV904T4BB")
    assert reconcile.serials_agree("ABC12345", "ABC12345")
    assert not reconcile.serials_agree("ABC12345", "XYZ99999")
    assert not reconcile.serials_agree("SHORT", "61B7JAR6WWV904T4BB")


def test_reconcile_confirms_and_keeps_longer_serial():
    primary = Card(
        brand="LENOVO",
        model="E24-10",
        serial_number="61B7JAR6WWV904T4BB",
        source=Source.BARCODE,
        confidence=Confidence.HIGH,
    )
    extra = Card(
        brand="LENOVO",
        model="E24-10",
        serial_number="V904T4BB",
        serial_display="V9-04T4BB",
        source=Source.VISION,
    )
    result = reconcile.reconcile(primary, extra)
    assert result is primary
    assert result.serial_number == "61B7JAR6WWV904T4BB"
    assert result.confidence is Confidence.HIGH
    assert any("подтвердил" in note for note in result.notes)


def test_reconcile_prefers_longer_serial_from_vision():
    primary = Card(serial_number="V904T4BB", source=Source.OCR)
    extra = Card(serial_number="61B7JAR6WWV904T4BB", source=Source.VISION)
    result = reconcile.reconcile(primary, extra)
    assert result.serial_number == "61B7JAR6WWV904T4BB"
    assert any("полный номер" in note for note in result.notes)


def test_reconcile_fills_empty_fields():
    primary = Card(serial_number="ABC12345", source=Source.BARCODE)
    extra = Card(brand="DELL", model="E2722H", serial_number="ABC12345", source=Source.VISION)
    result = reconcile.reconcile(primary, extra)
    assert result.brand == "DELL"
    assert result.model == "E2722H"
    assert result.source is Source.BARCODE
    assert any("дополнил" in note for note in result.notes)


def test_reconcile_takes_vision_model_when_serials_agree():
    """Штрихкод дал серийник, OCR подставил мусор в модель — Cloud Vision точнее."""
    primary = Card(
        brand="MSI",
        model="BZ418UALONC",
        serial_number="PD6T086500464",
        source=Source.BARCODE,
        confidence=Confidence.MEDIUM,
        barcode_payloads=["PD6T086500464"],
    )
    extra = Card(
        brand="MSI",
        model="PRO MP272L",
        serial_number="PD6T086500464",
        source=Source.VISION,
        barcode_payloads=["PD6T086500464"],
    )
    result = reconcile.reconcile(primary, extra)
    assert result.model == "PRO MP272L"
    assert result.serial_number == "PD6T086500464"
    assert any("Модель (уточнил Cloud Vision)" in note for note in result.notes)
    assert not any("расходится" in note for note in result.notes)


def test_reconcile_keeps_barcode_model_when_payload_has_it():
    primary = Card(
        brand="PHILIPS",
        model="246V5LSB/01",
        serial_number="AU0A1718003418",
        source=Source.BARCODE,
        confidence=Confidence.HIGH,
        barcode_payloads=["246V5LSB/01", "AU0A1718003418"],
    )
    extra = Card(
        brand="PHILIPS",
        model="246V5LSB",
        serial_number="AU0A1718003418",
        source=Source.VISION,
    )
    result = reconcile.reconcile(primary, extra)
    assert result.model == "246V5LSB/01"
    assert any("расходится" in note for note in result.notes)


def test_reconcile_keeps_primary_on_conflict():
    primary = Card(
        brand="DELL",
        serial_number="CN0Y71R3TV20019B13QTA01",
        source=Source.BARCODE,
        confidence=Confidence.HIGH,
    )
    extra = Card(
        brand="HP",
        serial_number="1CR9400173",
        source=Source.VISION,
    )
    result = reconcile.reconcile(primary, extra)
    assert result.brand == "DELL"
    assert result.serial_number == "CN0Y71R3TV20019B13QTA01"
    assert result.confidence is Confidence.MEDIUM
    assert any("расходится" in note for note in result.notes)


def test_reconcile_uses_vision_when_primary_missing():
    extra = Card(serial_number="ABC12345", source=Source.VISION)
    result = reconcile.reconcile(None, extra)
    assert result is extra
    assert result.notes == ["Карточка собрана Cloud Vision"]


def test_reconcile_without_vision_is_noop():
    primary = Card(serial_number="ABC12345")
    assert reconcile.reconcile(primary, None) is primary


def test_reconcile_notes_matching_barcode_payload():
    primary = Card(
        serial_number="61B7JAR6WWV904T4BB",
        source=Source.BARCODE,
        confidence=Confidence.HIGH,
        barcode_payloads=["61B7JAR6WWV904T4BB"],
    )
    extra = Card(
        serial_number="V904T4BB",
        source=Source.VISION,
        barcode_payloads=["61B7JAR6WWV904T4BB", "V904T4BB"],
    )
    result = reconcile.reconcile(primary, extra)
    assert any("подтвердил штрихкод: 61B7JAR6WWV904T4BB" in note for note in result.notes)
    assert result.serial_number == "61B7JAR6WWV904T4BB"


def test_reconcile_prefers_cleaner_samsung_serial_from_vision():
    primary = Card(
        brand="SAMSUNG",
        model="S22B370H",
        serial_number="2433HLNC8QQ394F",
        source=Source.OCR,
        confidence=Confidence.MEDIUM,
    )
    extra = Card(
        brand="SAMSUNG",
        model="S22B370H",
        serial_number="2133HLNC800394F",
        source=Source.VISION,
        barcode_payloads=["2133HLNC800394F"],
    )
    result = reconcile.reconcile(primary, extra)
    assert result.serial_number == "2133HLNC800394F"
    assert any("уточнил Cloud Vision" in note for note in result.notes)
    assert any("подтвердил штрихкод: 2133HLNC800394F" in note for note in result.notes)


def test_render_card_shows_vision_notes():
    card = Card(serial_number="ABC12345", notes=["Cloud Vision подтвердил: Серийный номер"])
    assert "Cloud Vision подтвердил: Серийный номер" in render_card(card)


@pytest.mark.asyncio
async def test_pipeline_confirms_matching_vision(monkeypatch):
    primary = Card(
        brand="LENOVO",
        model="E24-10",
        serial_number="61B7JAR6WWV904T4BB",
        source=Source.BARCODE,
        confidence=Confidence.HIGH,
    )
    monkeypatch.setattr(
        "app.services.pipeline._run_fast_contours",
        lambda _raw: (primary, Card(), None),
    )
    monkeypatch.setattr("app.services.vision.enabled", lambda: True)
    monkeypatch.setattr(
        "app.services.vision.scan",
        lambda _raw: (
            Card(brand="LENOVO", serial_number="V904T4BB", source=Source.VISION),
            "LENOVO V9-04T4BB",
        ),
    )
    result = await pipeline.process(b"img")
    assert result.card is primary
    assert result.card.serial_number == "61B7JAR6WWV904T4BB"
    assert any("подтвердил" in note for note in result.card.notes)
    assert "Cloud Vision" in (result.raw_text or "")


@pytest.mark.asyncio
async def test_pipeline_skips_vision_when_disabled(monkeypatch):
    called = False

    def fake_scan(_raw):
        nonlocal called
        called = True
        raise AssertionError("Cloud Vision не должен вызываться в тестах")

    monkeypatch.setattr("app.services.vision.enabled", lambda: False)
    monkeypatch.setattr("app.services.vision.scan", fake_scan)
    monkeypatch.setattr(
        "app.services.pipeline._run_fast_contours",
        lambda _raw: (Card(serial_number="ABC12345", source=Source.BARCODE), Card(), None),
    )
    result = await pipeline.process(b"img")
    assert not called
    assert result.card is not None
    assert result.card.notes == []


@pytest.mark.asyncio
async def test_pipeline_notes_vision_outage_on_success(monkeypatch):
    primary = Card(serial_number="ABC12345", source=Source.BARCODE)
    monkeypatch.setattr(
        "app.services.pipeline._run_fast_contours",
        lambda _raw: (primary, Card(), None),
    )
    monkeypatch.setattr("app.services.vision.enabled", lambda: True)

    def fail(_raw):
        raise pipeline.vision.VisionUnavailableError("quota")

    monkeypatch.setattr("app.services.vision.scan", fail)
    result = await pipeline.process(b"img")
    assert result.card is primary
    assert any("недоступен" in note for note in result.card.notes)
    assert result.warning is None


@pytest.mark.asyncio
async def test_pipeline_notes_when_vision_returns_text_without_card(monkeypatch):
    primary = Card(serial_number="CN0DMCK5WSL0028NCA4UA03", source=Source.BARCODE)
    monkeypatch.setattr(
        "app.services.pipeline._run_fast_contours",
        lambda _raw: (primary, Card(), None),
    )
    monkeypatch.setattr("app.services.vision.enabled", lambda: True)
    monkeypatch.setattr("app.services.vision.scan", lambda _raw: (None, "P2722H S/N:"))
    result = await pipeline.process(b"img")
    assert any("не собрал поля" in note for note in result.card.notes)
