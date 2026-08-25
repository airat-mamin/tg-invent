import asyncio
import logging
from datetime import datetime, timezone
from io import BytesIO

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app import texts
from app.config import settings
from app.db.database import Database
from app.keyboards.inline import confirmation
from app.models import Card, Confidence, Source, Status
from app.services import parts, pipeline

logger = logging.getLogger(__name__)
router = Router(name="scan")

MAX_FILE_SIZE = 20 * 1024 * 1024
DOWNLOAD_ATTEMPTS = 3


async def _download(bot: Bot, file_id: str) -> bytes | None:
    delay = 1.0
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        try:
            buffer = BytesIO()
            await bot.download(file_id, destination=buffer)
            return buffer.getvalue()
        except Exception as error:  # noqa: BLE001 - сетевые сбои Telegram
            logger.warning("Скачивание не удалось (попытка %s): %s", attempt, error)
            if attempt == DOWNLOAD_ATTEMPTS:
                return None
            await asyncio.sleep(delay)
            delay *= 2
    return None


def _store_image(raw: bytes, user_id: int) -> str | None:
    if not settings.store_images:
        return None
    settings.image_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    path = settings.image_dir / f"{user_id}-{stamp}.jpg"
    path.write_bytes(raw)
    return str(path)


@router.message(F.photo)
async def handle_photo(message: Message, bot: Bot, db: Database, state: FSMContext) -> None:
    await _process(
        message, bot, db, message.photo[-1].file_id, message.photo[-1].file_size or 0, state
    )


@router.message(F.document)
async def handle_document(message: Message, bot: Bot, db: Database, state: FSMContext) -> None:
    document = message.document
    if not (document.mime_type or "").startswith("image/"):
        await message.answer(texts.UNSUPPORTED)
        return
    await _process(message, bot, db, document.file_id, document.file_size or 0, state)


@router.message()
async def handle_unsupported(message: Message) -> None:
    await message.answer(texts.UNSUPPORTED)


async def _process(
    message: Message,
    bot: Bot,
    db: Database,
    file_id: str,
    size: int,
    state: FSMContext | None = None,
) -> None:
    if state is not None:
        await state.clear()
    if size > MAX_FILE_SIZE:
        await message.answer(texts.TOO_LARGE)
        return

    status_message = await message.answer(texts.PROCESSING)
    raw = await _download(bot, file_id)
    if raw is None:
        await status_message.edit_text(texts.DOWNLOAD_FAILED)
        return

    result = await pipeline.process(raw)

    if result.error == "decode":
        await status_message.edit_text(texts.BROKEN_IMAGE)
        return

    if result.card is None:
        # Неудачные попытки сохраняются вместе со снимком: без них невозможно
        # ни посчитать долю отказов, ни разобрать, почему наклейка не прочиталась.
        image_path = _store_image(raw, message.from_user.id)
        await db.add_scan(
            Card(
                source=Source.NONE,
                confidence=Confidence.LOW,
                raw_text=result.raw_text,
                duration_ms=result.duration_ms,
            ),
            user_id=message.from_user.id,
            username=message.from_user.username,
            status=Status.DISCARDED,
            image_path=image_path,
        )
        logger.info(
            "Не распознано: user=%s за %s мс, снимок %s, текст OCR: %.200r",
            message.from_user.id,
            result.duration_ms,
            image_path or "не сохранён",
            result.raw_text or "",
        )
        failure = texts.FAILURE
        if result.warning == "vlm_unavailable":
            failure = f"{texts.VLM_UNAVAILABLE}\n\n{failure}"
        elif result.warning == "vision_unavailable":
            failure = f"{texts.VISION_UNAVAILABLE}\n\n{failure}"
        await status_message.edit_text(failure)
        return

    await parts.fill_model(result.card, db)
    image_path = _store_image(raw, message.from_user.id)
    scan_id = await db.add_scan(
        result.card,
        user_id=message.from_user.id,
        username=message.from_user.username,
        status=Status.PENDING,
        image_path=image_path,
    )
    logger.info(
        "Распознано: scan_id=%s source=%s user=%s за %s мс",
        scan_id,
        result.card.source,
        message.from_user.id,
        result.duration_ms,
    )
    await status_message.edit_text(
        texts.render_card(result.card), reply_markup=confirmation(scan_id, result.card)
    )
