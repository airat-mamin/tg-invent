import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app import texts
from app.db.database import Database, row_to_card
from app.keyboards.inline import (
    field_choice,
    hide_keyboard,
    location_actions,
    room_actions,
    share_location,
)
from app.models import FIELD_TITLES, Status
from app.services import geocode, parts
from app.services import normalize as nz
from app.services.geocode import Place

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
    waiting_geo = State()
    waiting_room = State()


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
    if not row["location"]:
        await _offer_location(callback.message, db, state, scan_id, callback.from_user.id)


@router.callback_query(F.data.startswith("scan:discard:"))
async def on_discard(callback: CallbackQuery, db: Database, state: FSMContext) -> None:
    scan_id = int(callback.data.split(":")[2])
    await state.clear()
    await db.set_status(scan_id, Status.DISCARDED)
    await callback.message.edit_text(
        "🔄 Запись отброшена.\n\n" + texts.HELP.split("\n\nКоманды:")[0],
        reply_markup=None,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("scan:edit:"))
async def on_edit(callback: CallbackQuery, db: Database, state: FSMContext) -> None:
    scan_id = int(callback.data.split(":")[2])
    await state.set_data({"scan_id": scan_id, "edited": False})
    await _refresh_card(callback.message, db, scan_id)
    await callback.answer("Выберите поле для исправления")


@router.callback_query(F.data.startswith("field:"))
async def on_field(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    _, field, raw_id = callback.data.split(":")
    scan_id = int(raw_id)
    if field == "location":
        await _offer_location(callback.message, db, state, scan_id, callback.from_user.id)
        await callback.answer()
        return
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


def _place_from_mapping(data: dict) -> Place | None:
    if not data:
        return None
    place = Place(
        city=data.get("city"),
        street=data.get("street"),
        house=data.get("house"),
        latitude=data.get("latitude"),
        longitude=data.get("longitude"),
    )
    return place if place.address() or place.latitude is not None else None


def _place_from_row(row) -> Place | None:
    if row is None:
        return None
    return _place_from_mapping(dict(row))


async def _offer_location(
    message: Message, db: Database, state: FSMContext, scan_id: int, user_id: int
) -> None:
    last = _place_from_row(await db.get_user_place(user_id))
    await state.set_state(EditStates.waiting_geo)
    await state.update_data(scan_id=scan_id, place=last.to_dict() if last else None)
    # request_location в группах Telegram отклоняет: «location can be requested
    # in private chats only». Там оставляем ввод адреса текстом.
    chat_type = getattr(getattr(message, "chat", None), "type", "private")
    geo_markup = share_location() if chat_type == "private" else hide_keyboard()
    await message.answer(texts.ASK_LOCATION, reply_markup=geo_markup)
    await message.answer(
        "Либо выберите действие:",
        reply_markup=location_actions(scan_id, last.address() if last else None),
    )


async def _ask_room(
    message: Message, state: FSMContext, scan_id: int, intro: str | None = None
) -> None:
    await state.set_state(EditStates.waiting_room)
    if intro:
        await message.answer(intro, reply_markup=hide_keyboard())
    await message.answer(texts.ASK_ROOM, reply_markup=room_actions(scan_id))


async def _commit_location(
    message: Message, db: Database, state: FSMContext, user_id: int, room: str | None
) -> None:
    data = await state.get_data()
    scan_id = int(data["scan_id"])
    place = _place_from_mapping(data.get("place") or {})
    value = geocode.format_location(place, room)
    await db.update_field(scan_id, "location", value)
    if place and place.address():
        await db.save_user_place(
            user_id, place.city, place.street, place.house, place.latitude, place.longitude
        )
    await state.clear()
    row = await db.get_scan(scan_id)
    text = _render_row(row) + "\n\n" + (texts.LOCATION_SAVED if value else texts.LOCATION_SKIPPED)
    await message.answer(text, reply_markup=hide_keyboard())


@router.callback_query(F.data.startswith("loc:ask:"))
async def on_ask_location(
    callback: CallbackQuery, db: Database, state: FSMContext
) -> None:
    scan_id = int(callback.data.split(":")[2])
    await _offer_location(callback.message, db, state, scan_id, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data.startswith("loc:reuse:"))
async def on_reuse_location(callback: CallbackQuery, db: Database, state: FSMContext) -> None:
    scan_id = int(callback.data.split(":")[2])
    last = _place_from_row(await db.get_user_place(callback.from_user.id))
    if last is None:
        await callback.answer("Сохранённого адреса нет", show_alert=True)
        return
    await state.update_data(scan_id=scan_id, place=last.to_dict())
    await callback.answer()
    await _ask_room(callback.message, state, scan_id, f"Адрес: <b>{last.address()}</b>")


@router.callback_query(F.data.startswith("loc:skip:"))
async def on_skip_location(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer(texts.LOCATION_SKIPPED, reply_markup=hide_keyboard())
    await callback.answer()


@router.callback_query(F.data.startswith("loc:noroom:"))
async def on_no_room(callback: CallbackQuery, db: Database, state: FSMContext) -> None:
    await callback.answer()
    await _commit_location(callback.message, db, state, callback.from_user.id, room=None)


@router.message(EditStates.waiting_geo, F.location)
async def on_geo(message: Message, state: FSMContext) -> None:
    location = message.location
    place = await geocode.reverse_geocode(location.latitude, location.longitude)
    data = await state.get_data()
    scan_id = int(data["scan_id"])
    await state.update_data(place=place.to_dict())
    address = place.address()
    if not address:
        await message.answer(texts.GEO_FAILED, reply_markup=hide_keyboard())
        return
    await _ask_room(message, state, scan_id, f"Похоже, это <b>{address}</b>.")


@router.message(EditStates.waiting_geo, F.text)
async def on_geo_text(message: Message, state: FSMContext) -> None:
    if message.text.startswith("/"):
        return
    data = await state.get_data()
    scan_id = int(data["scan_id"])
    place = geocode.parse_typed_address(message.text)
    if not place.address():
        await message.answer(texts.GEO_FAILED, reply_markup=hide_keyboard())
        return
    await state.update_data(place=place.to_dict())
    await _ask_room(message, state, scan_id, f"Адрес: <b>{place.address()}</b>")


@router.message(EditStates.waiting_room, F.text)
async def on_room(message: Message, state: FSMContext, db: Database) -> None:
    if message.text.startswith("/"):
        return
    room = geocode.normalize_room(message.text)
    if message.text.strip() != "-" and room is None:
        await message.answer(texts.ROOM_INVALID)
        return
    await _commit_location(message, db, state, message.from_user.id, room)


@router.callback_query(F.data.startswith("scan:"))
async def on_unknown(callback: CallbackQuery) -> None:
    await callback.answer("Действие устарело, отправьте фото заново", show_alert=True)


__all__ = ["router"]
