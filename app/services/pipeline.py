import asyncio
import logging
import time
from dataclasses import dataclass

from app.models import Card
from app.services import barcode, ocr, preprocess, vlm
from app.services import normalize as nz

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    card: Card | None = None
    error: str | None = None
    warning: str | None = None
    duration_ms: int = 0


def _run_fast_contours(raw: bytes) -> tuple[Card | None, Card, str | None]:
    """Контуры №0 и №1 (блокирующие). Возвращает карточку, черновик и ошибку."""
    image = preprocess.decode_image(raw)
    if image is None:
        return None, Card(), "decode"

    variants = preprocess.build_variants(image)
    draft = Card()

    card = barcode.scan(variants)
    if card is not None:
        return card, draft, None

    ocr_card, ocr_text = ocr.scan(variants)
    if ocr_text:
        draft.brand = nz.match_brand(ocr_text)
        draft.raw_text = ocr_text
    if ocr_card is not None:
        return ocr_card, draft, None
    return None, draft, None


async def process(raw: bytes) -> PipelineResult:
    started = time.monotonic()

    card, draft, error = await asyncio.to_thread(_run_fast_contours, raw)
    if error == "decode":
        return PipelineResult(error="decode")

    warning: str | None = None
    if card is None and vlm.client.enabled:
        try:
            card = await vlm.client.scan(raw)
        except vlm.VlmUnavailableError as vlm_error:
            logger.warning("Контур №2 недоступен: %s", vlm_error)
            warning = "vlm_unavailable"

    if card is not None:
        card.merge_missing_from(draft)
        if card.raw_text is None:
            card.raw_text = draft.raw_text
        card.duration_ms = int((time.monotonic() - started) * 1000)

    return PipelineResult(
        card=card,
        warning=warning,
        duration_ms=int((time.monotonic() - started) * 1000),
    )
