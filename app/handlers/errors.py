import logging

from aiogram import Router
from aiogram.types import CallbackQuery, ErrorEvent, Message

from app import texts

logger = logging.getLogger(__name__)
router = Router(name="errors")


@router.errors()
async def on_error(event: ErrorEvent) -> bool:
    logger.exception("Необработанная ошибка: %s", event.exception)
    update = event.update
    try:
        if isinstance(update.message, Message):
            await update.message.answer(texts.INTERNAL_ERROR)
        elif isinstance(update.callback_query, CallbackQuery):
            await update.callback_query.answer(texts.INTERNAL_ERROR, show_alert=True)
    except Exception:  # noqa: BLE001 - уведомление не должно ронять диспетчер
        logger.debug("Не удалось уведомить пользователя об ошибке")
    return True
