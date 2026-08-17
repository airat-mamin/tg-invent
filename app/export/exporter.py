import csv
import io
from typing import Any

from openpyxl import Workbook

HEADERS = {
    "id": "ID",
    "created_at": "Дата и время (UTC)",
    "tg_user_id": "Telegram ID",
    "tg_username": "Пользователь",
    "brand": "Производитель",
    "model": "Модель",
    "serial_number": "Серийный номер",
    "service_tag": "Service Tag",
    "source": "Источник",
    "confidence": "Доверие",
    "status": "Статус",
    "location": "Расположение",
}


def to_csv(rows: list[dict[str, Any]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(HEADERS), delimiter=";", extrasaction="ignore")
    writer.writerow(HEADERS)
    writer.writerows(rows)
    # BOM нужен, чтобы Excel открывал файл в UTF-8 без перекодировки.
    return buffer.getvalue().encode("utf-8-sig")


def to_xlsx(rows: list[dict[str, Any]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Инвентаризация"
    sheet.append(list(HEADERS.values()))
    for row in rows:
        sheet.append([row.get(key) for key in HEADERS])
    for index, key in enumerate(HEADERS, start=1):
        width = max([len(HEADERS[key])] + [len(str(row.get(key) or "")) for row in rows] or [10])
        sheet.column_dimensions[sheet.cell(row=1, column=index).column_letter].width = min(
            width + 2, 40
        )
    sheet.freeze_panes = "A2"
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
