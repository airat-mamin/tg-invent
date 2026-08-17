from dataclasses import dataclass

import cv2
import numpy as np

MIN_SIDE = 1000
MAX_SIDE = 2500


@dataclass
class ImageVariants:
    """Набор представлений одного снимка для разных контуров."""

    original: np.ndarray
    gray: np.ndarray
    enhanced: np.ndarray
    binary: np.ndarray

    def for_barcode(self) -> list[np.ndarray]:
        return [self.gray, self.enhanced, self.binary]

    def for_ocr(self) -> list[np.ndarray]:
        return [self.enhanced, self.binary]


def decode_image(raw: bytes) -> np.ndarray | None:
    buffer = np.frombuffer(raw, dtype=np.uint8)
    return cv2.imdecode(buffer, cv2.IMREAD_COLOR)


def _rescale(image: np.ndarray) -> np.ndarray:
    height, width = image.shape[:2]
    smallest, largest = min(height, width), max(height, width)
    if smallest < MIN_SIDE:
        factor = MIN_SIDE / smallest
        return cv2.resize(image, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)
    if largest > MAX_SIDE:
        factor = MAX_SIDE / largest
        return cv2.resize(image, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
    return image


def _deskew(gray: np.ndarray) -> np.ndarray:
    edges = cv2.Canny(gray, 60, 180)
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 180, 120, minLineLength=gray.shape[1] // 3, maxLineGap=20
    )
    if lines is None:
        return gray
    angles = []
    for line in lines:
        x1, y1, x2, y2 = (float(value) for value in np.asarray(line).reshape(-1)[:4])
        angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        if abs(angle) <= 20:
            angles.append(angle)
    if not angles:
        return gray
    angle = float(np.median(angles))
    if abs(angle) < 0.7:
        return gray
    height, width = gray.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    return cv2.warpAffine(
        gray, matrix, (width, height), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )


def build_variants(image: np.ndarray) -> ImageVariants:
    scaled = _rescale(image)
    gray = cv2.cvtColor(scaled, cv2.COLOR_BGR2GRAY)
    gray = _deskew(gray)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    denoised = cv2.fastNlMeansDenoising(enhanced, None, 7, 7, 21)
    binary = cv2.adaptiveThreshold(
        denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 11
    )
    return ImageVariants(original=scaled, gray=gray, enhanced=enhanced, binary=binary)


def rotations(image: np.ndarray) -> list[np.ndarray]:
    return [
        image,
        cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE),
        cv2.rotate(image, cv2.ROTATE_180),
        cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE),
    ]
