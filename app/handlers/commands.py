import logging
from datetime import datetime, timedelta, timezone
from html import escape

from aiogram import Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, Message

from app import texts
from app.db.database import Database
from app.export import exporter

logger = logging.getLogger(__name__)
router = Router(name="commands")

PERIODS = {"today": 1, "week": 7, "month": 30}


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(texts.START)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(texts.HELP)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(texts.CANCELLED)


@router.message(Command("last"))
async def cmd_last(message: Message, db: Database) -> None:
    rows = await db.last_scans(message.from_user.id, limit=10)
    if not rows:
        await message.answer(texts.EMPTY_HISTORY)
        return
    lines = ["🗂 <b>Последние сканирования</b>", ""]
    for row in rows:
        identifier = row["serial_display"] or row["serial_number"] or row["service_tag"] or "—"
        title = " ".join(part for part in (row["brand"], row["model"]) if part) or "Без модели"
        lines.append(
            f"• {row['created_at'][:16].replace('T', ' ')} — {escape(title)}: "
            f"<code>{escape(identifier)}</code>"
        )
    await message.answer("\n".join(lines))


@router.message(Command("export"))
async def cmd_export(
    message: Message, command: CommandObject, db: Database, is_admin: bool = False
) -> None:
    period = (command.args or "all").strip().lower()
    since = None
    if period in PERIODS:
        since = datetime.now(timezone.utc) - timedelta(days=PERIODS[period])
    rows = await db.export_rows(user_id=None if is_admin else message.from_user.id, since=since)
    if not rows:
        await message.answer(texts.NOTHING_TO_EXPORT)
        return

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    await message.answer_document(
        BufferedInputFile(exporter.to_csv(rows), filename=f"inventory-{stamp}.csv"),
        caption=f"Записей: {len(rows)}",
    )
    await message.answer_document(
        BufferedInputFile(exporter.to_xlsx(rows), filename=f"inventory-{stamp}.xlsx")
    )


@router.message(Command("stats"))
async def cmd_stats(message: Message, db: Database, is_admin: bool = False) -> None:
    if not is_admin:
        await message.answer("Команда доступна только администраторам.")
        return
    data = await db.stats()
    by_source = ", ".join(f"{key}: {value}" for key, value in data["by_source"].items()) or "—"
    by_status = ", ".join(f"{key}: {value}" for key, value in data["by_status"].items()) or "—"
    await message.answer(
        "📊 <b>Статистика</b>\n\n"
        f"Всего сканирований: {data['total']}\n"
        f"По контурам: {by_source}\n"
        f"По статусам: {by_status}\n"
        f"Среднее время обработки: {data['avg_ms']} мс"
    )
