import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app import texts
from app.config import settings

logger = logging.getLogger(__name__)


class AccessMiddleware(BaseMiddleware):
    """Пропускает только пользователей из белого списка."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        if not settings.is_allowed(user.id):
            logger.warning(
                "Отклонён доступ: user_id=%s username=%s", user.id, user.username
            )
            if isinstance(event, Message):
                await event.answer(texts.ACCESS_DENIED)
            elif isinstance(event, CallbackQuery):
                await event.answer(texts.ACCESS_DENIED, show_alert=True)
            return None

        data["is_admin"] = settings.is_admin(user.id)
        return await handler(event, data)
