import cv2
import numpy as np
import pytest

from app.services import barcode, preprocess

zxingcpp = pytest.importorskip("zxingcpp")

SERIAL = "CN0Y71R3TV20019B13QT"
SERVICE_TAG = "9YSCSF3"


def _barcode_image(text: str, fmt=None) -> np.ndarray:
    fmt = fmt or zxingcpp.BarcodeFormat.Code128
    created = zxingcpp.create_barcode(text, fmt)
    return np.array(zxingcpp.write_barcode_to_image(created))


def _sticker(*codes: np.ndarray) -> np.ndarray:
    """Собирает синтетический шильдик: белый фон, штрихкоды и подписи."""
    canvas = np.full((600, 900), 255, dtype=np.uint8)
    offset = 60
    for code in codes:
        scaled = cv2.resize(code, (700, 140), interpolation=cv2.INTER_NEAREST)
        canvas[offset : offset + 140, 100:800] = scaled
        offset += 220
    cv2.putText(canvas, "DELL E2722H", (100, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.1, 0, 2)
    return cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR)


def test_barcode_contour_reads_serial():
    image = _sticker(_barcode_image(SERIAL))
    card = barcode.scan(preprocess.build_variants(image))
    assert card is not None
    assert card.serial_number == SERIAL
    assert card.confidence == "high"
    assert card.source == "barcode"


def test_barcode_contour_separates_serial_and_service_tag():
    image = _sticker(_barcode_image(SERIAL), _barcode_image(SERVICE_TAG))
    card = barcode.scan(preprocess.build_variants(image))
    assert card is not None
    assert card.serial_number == SERIAL
    assert card.service_tag == SERVICE_TAG


def test_barcode_contour_returns_none_without_codes():
    blank = np.full((600, 900, 3), 255, dtype=np.uint8)
    assert barcode.scan(preprocess.build_variants(blank)) is None


def test_qr_code_is_decoded():
    image = _sticker(_barcode_image(SERIAL, zxingcpp.BarcodeFormat.QRCode))
    card = barcode.scan(preprocess.build_variants(image))
    assert card is not None and card.serial_number == SERIAL
