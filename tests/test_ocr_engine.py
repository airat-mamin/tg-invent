"""Медленный сквозной тест Контура №1: требует EasyOCR и загрузки моделей.

Запуск: RUN_OCR_TESTS=1 pytest tests/test_ocr_engine.py
"""

import os

import cv2
import numpy as np
import pytest

from app.services import ocr, preprocess

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_OCR_TESTS") != "1", reason="Требует EasyOCR и загрузки моделей"
)


def text_sticker() -> np.ndarray:
    canvas = np.full((520, 1000), 255, dtype=np.uint8)
    lines = [
        ("DELL", 60),
        ("MODEL: E2722H", 150),
        ("SERVICE TAG: 9YSCSF3", 240),
        ("S/N: CN0Y71R3TV20019B13QT", 330),
        ("MAC: 00:1A:2B:3C:4D:5E", 420),
    ]
    for text, y in lines:
        cv2.putText(canvas, text, (50, y), cv2.FONT_HERSHEY_SIMPLEX, 1.4, 0, 3)
    return cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR)


def test_ocr_contour_reads_synthetic_sticker(monkeypatch):
    monkeypatch.setattr(ocr.settings, "ocr_enabled", True)
    card, raw_text = ocr.scan(preprocess.build_variants(text_sticker()))

    assert card is not None, f"OCR не нашёл идентификаторы, текст: {raw_text!r}"
    assert card.brand == "DELL"
    assert card.model == "E2722H"
    assert card.service_tag == "9YSCSF3"
    # Серийный номер OCR может прочитать с путаницей O/0 — на то и уровень доверия
    assert card.serial_number is not None
    assert len(card.serial_number) == 20
    assert "MAC" not in card.serial_number
    assert ":" not in card.serial_number
