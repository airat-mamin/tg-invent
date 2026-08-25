"""Определение модели по номеру детали внутри серийного номера.

У части производителей (например, Dell) номер детали зашит в серийный номер и
одинаков у одинаковых устройств. Это позволяет подставить модель там, где сам
её текст на фото не читается: он часто напечатан мелко, в тени или у края
наклейки.
"""

import logging

from app.db.database import Database
from app.models import Card
from app.services import normalize as nz

logger = logging.getLogger(__name__)

LEARNED = "learned"
MANUAL = "manual"


async def fill_model(card: Card, db: Database) -> bool:
    """Подставляет модель по номеру детали, если с наклейки её прочитать не удалось."""
    if card.model or not card.serial_number:
        return False
    pair = nz.part_number(card.serial_number)
    if pair is None:
        return False

    brand, part = pair
    model = await db.get_part_model(brand, part) or nz.model_from_part(brand, part)
    if not model:
        return False

    card.model = model
    card.model_inferred = True
    card.brand = card.brand or brand
    logger.info("Модель %s подставлена по номеру детали %s (%s)", model, part, brand)
    return True


async def remember(card: Card, db: Database, source: str) -> None:
    """Запоминает соответствие номера детали и модели, прочитанной с наклейки."""
    if not card.model or card.model_inferred or not card.serial_number:
        return
    pair = nz.part_number(card.serial_number)
    if pair is None:
        return

    brand, part = pair
    if await db.set_part_model(brand, part, card.model, source):
        logger.info(
            "Запомнено соответствие: %s %s -> %s (%s)", brand, part, card.model, source
        )


def as_yaml(rows) -> str:
    """Готовит накопленные соответствия к вставке в шаблон производителя."""
    by_brand: dict[str, list[tuple[str, str]]] = {}
    for row in rows:
        by_brand.setdefault(row["brand"], []).append((row["part"], row["model"]))

    blocks: list[str] = []
    for brand, pairs in sorted(by_brand.items()):
        lines = [f"# {brand.lower()}.yaml", "model:", "  by_part:"]
        lines.extend(f"    {part}: {model}" for part, model in sorted(pairs))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
