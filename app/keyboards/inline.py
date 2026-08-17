from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.models import FIELD_TITLES


def confirmation(scan_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Верно", callback_data=f"scan:confirm:{scan_id}")
    builder.button(text="✏️ Исправить", callback_data=f"scan:edit:{scan_id}")
    builder.button(text="🔄 Переснять", callback_data=f"scan:discard:{scan_id}")
    builder.adjust(2, 1)
    return builder.as_markup()


def field_choice(scan_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for field, title in FIELD_TITLES.items():
        builder.button(text=title, callback_data=f"field:{field}:{scan_id}")
    builder.button(text="📍 Расположение", callback_data=f"field:location:{scan_id}")
    builder.button(text="💾 Готово", callback_data=f"scan:done:{scan_id}")
    builder.adjust(2, 2, 1, 1)
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
