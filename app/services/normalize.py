"""Нормализация и валидация значений с шильдика.

Правила вынесены в шаблоны (каталог `templates`): у каждого производителя свой
формат идентификаторов, и добавление нового не должно требовать правки кода.
"""

import re
from difflib import SequenceMatcher
from functools import lru_cache
from itertools import product

from app.config import settings
from app.services.vendors import Registry, load_registry

CYRILLIC_TO_LATIN = str.maketrans(
    "АВЕКМНОРСТУХасеорхуѕ",
    "ABEKMHOPCTYXaceopxys",
)

# Пары символов, которые OCR путает между собой.
CONFUSABLES = {
    "O": "0",
    "0": "O",
    "I": "1",
    "1": "I",
    "L": "1",
    "B": "8",
    "8": "B",
    "S": "5",
    "5": "S",
    "Z": "2",
    "2": "Z",
    "G": "6",
    "6": "G",
    "Q": "0",
}
# Дополнительные пары, которые OCR путает в обозначениях моделей
# (3↔J на наклейках Samsung: UE32D5000PW → UEJ2D5000PW).
MODEL_CONFUSABLES = {**CONFUSABLES, "J": "3", "3": "J"}


@lru_cache(maxsize=1)
def rules() -> Registry:
    return load_registry(settings.templates_dir)


def clean_text(text: str) -> str:
    """Готовит сырой текст OCR к матчингу: латиница, верхний регистр, единые пробелы."""
    return re.sub(r"[ \t]+", " ", text.translate(CYRILLIC_TO_LATIN).upper())


def normalize_value(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.translate(CYRILLIC_TO_LATIN).upper().strip()
    cleaned = cleaned.strip(":.#№*|,;()[]{}<>\"' \t\r\n")
    if cleaned in rules().common.noise_values:
        return None
    return cleaned or None


def normalize_identifier(value: str | None) -> str | None:
    cleaned = normalize_value(value)
    if cleaned is None:
        return None
    cleaned = re.sub(r"[\s_]+", "", cleaned)
    return cleaned or None


def is_valid_service_tag(value: str | None) -> bool:
    return bool(value) and rules().common.valid_service_tag.fullmatch(value or "") is not None


def is_valid_serial(value: str | None) -> bool:
    if not value or not rules().common.valid_serial.fullmatch(value):
        return False
    return any(char.isdigit() for char in value)


def is_valid_model(value: str | None) -> bool:
    if not value or not (2 <= len(value) <= 25):
        return False
    if value in rules().brand_names or value in rules().common.model_stopwords:
        return False
    return rules().common.valid_model.fullmatch(value) is not None


def match_brand(text: str | None) -> str | None:
    """Находит бренд в тексте, допуская одну ошибку распознавания в слове."""
    if not text:
        return None
    known = rules().brand_names
    words = re.findall(r"[A-Z][A-Z\-]{1,20}", clean_text(text))
    for word in words:
        if word in known:
            return _canonical_brand(word)
    for word in words:
        if len(word) < 4:
            continue
        for brand in known:
            if len(brand) < 4 or abs(len(word) - len(brand)) > 1:
                continue
            if SequenceMatcher(None, word, brand).ratio() >= 0.85:
                return _canonical_brand(brand)
    return None


def _canonical_brand(name: str) -> str:
    vendor = rules().by_brand(name)
    return vendor.brand if vendor else name


def polish_serial(serial: str | None) -> tuple[str | None, bool]:
    """Применяет точечные правки шаблона к серийному номеру.

    Правка принимается, только если после неё значение начинает соответствовать
    формату производителя, — иначе она была бы догадкой на пустом месте.
    """
    if not serial:
        return serial, False
    for vendor in rules().vendors:
        if vendor.serial is None or vendor.serial.matches(serial):
            continue
        for fix in vendor.serial.fixes:
            candidate = fix.pattern.sub(fix.replacement, serial)
            if candidate != serial and vendor.serial.matches(candidate):
                return candidate, True
    return serial, False


def canonical_serial(serial: str | None) -> str | None:
    """Приводит серийный номер к машинному виду.

    У Dell дефисы в PPID только разделяют группы, в штрихкоде их нет. У других
    производителей дефис может быть частью номера, поэтому убирается он лишь
    тогда, когда шаблон производителя объявил дефисы разделителями.
    """
    if not serial or "-" not in serial:
        return serial
    compact = serial.replace("-", "")
    vendor = rules().match_serial(compact)
    if vendor is not None and vendor.serial is not None and vendor.serial.hyphens_are_separators:
        return compact
    return serial


def display_serial(canonical: str | None, printed: str | None = None) -> str | None:
    """Возвращает номер в том виде, в каком он напечатан на наклейке.

    Если OCR прочитал номер с дефисами и он сходится с машинным вариантом,
    используется прочитанная разбивка, иначе группы берутся из шаблона.
    """
    if not canonical:
        return canonical
    if printed and "-" in printed and printed.replace("-", "") == canonical:
        return printed
    vendor = rules().match_serial(canonical)
    if vendor is None or vendor.serial is None:
        return canonical
    return vendor.serial.split_groups(canonical) or canonical


def infer_brand_from_serial(serial: str | None) -> str | None:
    """Определяет бренд по формату идентификатора.

    Формат PPID узнаваем сам по себе, поэтому производителя видно даже когда с
    фото удалось прочитать только штрихкод.
    """
    vendor = rules().match_serial(serial)
    return vendor.brand if vendor else None


def is_truncated_serial(value: str | None) -> bool:
    """Проверяет, не оборвано ли значение на середине известного формата.

    OCR легко теряет продолжение длинного номера: на месте дефиса он читает
    двоеточие, и от PPID остаётся только первая группа. Такой обрывок проходит
    общую валидацию, но с точки зрения формата производителя он неполон.
    """
    if not value:
        return False
    for vendor in rules().vendors:
        serial = vendor.serial
        if serial is None or serial.part_number is None or serial.matches(value):
            continue
        # Обрывок проверяется и после правок OCR: сами по себе они не применяются,
        # потому что неполное значение всё равно не сойдётся с форматом целиком.
        variants = [value] + [fix.pattern.sub(fix.replacement, value) for fix in serial.fixes]
        match = next(
            (found for found in (serial.part_number.match(item) for item in variants) if found),
            None,
        )
        # Значение оборвано, если после номера детали ничего не осталось, а формат
        # производителя требует продолжения. Если хвост есть, это чужой номер,
        # случайно похожий на начало формата.
        if match and len(value) - match.end() <= 2 and len(value) < serial.min_length:
            return True
    return False


def part_number(serial: str | None) -> tuple[str, str] | None:
    """Возвращает пару (производитель, номер детали), если формат её содержит."""
    vendor = rules().match_serial(serial)
    if vendor is None or vendor.serial is None or serial is None:
        return None
    part = vendor.serial.extract_part_number(serial)
    return (vendor.brand, part) if part else None


def _matches_vendor_model(value: str, brand: str | None) -> bool:
    vendors = [rules().by_brand(brand)] if brand else list(rules().vendors)
    vendors = [vendor for vendor in vendors if vendor is not None]
    if not vendors:
        return True
    for vendor in vendors:
        if vendor.model_token is not None and vendor.model_token.fullmatch(value):
            return True
        if vendor.model_token is None and not brand:
            continue
    return False


def polish_model(value: str | None, brand: str | None = None) -> tuple[str | None, bool]:
    """Исправляет типичные ошибки OCR в обозначении модели по шаблону вендора."""
    normalized = normalize_value(value)
    if normalized is None:
        return None, False
    if is_valid_model(normalized) and _matches_vendor_model(normalized, brand):
        return normalized, False
    for candidate in _confusable_candidates(normalized, mapping=MODEL_CONFUSABLES):
        if is_valid_model(candidate) and _matches_vendor_model(candidate, brand):
            return candidate, True
    # Если производитель известен, не принимаем значение, которое не сходится
    # с его формой: иначе в карточку попадает мусор OCR вроде MCTOYHHK.
    if brand is not None and rules().by_brand(brand) and rules().by_brand(brand).model_token:
        return None, False
    if is_valid_model(normalized):
        return normalized, False
    return None, False


def match_model_shape(value: str | None) -> tuple[str, str] | None:
    """Опознаёт обозначение модели по форме, описанной в шаблоне производителя.

    Возвращает пару (производитель, модель). Применяется к значениям, про которые
    заранее неизвестно, что это: например, к содержимому штрихкода.
    """
    if not value:
        return None
    candidate = value.upper()
    if not is_valid_model(candidate):
        return None
    for vendor in rules().vendors:
        if vendor.model_token is not None and vendor.model_token.fullmatch(candidate):
            return vendor.brand, candidate
    return None


def model_from_part(brand: str | None, part: str | None) -> str | None:
    """Ищет модель по номеру детали в шаблоне производителя."""
    vendor = rules().by_brand(brand)
    if vendor is None or not part:
        return None
    return vendor.models_by_part.get(part.upper())


def find_model_candidate(
    text: str, exclude: tuple[str | None, ...] = (), brand: str | None = None
) -> str | None:
    """Ищет обозначение модели, не опираясь на метку.

    На части шильдиков метка модели напечатана только на языке страны выпуска
    (например, 型号 или «Модель»), зато само обозначение продублировано рядом.
    Кандидаты проверяются по форме из шаблона производителя, в том числе после
    точечной правки символов, которые OCR путает между собой.
    """
    if not text:
        return None
    corpus = clean_text(text)
    blocked = tuple(value for value in exclude if value)
    counts: dict[str, int] = {}
    for token in re.findall(r"\b[A-Z0-9][A-Z0-9\-/]{3,20}\b", corpus):
        if token in rules().common.model_stopwords or token in rules().brand_names:
            continue
        if any(token in value for value in blocked):
            continue
        polished, _ = polish_model(token, brand)
        if not polished or not _matches_vendor_model(polished, brand):
            continue
        if brand is None and not any(
            vendor.model_token and vendor.model_token.fullmatch(polished)
            for vendor in rules().vendors
        ) and not rules().common.model_token.fullmatch(polished):
            continue
        counts[polished] = counts.get(polished, 0) + 1
    if not counts:
        return None
    best = max(counts, key=lambda token: (counts[token], -len(token)))
    return best if is_valid_model(best) else None


def _confusable_candidates(
    value: str, limit: int = 64, mapping: dict[str, str] | None = None
) -> list[str]:
    pairs = mapping or CONFUSABLES
    positions = [i for i, char in enumerate(value) if char in pairs]
    if not positions or len(positions) > 6:
        return []
    options = [(char, pairs[char]) for char in (value[i] for i in positions)]
    candidates: list[str] = []
    for combo in product(*options):
        chars = list(value)
        for index, char in zip(positions, combo, strict=False):
            chars[index] = char
        candidate = "".join(chars)
        if candidate != value:
            candidates.append(candidate)
        if len(candidates) >= limit:
            break
    return candidates


def repair_identifier(value: str | None, validator) -> tuple[str | None, bool]:
    """Возвращает (значение, признак коррекции символов).

    Подбор визуально схожих символов выполняется только для значений,
    не прошедших валидацию: корректные значения править нельзя.
    """
    normalized = normalize_identifier(value)
    if normalized is None:
        return None, False
    if validator(normalized):
        return normalized, False
    for candidate in _confusable_candidates(normalized):
        if validator(candidate):
            return candidate, True
    return None, False


def looks_like_noise(context: str, value: str) -> bool:
    if rules().common.mac_address.search(value):
        return True
    index = context.find(value)
    if index == -1:
        return False
    return rules().common.noise_labels.search(context[max(0, index - 20) : index]) is not None


def service_tag_label() -> re.Pattern[str]:
    return rules().common.service_tag_label


def serial_label() -> re.Pattern[str]:
    return rules().common.serial_label


def model_label() -> re.Pattern[str]:
    return rules().common.model_label
