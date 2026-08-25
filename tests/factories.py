import cv2
import numpy as np
import pytest

zxingcpp = pytest.importorskip("zxingcpp")

SERIAL = "CN0Y71R3TV20019B13QT"
SERVICE_TAG = "9YSCSF3"


def barcode_image(text: str, fmt=None) -> np.ndarray:
    fmt = fmt or zxingcpp.BarcodeFormat.Code128
    return np.array(zxingcpp.write_barcode_to_image(zxingcpp.create_barcode(text, fmt)))


def sticker(*codes: np.ndarray) -> np.ndarray:
    """Синтетический шильдик: белый фон, штрихкоды и подпись с брендом."""
    canvas = np.full((600, 900), 255, dtype=np.uint8)
    offset = 60
    for code in codes:
        canvas[offset : offset + 140, 100:800] = cv2.resize(
            code, (700, 140), interpolation=cv2.INTER_NEAREST
        )
        offset += 220
    cv2.putText(canvas, "DELL E2722H", (100, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.1, 0, 2)
    return cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR)


def sticker_bytes(*codes: np.ndarray) -> bytes:
    return cv2.imencode(".png", sticker(*codes))[1].tobytes()
