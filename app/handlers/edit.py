import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app import texts
from app.db.database import Database, row_to_card
from app.keyboards.inline import confirmation, field_choice
from app.models import FIELD_TITLES, Status
from app.services import normalize as nz
from app.services import parts

logger = logging.getLogger(__name__)
router = Router(name="edit")

VALIDATORS = {
    "serial_number": (nz.normalize_identifier, nz.is_valid_serial, "5–30 символов A–Z, 0–9, дефис"),
    "service_tag": (nz.normalize_identifier, nz.is_valid_service_tag, "ровно 7 символов A–Z, 0–9"),
    "model": (nz.normalize_value, nz.is_valid_model, "2–25 символов"),
    "brand": (nz.normalize_value, lambda value: bool(value) and len(value) <= 30, "до 30 символов"),
    "location": (lambda value: value.strip()[:100] or None, bool, "до 100 символов"),
}


class EditStates(StatesGroup):
    waiting_value = State()


def _render_row(row) -> str:
    text = texts.render_card(row_to_card(row))
    if row["location"]:
        text += f"\n📍 {row['location']}"
    return text


async def _refresh_card(message: Message, db: Database, scan_id: int) -> None:
    row = await db.get_scan(scan_id)
    if row is None:
        return
    await message.edit_text(_render_row(row), reply_markup=field_choice(scan_id, row_to_card(row)))


@router.callback_query(F.data.startswith("scan:confirm:"))
async def on_confirm(callback: CallbackQuery, db: Database, state: FSMContext) -> None:
    scan_id = int(callback.data.split(":")[2])
    await _finalize(callback, db, state, scan_id, Status.CONFIRMED)


@router.callback_query(F.data.startswith("scan:done:"))
async def on_done(callback: CallbackQuery, db: Database, state: FSMContext) -> None:
    scan_id = int(callback.data.split(":")[2])
    data = await state.get_data()
    status = Status.CORRECTED if data.get("edited") else Status.CONFIRMED
    await _finalize(callback, db, state, scan_id, status)


async def _finalize(
    callback: CallbackQuery, db: Database, state: FSMContext, scan_id: int, status: Status
) -> None:
    await state.clear()
    row = await db.get_scan(scan_id)
    if row is None:
        await callback.answer("Запись не найдена", show_alert=True)
        return

    await db.set_status(scan_id, status)
    # Подтверждённая карточка — источник соответствия «номер детали → модель»
    # для всех таких же устройств, где модель на фото не прочитается.
    await parts.remember(row_to_card(row), db, parts.LEARNED)
    duplicate = await db.find_duplicate(row["serial_number"], row["service_tag"], scan_id)

    text = _render_row(row)
    text += "\n\n✅ Сохранено" + (" с исправлениями" if status is Status.CORRECTED else "")
    if duplicate is not None:
        text += "\n" + texts.render_duplicate(duplicate["created_at"], duplicate["tg_username"])

    await callback.message.edit_text(text, reply_markup=None)
    await callback.answer("Сохранено")


@router.callback_query(F.data.startswith("scan:discard:"))
async def on_discard(callback: CallbackQuery, db: Database, state: FSMContext) -> None:
    scan_id = int(callback.data.split(":")[2])
    await state.clear()
    await db.set_status(scan_id, Status.DISCARDED)
    await callback.message.edit_text(
        "🔄 Запись отброшена.\n\n" + texts.HELP.split("\n\nКоманды:")[0], reply_markup=None
    )
    await callback.answer()


@router.callback_query(F.data.startswith("scan:edit:"))
async def on_edit(callback: CallbackQuery, db: Database, state: FSMContext) -> None:
    scan_id = int(callback.data.split(":")[2])
    await state.set_data({"scan_id": scan_id, "edited": False})
    await _refresh_card(callback.message, db, scan_id)
    await callback.answer("Выберите поле для исправления")


@router.callback_query(F.data.startswith("field:"))
async def on_field(callback: CallbackQuery, state: FSMContext) -> None:
    _, field, raw_id = callback.data.split(":")
    scan_id = int(raw_id)
    hint = VALIDATORS[field][2]
    title = FIELD_TITLES.get(field, "Расположение")
    await state.set_state(EditStates.waiting_value)
    await state.update_data(scan_id=scan_id, field=field)
    await callback.message.answer(
        f"Введите значение для поля «{title}» ({hint}).\n"
        "Отправьте <code>-</code>, чтобы очистить поле, или /cancel для отмены."
    )
    await callback.answer()


@router.message(EditStates.waiting_value, F.text)
async def on_value(message: Message, state: FSMContext, db: Database) -> None:
    data = await state.get_data()
    field: str = data["field"]
    scan_id: int = data["scan_id"]
    normalizer, validator, hint = VALIDATORS[field]

    if message.text.strip() == "-":
        value = None
    else:
        value = normalizer(message.text)
        if not validator(value):
            await message.answer(f"Значение не подходит: ожидается {hint}. Попробуйте ещё раз.")
            return

    await db.update_field(scan_id, field, value)
    await state.update_data(edited=True)
    await state.set_state(None)

    row = await db.get_scan(scan_id)
    if field == "model" and value:
        await parts.remember(row_to_card(row), db, parts.MANUAL)
    await message.answer(_render_row(row), reply_markup=field_choice(scan_id, row_to_card(row)))


@router.callback_query(F.data.startswith("scan:"))
async def on_unknown(callback: CallbackQuery) -> None:
    await callback.answer("Действие устарело, отправьте фото заново", show_alert=True)


__all__ = ["router", "confirmation"]
