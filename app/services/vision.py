"""Облачный OCR Google Cloud Vision: проверка и дополнение контуров №0/№1.

Cloud Vision API не умеет декодировать штрихи Code128/QR: отдельного
BARCODE_DETECTION нет. Зато DOCUMENT_TEXT_DETECTION читает печатную строку
под кодом — её мы разбираем теми же правилами, что и контур №0, и сверяем
с локальным zxing.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from app.config import settings
from app.models import Card, Source
from app.services import barcode, reconcile
from app.services import normalize as nz
from app.services.ocr import Block, parse_blocks

logger = logging.getLogger(__name__)

_client = None
# Строки вроде 61B7JAR6WWV904T4BB, V9-04T4BB, JYK27D2.
_BARCODE_TOKEN = re.compile(r"\b[A-Z0-9][A-Z0-9\-]{6,40}\b")


class VisionUnavailableError(RuntimeError):
    pass


def _short_error(error: object) -> str:
    text = str(error).split("\n", 1)[0].strip()
    if "BILLING" in str(error).upper() or "billing to be enabled" in str(error).lower():
        return "нужно включить биллинг в проекте Google Cloud"
    return text[:300]


def _credentials_path() -> Path | None:
    path = settings.vision_credentials
    if not path:
        return None
    resolved = path if path.is_absolute() else Path.cwd() / path
    return resolved if resolved.is_file() else None


def enabled() -> bool:
    return settings.vision_enabled and _credentials_path() is not None


def _vertices_box(vertices) -> tuple[float, float, float, float]:
    xs = [float(getattr(point, "x", 0) or 0) for point in vertices]
    ys = [float(getattr(point, "y", 0) or 0) for point in vertices]
    if not xs or not ys:
        return 0.0, 0.0, 1.0, 1.0
    return min(xs), min(ys), max(xs), max(ys)


def _word_text(word) -> str:
    return "".join(symbol.text or "" for symbol in word.symbols)


def blocks_from_annotation(annotation) -> list[Block]:
    """Превращает ответ DOCUMENT_TEXT_DETECTION в блоки, как у EasyOCR."""
    blocks: list[Block] = []
    if annotation is None:
        return blocks
    for page in annotation.pages:
        for block in page.blocks:
            for paragraph in block.paragraphs:
                for word in paragraph.words:
                    text = _word_text(word).strip()
                    if not text:
                        continue
                    x1, y1, x2, y2 = _vertices_box(word.bounding_box.vertices)
                    blocks.append(
                        Block(
                            text=text,
                            confidence=float(getattr(word, "confidence", 0.0) or 0.9),
                            x1=x1,
                            y1=y1,
                            x2=x2,
                            y2=y2,
                        )
                    )
    return blocks


def card_from_vision_text(full_text: str, blocks: list[Block]) -> Card | None:
    card = parse_blocks(blocks) if blocks else None
    if card is None and full_text.strip():
        card = parse_blocks([Block(full_text, 0.9, 0, 0, 400, 80)])
    if card is None:
        return None
    card.source = Source.VISION
    return card


def barcode_payloads_from_text(text: str) -> list[str]:
    """Достаёт из OCR Cloud Vision строки, которые мог бы нести штрихкод или QR."""
    if not text:
        return []
    seen: list[str] = []
    for token in _BARCODE_TOKEN.findall(nz.clean_text(text)):
        serial, tag, _ = barcode._accept_payload(token)
        compact = nz.normalize_identifier(token) or ""
        letters = sum(character.isalpha() for character in compact)
        digits = sum(character.isdigit() for character in compact)
        if serial and nz.rules().match_serial(serial) is not None:
            payload = serial
        elif tag and letters >= 3 and digits >= 2:
            payload = tag
        else:
            continue
        if payload and payload not in seen:
            seen.append(payload)
    return seen


def _overlay_barcode_payloads(ocr_card: Card | None, payloads: list[str]) -> Card | None:
    extra = barcode.card_from_payloads(payloads)
    if extra is None:
        if ocr_card is not None:
            ocr_card.barcode_payloads = payloads
        return ocr_card
    extra.source = Source.VISION
    extra.barcode_payloads = payloads
    if ocr_card is None:
        return extra
    ocr_card.barcode_payloads = payloads
    if extra.serial_number:
        chosen = reconcile.prefer_serial(ocr_card.serial_number, extra.serial_number)
        if (chosen and chosen != ocr_card.serial_number) or not ocr_card.serial_number:
            ocr_card.serial_number = extra.serial_number
            ocr_card.serial_display = extra.serial_display
    ocr_card.merge_missing_from(extra)
    return ocr_card


def _annotator():
    global _client
    if _client is not None:
        return _client
    path = _credentials_path()
    if path is None:
        raise VisionUnavailableError("нет файла ключа сервисного аккаунта")
    try:
        from google.cloud import vision
    except ImportError as error:
        raise VisionUnavailableError("не установлен google-cloud-vision") from error
    try:
        _client = vision.ImageAnnotatorClient.from_service_account_file(str(path))
    except Exception as error:  # noqa: BLE001 - битый ключ или SDK
        raise VisionUnavailableError(_short_error(error)) from error
    return _client


def scan(image: bytes) -> tuple[Card | None, str]:
    """Возвращает карточку (если собралась) и полный текст Cloud Vision."""
    if not enabled():
        return None, ""
    try:
        from google.cloud import vision
    except ImportError as error:
        raise VisionUnavailableError("не установлен google-cloud-vision") from error

    try:
        response = _annotator().annotate_image(
            {
                "image": vision.Image(content=image),
                "features": [
                    {"type_": vision.Feature.Type.DOCUMENT_TEXT_DETECTION},
                ],
            }
        )
    except VisionUnavailableError:
        raise
    except Exception as error:  # noqa: BLE001 - сеть и ошибки API
        raise VisionUnavailableError(_short_error(error)) from error
    if response.error.message:
        raise VisionUnavailableError(_short_error(response.error.message))

    annotation = response.full_text_annotation
    full_text = (annotation.text if annotation else "") or ""
    if not full_text and response.text_annotations:
        full_text = response.text_annotations[0].description or ""
    blocks = blocks_from_annotation(annotation)
    card = card_from_vision_text(full_text, blocks)
    payloads = barcode_payloads_from_text(full_text)
    card = _overlay_barcode_payloads(card, payloads)
    if payloads:
        tagged = "--- barcodes ---\n" + "\n".join(payloads)
        full_text = f"{full_text}\n{tagged}" if full_text else tagged
    logger.info(
        "Cloud Vision: %s символов текста, штрихкод-строки %s, карточка %s",
        len(full_text),
        payloads or "нет",
        "собрана" if card is not None else "не собралась",
    )
    return card, full_text
