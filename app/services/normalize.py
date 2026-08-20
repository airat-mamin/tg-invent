"""Нормализация и валидация значений с шильдика.

Правила вынесены в шаблоны (каталог `templates`): у каждого производителя свой
формат идентификаторов, и добавление нового не должно требовать правки кода.
"""

import re
from difflib import SequenceMatcher
from functools import lru_cache
from itertools import combinations, product

from app.config import settings
from app.services.vendors import Registry, load_registry

CYRILLIC_TO_LATIN = str.maketrans(
    "АВЕКМНОРСТУХасеорхуѕØø",
    "ABEKMHOPCTYXaceopxys00",
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
# (3↔J на наклейках Samsung: UE32D5000PW → UEJ2D5000PW;
#  O↔Q на MSI: PRO MP275QPG → PRO MP27SOPG / VPROMP275OPG).
MODEL_CONFUSABLES: dict[str, str | tuple[str, ...]] = {
    **CONFUSABLES,
    "J": "3",
    "3": "J",
    "O": ("0", "Q"),
    "Q": ("0", "O"),
    "1": ("I", "S"),
    "T": "7",
    "7": "T",
}
DATE_LIKE = re.compile(r"^\d{4}-\d{2}(?:-\d{2})?$")
SERIES_PREFIX = re.compile(r"^(PRO|MAG|MODERN|SMARTVIEW|MATEVIEW)(?=[A-Z0-9])")
GTIN_LENGTHS = frozenset({8, 12, 13, 14})
PRODUCT_SKU = re.compile(r"^\d[A-Z]{2}\d{2}[A-Z]{2}$")


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


def is_gtin(value: str | None) -> bool:
    """EAN/UPC с верной контрольной суммой. На Acer это штрихкод под настоящим S/N.

    13 цифр без контрольной суммы (iiyama 1166911418964) — обычный серийник.
    """
    if not value or not value.isdigit() or len(value) not in GTIN_LENGTHS:
        return False
    digits = [int(char) for char in value]
    body, check = digits[:-1], digits[-1]
    total = 0
    for index, digit in enumerate(reversed(body), start=1):
        total += digit * (3 if index % 2 else 1)
    return (10 - (total % 10)) % 10 == check


def is_product_sku(value: str | None) -> bool:
    """Артикул HP вида 7VH44AA / 8MB11AA / 3NS59AA — не серийник и не Service Tag."""
    return bool(value) and PRODUCT_SKU.fullmatch(value) is not None


def is_valid_service_tag(value: str | None) -> bool:
    if not value or rules().common.valid_service_tag.fullmatch(value) is None:
        return False
    if is_product_sku(value) or _exact_vendor_model(value):
        return False
    return True


def is_valid_serial(value: str | None) -> bool:
    if not value or not rules().common.valid_serial.fullmatch(value):
        return False
    if not any(char.isdigit() for char in value):
        return False
    if is_gtin(value) or is_product_sku(value) or _exact_vendor_model(value):
        return False
    # QR и служебные коды вроде 90106-45981: одни цифры и дефис. Настоящий
    # цифровой серийник (iiyama) длиннее 12 знаков и без дефиса.
    digits_only = re.sub(r"[^0-9]", "", value)
    if re.fullmatch(r"[\d-]+", value) and ("-" in value or len(digits_only) < 12):
        return False
    return True


def _serial_of_brand(value: str, brand: str | None) -> bool:
    """Токен — серийник этого производителя. Чужой короткий формат (Lenovo)
    не должен выбивать модель Samsung S22B370H."""
    vendor = rules().match_serial(value)
    if vendor is None:
        return False
    expected = rules().by_brand(brand) if brand else None
    if expected is None:
        return True
    return vendor.brand == expected.brand


def _looks_like_serial_token(token: str) -> bool:
    """Длинный номер с кучей цифр — серийник, даже если формат чуть не сошёлся."""
    compact = re.sub(r"[^A-Z0-9]", "", token)
    return len(compact) >= 12 and sum(char.isdigit() for char in compact) >= 5


def _exact_vendor_model(value: str) -> bool:
    """Модель по шаблону как есть, без подбора OCR-замен — иначе Service Tag Dell
    вроде 84ZCSF3 превращается в модель Philips."""
    return any(
        vendor.model_token is not None and vendor.model_token.fullmatch(value)
        for vendor in rules().vendors
    )


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
        word = word.strip("-")
        if word in known:
            return _canonical_brand(word)
    for word in words:
        if len(word) < 4:
            continue
        for brand in known:
            if len(brand) < 4 or abs(len(word) - len(brand)) > 1:
                continue
            if SequenceMatcher(None, word, brand).ratio() >= 0.80:
                return _canonical_brand(brand)
    return None


def _canonical_brand(name: str) -> str:
    vendor = rules().by_brand(name)
    return vendor.brand if vendor else name


def polish_serial(serial: str | None) -> tuple[str | None, bool]:
    """Применяет точечные правки шаблона к серийному номеру.

    Правка принимается, если после неё значение соответствует формату
    производителя. Даже когда исходная строка уже «похожа» на серийник
    (ETR4MO2620010 проходит шаблон), O после M всё равно заменяется на 0.
    Несколько правок одного вендора применяются подряд: на MSI в одном номере
    OCR одновременно путает Q с 0 и T с 1.
    """
    if not serial:
        return serial, False
    for vendor in rules().vendors:
        if vendor.serial is None:
            continue
        candidate = serial
        for fix in vendor.serial.fixes:
            candidate = fix.pattern.sub(fix.replacement, candidate)
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


def inventory_serial(serial: str | None) -> str | None:
    """Если штрихкод склеил MTM и S/N, возвращает только серийник с наклейки."""
    if not serial:
        return serial
    vendor = rules().match_serial(serial)
    if vendor is None or vendor.serial is None:
        return serial
    return vendor.serial.inventory_value(serial)


def glue_hyphen_continuations(text: str) -> str:
    """Склеивает PPID, разорванный по дефису: «CN-0DMCK5-» + «WSL00-28N-»."""
    if not text:
        return ""
    return re.sub(r"-\s+", "-", clean_text(text))


def find_serial_payload(text: str) -> str | None:
    """Ищет в тексте строку штрихкода: длинный идентификатор формата производителя.

    На Lenovo под Code128 напечатано 61B7JAR6WWV904T4BB — в инвентаризацию
    идёт эта строка целиком, как её вернул бы сканер, а не укороченный S/N.
    У Dell номер на наклейке часто режется по дефисам на три строки.
    """
    if not text:
        return None
    glued = glue_hyphen_continuations(text)
    tokens = re.findall(r"\b[A-Z0-9]{10,24}\b", clean_text(text))
    tokens += re.findall(r"\b[A-Z0-9]{10,24}\b", glued.replace("-", ""))
    tokens += re.findall(
        r"\b(?:CN|MY|TW|SG|MX|BR|IN|PH|TH|CZ|IE)-[A-Z0-9-]{10,28}",
        glued,
    )
    best: tuple[int, str] | None = None
    seen: set[str] = set()
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        polished, _ = polish_serial(token)
        candidate = polished or token
        if rules().match_serial(candidate) is None:
            continue
        value = canonical_serial(candidate)
        if not value or not is_valid_serial(value):
            continue
        score = len(value.replace("-", ""))
        if best is None or score > best[0]:
            best = (score, value)
    return best[1] if best else None


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
    vendor = rules().by_brand(brand) if brand else None
    if vendor is not None and vendor.model_token is not None:
        return vendor.model_token.fullmatch(value) is not None
    vendors = list(rules().vendors) if not brand else []
    for item in vendors:
        if item.model_token is not None and item.model_token.fullmatch(value):
            return True
    return rules().common.model_token.fullmatch(value) is not None


def _looks_like_date(value: str) -> bool:
    """Дата выпуска на шильдике (2019-08-16) не должна становиться моделью O19-08."""
    restored = value.replace(" ", "").translate(str.maketrans("OIZSB", "01258"))
    return DATE_LIKE.fullmatch(restored) is not None


def polish_model(value: str | None, brand: str | None = None) -> tuple[str | None, bool]:
    """Исправляет типичные ошибки OCR в обозначении модели по шаблону вендора."""
    normalized = normalize_value(value)
    if normalized is None or _looks_like_date(normalized):
        return None, False
    if normalized in rules().common.model_stopwords or normalized in rules().brand_names:
        return None, False
    matches: list[tuple[str, bool]] = []
    seen: set[str] = set()
    for source in _model_source_variants(normalized, brand):
        for candidate in (source, *_confusable_candidates(source, mapping=MODEL_CONFUSABLES)):
            pretty = _pretty_model(candidate)
            for item in (pretty, _extract_vendor_model(pretty, brand)):
                if not item or item in seen:
                    continue
                if is_valid_model(item) and _matches_vendor_model(item, brand):
                    seen.add(item)
                    matches.append((item, item != normalized))
    if matches:
        pretty, fixed = max(matches, key=lambda item: _rank_model(item[0], normalized))
        return pretty, fixed
    # Если производитель известен, не принимаем значение, которое не сходится
    # с его формой: иначе в карточку попадает мусор OCR вроде MCTOYHHK.
    if brand is not None and rules().by_brand(brand) and rules().by_brand(brand).model_token:
        return None, False
    pretty = _pretty_model(normalized)
    if is_valid_model(pretty) and (
        rules().common.model_token.fullmatch(pretty) or _matches_vendor_model(pretty, brand)
    ):
        return pretty, pretty != normalized
    return None, False


def _pretty_model(value: str) -> str:
    """Ставит пробел после серии и дефис в ThinkVision E24 10 → E24-10."""
    value = SERIES_PREFIX.sub(r"\1 ", value)
    value = re.sub(r"^([A-Z]\d{2,3}[A-Z]\d?)(G\d)$", r"\1 \2", value)
    return re.sub(r"^([A-Z]\d{2}) (\d{2})$", r"\1-\2", value)


def _rank_model(value: str, original: str) -> tuple[int, int, int, int]:
    """Меньше «O» (OCR путает с Q), без ложных Z/I, для Samsung S из ведущей 1."""
    compact_value = value.replace(" ", "")
    compact_orig = original.replace(" ", "")
    code = re.sub(r"^(PRO|MAG|MODERN) ?", "", compact_value)
    odd = compact_value.count("Z") + int(
        compact_value.startswith("I") and not compact_orig.startswith("I")
    )
    leading_s = int(compact_value.startswith("S") and compact_orig[:1] in "1I")
    return (-code.count("O"), -odd, leading_s, len(value))


def _model_source_variants(value: str, brand: str | None) -> list[str]:
    """Варианты, с которых OCR часто начинает Samsung: S→1/18, LS22… → S22…"""
    compact = re.sub(r"[\s/]+", "", value)
    variants: list[str] = []
    for item in (value, compact):
        if item and item not in variants:
            variants.append(item)
    if brand != "SAMSUNG":
        return variants
    extra: list[str] = []
    for src in list(variants):
        if src[:1] in "1I" and len(src) >= 8:
            extra.append("S" + src[1:])
            extra.append("S" + src[2:])
        if src.startswith("LS") and len(src) >= 9:
            extra.append(src[1:])
    for src in extra:
        if src not in variants:
            variants.append(src)
        if len(src) > 9:
            for length in (8, 9):
                clipped = src[:length]
                if clipped not in variants:
                    variants.append(clipped)
    return variants


def _extract_vendor_model(value: str, brand: str | None) -> str | None:
    """Достаёт обозначение модели из более длинного кода (LS22B370HS/CI)."""
    vendor = rules().by_brand(brand) if brand else None
    if vendor is None or vendor.model_token is None:
        return None
    inner = vendor.model_token.pattern
    if inner.startswith("^") and inner.endswith("$"):
        inner = inner[1:-1]
    match = re.search(inner, value)
    if not match or match.group(0) == value:
        return None
    # Обрывок слева должен быть префиксом линейки (L у LS22…, V у VPRO…),
    # а не случайной цифрой: иначе 1B22B370H даёт ложный B22B370H.
    if value[: match.start()].isdigit():
        return None
    return match.group(0)


def match_model_shape(value: str | None) -> tuple[str, str] | None:
    """Опознаёт обозначение модели по форме, описанной в шаблоне производителя.

    Возвращает пару (производитель, модель). Применяется к значениям, про которые
    заранее неизвестно, что это: например, к содержимому штрихкода.
    """
    if not value:
        return None
    candidate, _ = polish_model(value, None)
    if not candidate or not is_valid_model(candidate):
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

    tokens = re.findall(r"\b[A-Z0-9][A-Z0-9\-/]{3,20}\b", corpus)
    tokens += re.findall(
        r"\b(?:PRO|MAG|MPG|MODERN|SMARTVIEW|MATEVIEW)\s+[A-Z0-9][A-Z0-9\-]{0,20}\b",
        corpus,
    )
    tokens += re.findall(r"\b[A-Z]\d{2}\s+\d{2}\b", corpus)
    compact_tokens = [token.replace(" ", "") for token in tokens]
    vendor = rules().by_brand(brand)
    if vendor is not None and vendor.model_token is not None:
        inner = vendor.model_token.pattern
        if inner.startswith("^") and inner.endswith("$"):
            inner = inner[1:-1]
        bounded = re.compile(r"\b(?:" + inner + r")\b")
        for token in compact_tokens:
            serial_like, _ = polish_serial(token)
            if (
                is_product_sku(token)
                or is_gtin(token)
                or _looks_like_serial_token(token)
                or _serial_of_brand(serial_like or token, brand)
            ):
                continue
            if re.fullmatch(inner, token):
                tokens.append(token)
                continue
            for match in re.finditer(inner, token):
                # VPROMP275OPG → PROMP275OPG; не вырезать E76Y из HFNKE76YH1HPHN.
                if match.start() <= 1:
                    tokens.append(match.group(0))
        tokens += [match.group(0) for match in bounded.finditer(corpus)]

    for token in tokens:
        if token in rules().common.model_stopwords or token in rules().brand_names:
            continue
        if "/" in token or token.isdigit():
            continue
        serial_like, _ = polish_serial(token)
        if (
            is_product_sku(token)
            or is_gtin(token)
            or _looks_like_serial_token(token)
            or _serial_of_brand(serial_like or token, brand)
        ):
            continue
        if any(token in value or value in token for value in blocked if value):
            continue
        polished, _ = polish_model(token, brand)
        if not polished or not _matches_vendor_model(polished, brand):
            continue
        if (
            brand is None
            and not any(
                item.model_token and item.model_token.fullmatch(polished)
                for item in rules().vendors
            )
            and not rules().common.model_token.fullmatch(polished)
        ):
            continue
        counts[polished] = counts.get(polished, 0) + 1
    if not counts:
        return None
    collapsed = _collapse_model_aliases(counts)
    prefer_long = vendor is not None and vendor.model_token is not None
    length_key = (
        (lambda token: len(token.replace(" ", ""))) if prefer_long else (lambda token: -len(token))
    )
    best = max(collapsed, key=lambda token: (collapsed[token], length_key(token)))
    return best if is_valid_model(best) else None


def _collapse_model_aliases(counts: dict[str, int]) -> dict[str, int]:
    """Склеивает PROMP275QPG с PRO MP275QPG и отбрасывает P24H, если есть P24H G4."""
    groups: dict[str, list[tuple[str, int]]] = {}
    for token, count in counts.items():
        groups.setdefault(token.replace(" ", ""), []).append((token, count))
    merged: dict[str, int] = {}
    for items in groups.values():
        winner = max(items, key=lambda item: (" " in item[0], len(item[0]), item[1]))[0]
        merged[winner] = sum(count for _, count in items)
    compact = {token: token.replace(" ", "") for token in merged}
    filtered = {
        token: count
        for token, count in merged.items()
        if not any(
            other != token
            and compact[other].startswith(compact[token])
            and len(compact[other]) > len(compact[token])
            for other in merged
        )
    }
    return filtered or merged


def _mapping_options(char: str, pairs: dict[str, str | tuple[str, ...]]) -> tuple[str, ...]:
    raw = pairs[char]
    extras = (raw,) if isinstance(raw, str) else raw
    return (char, *extras)


def _confusable_candidates(
    value: str,
    limit: int = 96,
    mapping: dict[str, str | tuple[str, ...]] | None = None,
) -> list[str]:
    pairs = mapping or CONFUSABLES
    positions = [i for i, char in enumerate(value) if char in pairs]
    if not positions or len(positions) > 8:
        return []
    alternatives = [_mapping_options(value[i], pairs)[1:] for i in positions]
    candidates: list[str] = []
    for count in range(1, len(positions) + 1):
        for which in combinations(range(len(positions)), count):
            pools = [alternatives[index] for index in which]
            if any(not pool for pool in pools):
                continue
            for combo in product(*pools):
                chars = list(value)
                for index, char in zip(which, combo, strict=True):
                    chars[positions[index]] = char
                candidate = "".join(chars)
                if candidate != value:
                    candidates.append(candidate)
                if len(candidates) >= limit:
                    return candidates
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
