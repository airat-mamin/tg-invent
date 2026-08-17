from aiogram.types import (
    CopyTextButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.models import FIELD_TITLES, Card

COPY_BUTTON_PREFIX = "📋 S/N без дефисов: "
# Длинную подпись клиенты Telegram обрезают, поэтому номер выносим в подпись
# только пока она умещается целиком.
MAX_BUTTON_LABEL = 64


def _copy_serial_button(card: Card | None) -> InlineKeyboardButton | None:
    """Кнопка копирует номер без дефисов, тогда как в тексте он показан с ними."""
    if card is None or not card.serial_number:
        return None
    if not card.serial_display or card.serial_display == card.serial_number:
        return None
    label = f"{COPY_BUTTON_PREFIX}{card.serial_number}"
    if len(label) > MAX_BUTTON_LABEL:
        label = COPY_BUTTON_PREFIX.rstrip(": ")
    return InlineKeyboardButton(text=label, copy_text=CopyTextButton(text=card.serial_number))


def confirmation(scan_id: int, card: Card | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    copy_button = _copy_serial_button(card)
    if copy_button is not None:
        builder.row(copy_button)
    builder.row(
        InlineKeyboardButton(text="✅ Верно", callback_data=f"scan:confirm:{scan_id}"),
        InlineKeyboardButton(text="✏️ Исправить", callback_data=f"scan:edit:{scan_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="📍 Расположение", callback_data=f"loc:ask:{scan_id}"),
        InlineKeyboardButton(text="🔄 Переснять", callback_data=f"scan:discard:{scan_id}"),
    )
    return builder.as_markup()


def field_choice(scan_id: int, card: Card | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    copy_button = _copy_serial_button(card)
    if copy_button is not None:
        builder.row(copy_button)

    fields = [
        InlineKeyboardButton(text=title, callback_data=f"field:{field}:{scan_id}")
        for field, title in FIELD_TITLES.items()
    ]
    for index in range(0, len(fields), 2):
        builder.row(*fields[index : index + 2])
    builder.row(
        InlineKeyboardButton(text="📍 Расположение", callback_data=f"loc:ask:{scan_id}")
    )
    builder.row(InlineKeyboardButton(text="💾 Готово", callback_data=f"scan:done:{scan_id}"))
    return builder.as_markup()


def export_formats() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="CSV", callback_data="export:csv"),
                InlineKeyboardButton(text="XLSX", callback_data="export:xlsx"),
            ]
        ]
    )


def share_location() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📍 Отправить геопозицию", request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Или введите адрес вручную",
    )


def hide_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


def location_actions(scan_id: int, last_address: str | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if last_address:
        label = last_address if len(last_address) <= 40 else last_address[:37] + "…"
        builder.row(InlineKeyboardButton(text=f"↩ {label}", callback_data=f"loc:reuse:{scan_id}"))
    builder.row(InlineKeyboardButton(text="Пропустить", callback_data=f"loc:skip:{scan_id}"))
    return builder.as_markup()


def room_actions(scan_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Без кабинета", callback_data=f"loc:noroom:{scan_id}")]
        ]
    )
