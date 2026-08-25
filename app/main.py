import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from app.config import settings
from app.db.database import Database
from app.handlers import commands, edit, errors, scan
from app.logging_setup import setup_logging
from app.middlewares.access import AccessMiddleware
from app.middlewares.throttling import ThrottlingMiddleware
from app.services import barcode, normalize, ocr, vision, vlm

logger = logging.getLogger(__name__)

BOT_COMMANDS = [
    BotCommand(command="start", description="Начало работы"),
    BotCommand(command="help", description="Как снимать наклейку"),
    BotCommand(command="last", description="Последние сканирования"),
    BotCommand(command="export", description="Выгрузка в CSV/XLSX"),
    BotCommand(command="cancel", description="Отменить редактирование"),
]


def build_dispatcher(db: Database) -> Dispatcher:
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher["db"] = db

    for observer in (dispatcher.message, dispatcher.callback_query):
        observer.middleware(AccessMiddleware())
    dispatcher.message.middleware(ThrottlingMiddleware())

    dispatcher.include_router(errors.router)
    dispatcher.include_router(commands.router)
    dispatcher.include_router(edit.router)
    # Роутер сканирования включается последним: он содержит обработчик остальных сообщений.
    dispatcher.include_router(scan.router)
    return dispatcher


async def _warmup() -> None:
    # Шаблоны читаются первыми: ошибка в конфигурации должна останавливать запуск,
    # а не всплывать на первом же присланном фото.
    registry = normalize.rules()
    logger.info(
        "Шаблоны производителей: %s",
        ", ".join(vendor.brand for vendor in registry.vendors) or "только общие правила",
    )
    logger.info(
        "Контур №0 (штрихкоды): %s", "включён" if barcode.available() else "недоступен"
    )
    if settings.ocr_enabled:
        loaded = await asyncio.to_thread(ocr.engine.load)
        logger.info("Контур №1 (EasyOCR): %s", "готов" if loaded else "недоступен")
    else:
        logger.info("Контур №1 (EasyOCR): отключён настройками")
    if settings.vision_enabled:
        logger.info(
            "Cloud Vision: %s",
            "готов" if vision.enabled() else "ключ не найден, сверка отключена",
        )
    else:
        logger.info("Cloud Vision: отключён настройками")
    if settings.vlm_enabled:
        healthy = await vlm.client.health()
        logger.info(
            "Контур №2 (%s): %s", settings.ollama_model, "готов" if healthy else "недоступен"
        )
    else:
        logger.info("Контур №2 (VLM): отключён настройками")


async def main() -> None:
    setup_logging(settings.log_level, settings.log_json)

    if not settings.allowed_ids and not settings.admin_ids:
        logger.warning(
            "ALLOWED_USER_IDS пуст: бот отвечает всем. Заполните список перед эксплуатацией."
        )

    db = Database(settings.db_path)
    await db.connect()
    if settings.store_images and settings.image_retention_days > 0:
        removed = await db.purge_images(settings.image_retention_days, settings.image_dir)
        if removed:
            logger.info("Удалено устаревших изображений: %s", removed)

    bot = Bot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = build_dispatcher(db)

    await _warmup()
    await bot.set_my_commands(BOT_COMMANDS)
    me = await bot.get_me()
    logger.info("Бот запущен: @%s", me.username)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        await db.close()
        await bot.session.close()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt, SystemExit):
        asyncio.run(main())
