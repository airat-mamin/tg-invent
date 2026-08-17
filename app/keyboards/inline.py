from aiogram.types import CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.models import FIELD_TITLES, Card


def _copy_serial_button(card: Card | None) -> InlineKeyboardButton | None:
    """Кнопка копирует номер без дефисов, тогда как в тексте он показан с ними."""
    if card is None or not card.serial_number:
        return None
    if not card.serial_display or card.serial_display == card.serial_number:
        return None
    return InlineKeyboardButton(
        text="📋 S/N без дефисов", copy_text=CopyTextButton(text=card.serial_number)
    )


def confirmation(scan_id: int, card: Card | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    copy_button = _copy_serial_button(card)
    if copy_button is not None:
        builder.row(copy_button)
    builder.row(
        InlineKeyboardButton(text="✅ Верно", callback_data=f"scan:confirm:{scan_id}"),
        InlineKeyboardButton(text="✏️ Исправить", callback_data=f"scan:edit:{scan_id}"),
    )
    builder.row(InlineKeyboardButton(text="🔄 Переснять", callback_data=f"scan:discard:{scan_id}"))
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
        InlineKeyboardButton(text="📍 Расположение", callback_data=f"field:location:{scan_id}")
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
