import logging

import numpy as np

from app.models import Card, Confidence, Source
from app.services import normalize as nz
from app.services.preprocess import ImageVariants, rotations

logger = logging.getLogger(__name__)

try:
    import zxingcpp

    _ZXING_AVAILABLE = True
except ImportError:  # pragma: no cover
    _ZXING_AVAILABLE = False
    logger.warning("zxing-cpp не установлен, контур штрихкодов отключён")

try:
    from pyzbar import pyzbar

    _PYZBAR_AVAILABLE = True
except Exception:  # pyzbar падает с ImportError и OSError без libzbar
    _PYZBAR_AVAILABLE = False
    pyzbar = None


def available() -> bool:
    return _ZXING_AVAILABLE or _PYZBAR_AVAILABLE


def _decode_one(image: np.ndarray) -> list[str]:
    texts: list[str] = []
    if _ZXING_AVAILABLE:
        try:
            texts.extend(result.text for result in zxingcpp.read_barcodes(image) if result.text)
        except Exception as error:  # noqa: BLE001 - декодер не должен ронять обработку
            logger.debug("zxing-cpp: %s", error)
    if not texts and _PYZBAR_AVAILABLE:
        try:
            texts.extend(result.data.decode("utf-8", "ignore") for result in pyzbar.decode(image))
        except Exception as error:  # noqa: BLE001
            logger.debug("pyzbar: %s", error)
    return texts


def decode_all(variants: ImageVariants) -> list[str]:
    """Пробует декодировать коды на всех вариантах изображения и поворотах."""
    seen: list[str] = []
    for image in variants.for_barcode():
        for rotated in rotations(image):
            for text in _decode_one(rotated):
                value = text.strip()
                if value and value not in seen:
                    seen.append(value)
        if seen:
            break
    return seen


def scan(variants: ImageVariants) -> Card | None:
    if not available():
        return None
    payloads = decode_all(variants)
    if not payloads:
        return None

    service_tag: str | None = None
    serial: str | None = None
    for payload in payloads:
        value = nz.normalize_identifier(payload)
        if value is None:
            continue
        if service_tag is None and nz.is_valid_service_tag(value):
            service_tag = value
            continue
        if nz.is_valid_serial(value) and (serial is None or len(value) > len(serial)):
            serial = value

    if service_tag is None and serial is None:
        return None
    # Единственный 7-символьный код без второго кандидата трактуем как Service Tag.
    if serial is not None and service_tag is not None and serial == service_tag:
        serial = None

    return Card(
        brand=None,
        model=None,
        serial_number=serial,
        service_tag=service_tag,
        source=Source.BARCODE,
        confidence=Confidence.HIGH,
        raw_text="\n".join(payloads),
    )
