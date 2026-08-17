import numpy as np
import pytest

from app.services import barcode, preprocess
from tests.factories import SERIAL, SERVICE_TAG, barcode_image, sticker

zxingcpp = pytest.importorskip("zxingcpp")


def test_barcode_contour_reads_serial():
    card = barcode.scan(preprocess.build_variants(sticker(barcode_image(SERIAL))))
    assert card is not None
    assert card.serial_number == SERIAL
    assert card.confidence == "high"
    assert card.source == "barcode"


def test_barcode_contour_separates_serial_and_service_tag():
    image = sticker(barcode_image(SERIAL), barcode_image(SERVICE_TAG))
    card = barcode.scan(preprocess.build_variants(image))
    assert card is not None
    assert card.serial_number == SERIAL
    assert card.service_tag == SERVICE_TAG


def test_barcode_contour_returns_none_without_codes():
    blank = np.full((600, 900, 3), 255, dtype=np.uint8)
    assert barcode.scan(preprocess.build_variants(blank)) is None


def test_qr_code_is_decoded():
    image = sticker(barcode_image(SERIAL, zxingcpp.BarcodeFormat.QRCode))
    card = barcode.scan(preprocess.build_variants(image))
    assert card is not None and card.serial_number == SERIAL
