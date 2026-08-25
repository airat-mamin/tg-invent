import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from app import texts
from app.config import settings

WINDOW_SECONDS = 60


class ThrottlingMiddleware(BaseMiddleware):
    """Ограничивает частоту тяжёлых запросов (изображений) от одного пользователя."""

    def __init__(self) -> None:
        self._hits: dict[int, deque[float]] = defaultdict(deque)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or not (event.photo or event.document):
            return await handler(event, data)

        user = data.get("event_from_user")
        if user is None or settings.rate_limit_per_minute <= 0:
            return await handler(event, data)

        now = time.monotonic()
        hits = self._hits[user.id]
        while hits and now - hits[0] > WINDOW_SECONDS:
            hits.popleft()
        if len(hits) >= settings.rate_limit_per_minute:
            await event.answer(texts.RATE_LIMITED)
            return None

        hits.append(now)
        return await handler(event, data)
