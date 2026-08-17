from html import escape

from app.models import FIELD_TITLES, SOURCE_TITLES, Card, Confidence

START = (
    "🖥 <b>IT-Asset-OCR-Bot</b>\n\n"
    "Отправьте мне чёткое фото наклейки на мониторе/ПК, и я пришлю вам данные для копирования.\n\n"
    "Подсказки по съёмке — /help\n"
    "Последние сканирования — /last\n"
    "Выгрузка в файл — /export"
)

HELP = (
    "📷 <b>Как снимать наклейку</b>\n\n"
    "• Наклейка целиком в кадре, края не обрезаны\n"
    "• Камера параллельно наклейке, без сильного наклона\n"
    "• Без бликов от вспышки и ламп: снимайте под углом к источнику света\n"
    "• Дождитесь наводки на резкость\n"
    "• Если шрифт мелкий — отправьте фото <b>файлом без сжатия</b>\n\n"
    "Команды:\n"
    "/last — последние 10 сканирований\n"
    "/export [today|week|all] — выгрузка в CSV и XLSX\n"
    "/cancel — отменить редактирование"
)

ACCESS_DENIED = "⛔️ Доступ ограничен. Обратитесь к администратору."
RATE_LIMITED = "⏳ Слишком часто. Подождите немного и отправьте фото ещё раз."
PROCESSING = "🔍 Распознаю изображение…"
UNSUPPORTED = "Пришлите, пожалуйста, фотографию наклейки — как изображение или файлом."
TOO_LARGE = "Файл больше 20 МБ — Telegram не отдаёт такие боту. Отправьте сжатое фото."
DOWNLOAD_FAILED = "Не удалось загрузить файл из Telegram. Попробуйте ещё раз."
BROKEN_IMAGE = "Не удалось открыть изображение. Пришлите фото в JPEG или PNG."
INTERNAL_ERROR = "Произошла внутренняя ошибка. Попробуйте ещё раз позже."
VLM_UNAVAILABLE = "⚠️ Углублённое распознавание временно недоступно."
CANCELLED = "Редактирование отменено."
NOTHING_TO_EXPORT = "Пока нечего выгружать: нет подтверждённых сканирований."
EMPTY_HISTORY = "У вас пока нет подтверждённых сканирований."

FAILURE = (
    "❌ <b>Не удалось распознать наклейку</b>\n\n"
    "Проверьте, что в кадре вся наклейка, нет бликов и текст в фокусе.\n"
    "Если шрифт мелкий — отправьте фото файлом без сжатия (/help)."
)

LOW_CONFIDENCE_WARNING = "⚠️ Проверьте значения — распознавание могло быть неточным."


def render_card(card: Card) -> str:
    source = SOURCE_TITLES.get(card.source, str(card.source))
    lines = [f"🖥 <b>Оборудование распознано</b> ({source})", ""]
    for field, title in FIELD_TITLES.items():
        # Серийный номер показываем так, как он напечатан на наклейке: с дефисами
        # его удобнее сверять глазами, чем сплошную строку из штрихкода.
        value = card.serial_display or card.serial_number if field == "serial_number" else None
        value = value or getattr(card, field)
        if not value:
            continue
        line = f"• {title}: <code>{escape(str(value))}</code>"
        if field == "model" and card.model_inferred:
            line += " <i>(по номеру детали)</i>"
        lines.append(line)
    lines.append("")
    if card.confidence is not Confidence.HIGH or card.corrected_symbols:
        lines.append(LOW_CONFIDENCE_WARNING)
    lines.append("<i>Нажмите на значение, чтобы скопировать его как есть.</i>")
    if card.serial_display and card.serial_number and card.serial_display != card.serial_number:
        lines.append("<i>Кнопка ниже копирует серийный номер без дефисов.</i>")
    return "\n".join(lines)


def render_duplicate(created_at: str, username: str | None) -> str:
    who = f"@{escape(username)}" if username else "другим пользователем"
    return f"♻️ Это оборудование уже сканировалось {created_at[:10]} ({who})."
