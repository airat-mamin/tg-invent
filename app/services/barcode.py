import logging

import cv2
import numpy as np

from app.models import Card, Confidence, Source
from app.services import normalize as nz
from app.services.preprocess import ImageVariants, rotations

logger = logging.getLogger(__name__)

# 4–5 нужны для узкого Code128 внизу шильдика: на кадре 1280×720 штрихи уже пикселя.
UPSCALE_STEPS = (1, 2, 3)
ROI_UPSCALE_STEPS = (3, 4)

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


def _binarizers(*, thorough: bool) -> list:
    if not _ZXING_AVAILABLE:
        return []
    if thorough:
        return [
            zxingcpp.Binarizer.LocalAverage,
            zxingcpp.Binarizer.GlobalHistogram,
            zxingcpp.Binarizer.FixedThreshold,
        ]
    return [zxingcpp.Binarizer.LocalAverage]


def _decode_one(image: np.ndarray, *, thorough: bool = False, is_pure: bool = False) -> list[str]:
    texts: list[str] = []
    if _ZXING_AVAILABLE:
        for binarizer in _binarizers(thorough=thorough):
            try:
                results = zxingcpp.read_barcodes(
                    image,
                    try_rotate=True,
                    try_invert=True,
                    binarizer=binarizer,
                    is_pure=is_pure,
                )
            except Exception as error:  # noqa: BLE001 - декодер не должен ронять обработку
                logger.debug("zxing-cpp: %s", error)
                continue
            texts.extend(result.text for result in results if result.text)
            if texts:
                return texts
    if not texts and _PYZBAR_AVAILABLE:
        try:
            texts.extend(result.data.decode("utf-8", "ignore") for result in pyzbar.decode(image))
        except Exception as error:  # noqa: BLE001
            logger.debug("pyzbar: %s", error)
    return texts


def _is_inventory_payload(value: str) -> bool:
    """Короткий код вроде ревизии A03 или Service Tag ещё не повод останавливаться."""
    compact = nz.normalize_identifier(value)
    if not compact or len(compact) < 8:
        return False
    polished, _ = nz.polish_serial(compact)
    candidate = polished or compact
    return nz.is_valid_serial(candidate) or nz.rules().match_serial(candidate) is not None


def _as_gray(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return image
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def _barcode_rois(gray: np.ndarray) -> list[np.ndarray]:
    """Вырезает области, где на шильдике обычно лежит Code128.

    Lenovo, iiyama и часть Dell печатают основной код внизу слева, часто на
    белом прямоугольнике. На полном кадре 1280×720 штрихи слипаются, а на
    вырезанном фрагменте после увеличения декодер их ещё может разобрать.
    """
    height, width = gray.shape[:2]
    rois = [gray[int(height * 0.55) :, : int(width * 0.8)]]
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    for source in (mask, cv2.bitwise_not(mask)):
        contours, _ = cv2.findContours(source, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        ranked = sorted(contours, key=cv2.contourArea, reverse=True)
        for contour in ranked[:12]:
            x1, y1, box_w, box_h = cv2.boundingRect(contour)
            if box_w < 80 or not (8 <= box_h <= max(24, height // 3)):
                continue
            if box_w / max(box_h, 1) < 2.4:
                continue
            pad = max(4, box_h // 3)
            y0, y2 = max(0, y1 - pad), min(height, y1 + box_h + pad)
            x0, x2 = max(0, x1 - pad), min(width, x1 + box_w + pad)
            rois.append(gray[y0:y2, x0:x2])
            if len(rois) >= 8:
                return rois
    return rois


def _collect(texts: list[str], seen: list[str]) -> None:
    for text in texts:
        value = text.strip()
        if value and value not in seen:
            seen.append(value)


def _scan_image(
    image: np.ndarray,
    seen: list[str],
    scales: tuple[int, ...],
    *,
    rotate: bool,
    thorough: bool,
) -> bool:
    for scale in scales:
        scaled = (
            image
            if scale == 1
            else cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        )
        frames = rotations(scaled) if rotate else [scaled]
        for frame in frames:
            _collect(_decode_one(frame, thorough=thorough), seen)
            if thorough:
                _collect(_decode_one(frame, thorough=True, is_pure=True), seen)
        if any(_is_inventory_payload(item) for item in seen):
            return True
    return False


def decode_all(variants: ImageVariants) -> list[str]:
    """Пробует декодировать коды на всех вариантах изображения, масштабах и поворотах.

    Увеличение обязательно: на снимке 1280x720, где наклейка занимает четверть
    кадра, штрихи оказываются уже пикселя и декодер их не видит, хотя после
    двукратного апскейла код читается без ошибок. Останавливаемся, когда найден
    достаточно длинный идентификатор: короткий Service Tag или «A03» с ревизии
    часто читаются раньше, чем серийник на том же шильдике.

    Если на полном кадре кода нет, ищем его в типичных местах — нижняя полоса
    шильдика и светлые прямоугольники под Code128.
    """
    seen: list[str] = []
    frames = variants.for_barcode()
    for image in frames:
        if _scan_image(image, seen, UPSCALE_STEPS, rotate=True, thorough=False):
            return seen
    # Узкий Code128 на белом поле: только серый кадр, без полного перебора
    # бинаризаторов — иначе контур №0 занимает дольше, чем OCR.
    gray = _as_gray(frames[0])
    for roi in _barcode_rois(gray)[:4]:
        if min(roi.shape[:2]) < 8:
            continue
        if _scan_image(roi, seen, ROI_UPSCALE_STEPS, rotate=False, thorough=False):
            return seen
    return seen


def _accept_payload(payload: str) -> tuple[str | None, str | None, str | None]:
    """Возвращает (серийник, service tag, бренд) для одного значения штрихкода."""
    value = nz.normalize_identifier(payload)
    if value is None:
        return None, None, None
    polished, _ = nz.polish_serial(value)
    value = nz.canonical_serial(polished or value)
    if value is None:
        return None, None, None
    brand = nz.infer_brand_from_serial(value)
    serial = nz.inventory_serial(value)
    if nz.is_valid_service_tag(value) and not nz.rules().match_serial(value):
        return None, value, brand
    if serial and nz.is_valid_serial(serial):
        return serial, None, brand
    if nz.is_valid_service_tag(value):
        return None, value, brand
    return None, None, brand


def scan(variants: ImageVariants) -> Card | None:
    if not available():
        return None
    payloads = decode_all(variants)
    if not payloads:
        return None

    service_tag: str | None = None
    serial: str | None = None
    model: str | None = None
    brand: str | None = None
    serial_from_vendor = False
    for payload in payloads:
        found_serial, found_tag, found_brand = _accept_payload(payload)
        value = nz.normalize_identifier(payload)
        brand = brand or found_brand
        if found_tag and service_tag is None:
            service_tag = found_tag
        if found_serial:
            vendor_hit = bool(value) and nz.rules().match_serial(value or "") is not None
            if serial is None or (vendor_hit and not serial_from_vendor):
                serial = found_serial
                serial_from_vendor = serial_from_vendor or vendor_hit
            elif vendor_hit and len(found_serial) > len(serial or ""):
                serial = found_serial
        if model is None and value:
            match = nz.match_model_shape(value)
            if match is not None:
                brand, model = match

    if service_tag is None and serial is None:
        return None
    if serial is not None and service_tag is not None and serial == service_tag:
        serial = None

    serial = nz.canonical_serial(serial)
    return Card(
        brand=brand or nz.infer_brand_from_serial(serial),
        model=model,
        serial_number=serial,
        serial_display=nz.display_serial(serial),
        service_tag=service_tag,
        source=Source.BARCODE,
        confidence=Confidence.HIGH,
        raw_text="\n".join(payloads),
    )
