"""Наклейка монитора Philips: модель продублирована штрихкодом, метка «MODEL ID»."""

import cv2
import numpy as np
import pytest

from app.services import barcode, preprocess
from app.services import normalize as nz
from app.services.ocr import Block, parse_blocks
from tests.factories import barcode_image

zxingcpp = pytest.importorskip("zxingcpp")

MODEL = "246V5LSB/01"
SERIAL = "AU0A1718003418"


def small_label() -> np.ndarray:
    """Наклейка занимает четверть кадра — как на снимке со смартфона."""
    canvas = np.full((720, 1280, 3), 60, dtype=np.uint8)
    label = np.full((300, 480, 3), 250, dtype=np.uint8)
    for index, value in enumerate((MODEL, SERIAL)):
        code = cv2.cvtColor(barcode_image(value), cv2.COLOR_GRAY2BGR)
        code = cv2.resize(code, (420, 70), interpolation=cv2.INTER_NEAREST)
        label[60 + index * 130 : 130 + index * 130, 30:450] = code
    canvas[220:520, 400:880] = label
    return canvas


def test_model_and_serial_are_read_from_barcodes():
    card = barcode.scan(preprocess.build_variants(small_label()))
    assert card is not None
    assert card.serial_number == SERIAL
    assert card.model == MODEL
    assert card.brand == "PHILIPS"


def test_model_shape_is_recognised_from_template():
    assert nz.match_model_shape(MODEL) == ("PHILIPS", MODEL)
    assert nz.match_model_shape("328E1CA/00") == ("PHILIPS", "328E1CA/00")
    assert nz.match_model_shape(SERIAL) is None


def test_model_id_label_is_understood():
    blocks = [
        Block("MODEL ID:246V5LSB/01", 0.9, 10, 10, 320, 40),
        Block("SERIAL NUMBER:AU0A1718003418", 0.9, 10, 60, 380, 90),
    ]
    card = parse_blocks(blocks)
    assert card is not None
    assert card.serial_number == SERIAL
    assert card.model == MODEL


def test_label_word_is_not_taken_for_model():
    # До поддержки «MODEL ID» в качестве модели захватывалось слово ID
    assert nz.is_valid_model("ID") is False
    assert nz.is_valid_model("NAME") is False
