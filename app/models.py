from dataclasses import dataclass, field
from enum import StrEnum


class Source(StrEnum):
    BARCODE = "barcode"
    OCR = "ocr"
    VLM = "vlm"
    MANUAL = "manual"
    NONE = "none"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Status(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CORRECTED = "corrected"
    DISCARDED = "discarded"


FIELD_TITLES = {
    "brand": "Производитель",
    "model": "Модель",
    "serial_number": "Серийный номер",
    "service_tag": "Service Tag",
}

SOURCE_TITLES = {
    Source.BARCODE: "штрихкод",
    Source.OCR: "OCR",
    Source.VLM: "нейросеть",
    Source.MANUAL: "ручной ввод",
    Source.NONE: "не распознано",
}


@dataclass
class Card:
    """Результат распознавания одной наклейки."""

    brand: str | None = None
    model: str | None = None
    # serial_number — машинный вид (как в штрихкоде), serial_display — как напечатано.
    serial_number: str | None = None
    serial_display: str | None = None
    service_tag: str | None = None
    source: Source = Source.BARCODE
    confidence: Confidence = Confidence.LOW
    corrected_symbols: bool = False
    raw_text: str | None = None
    duration_ms: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def has_identifier(self) -> bool:
        return bool(self.serial_number or self.service_tag)

    def merge_missing_from(self, other: "Card") -> None:
        """Дополняет пустые описательные поля данными предыдущего контура."""
        for name in ("brand", "model"):
            if getattr(self, name) is None and getattr(other, name) is not None:
                setattr(self, name, getattr(other, name))
