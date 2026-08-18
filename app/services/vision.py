"""Облачный OCR Google Cloud Vision: проверка и дополнение контуров №0/№1."""

from __future__ import annotations

import logging
from pathlib import Path

from app.config import settings
from app.models import Card, Source
from app.services.ocr import Block, parse_blocks

logger = logging.getLogger(__name__)

_client = None


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
        response = _annotator().document_text_detection(image=vision.Image(content=image))
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
    logger.info(
        "Cloud Vision: %s символов текста, карточка %s",
        len(full_text),
        "собрана" if card is not None else "не собралась",
    )
    return card, full_text
