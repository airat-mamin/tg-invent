import re
from difflib import SequenceMatcher
from itertools import product

BRANDS = (
    "DELL",
    "HP",
    "HEWLETT-PACKARD",
    "LENOVO",
    "SAMSUNG",
    "LG",
    "ACER",
    "ASUS",
    "PHILIPS",
    "AOC",
    "BENQ",
    "VIEWSONIC",
    "IIYAMA",
    "NEC",
    "EIZO",
    "HUAWEI",
    "XIAOMI",
    "MSI",
    "GIGABYTE",
    "DEXP",
    "IRBIS",
    "APPLE",
    "FUJITSU",
    "TOSHIBA",
)

CYRILLIC_TO_LATIN = str.maketrans(
    "АВЕКМНОРСТУХасеорхуѕ",
    "ABEKMHOPCTYXaceopxys",
)

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

SERVICE_TAG_RE = re.compile(
    r"(?:SERVICE\s*TAG|SERVICE\s*CODE|EXPRESS\s*SERVICE\s*CODE|\bS[/\\.]?T\b)"
    r"\s*[:.#№]?\s*([A-Z0-9]{7})\b"
)
SERIAL_RE = re.compile(
    r"(?:S[/\\.\s]?N|SERIAL\s*(?:NO\.?|NUMBER|NUM)?)\s*[:.#№]?\s*([A-Z0-9][A-Z0-9-]{4,29})\b"
)
MODEL_RE = re.compile(
    r"(?:MODEL(?:\s*(?:NO\.?|NAME))?|\bMDL\b)\s*[:.#№]?\s*([A-Z0-9][A-Z0-9\-/]{1,23})\b"
)

MAC_RE = re.compile(r"\b(?:[0-9A-F]{2}[:-]){5}[0-9A-F]{2}\b")
NOISE_LABELS = re.compile(r"\b(P/?N|PART\s*(?:NO|NUMBER)|FCC\s*ID|EAC|MAC|REV|LOT|BOM)\b")
NOISE_VALUES = frozenset(
    {"NULL", "NONE", "N/A", "NA", "-", "—", "UNKNOWN", "NOTFOUND", "NOT FOUND", ""}
)


def clean_text(text: str) -> str:
    """Готовит сырой текст OCR к матчингу: латиница, верхний регистр, единые пробелы."""
    return re.sub(r"[ \t]+", " ", text.translate(CYRILLIC_TO_LATIN).upper())


def normalize_value(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.translate(CYRILLIC_TO_LATIN).upper().strip()
    cleaned = cleaned.strip(":.#№*|,;()[]{}<>\"' \t\r\n")
    if cleaned in NOISE_VALUES:
        return None
    return cleaned or None


def normalize_identifier(value: str | None) -> str | None:
    cleaned = normalize_value(value)
    if cleaned is None:
        return None
    cleaned = re.sub(r"[\s_]+", "", cleaned)
    return cleaned or None


def is_valid_service_tag(value: str | None) -> bool:
    return bool(value) and re.fullmatch(r"[A-Z0-9]{7}", value or "") is not None


def is_valid_serial(value: str | None) -> bool:
    if not value or not re.fullmatch(r"[A-Z0-9][A-Z0-9-]{4,29}", value):
        return False
    return any(char.isdigit() for char in value)


def is_valid_model(value: str | None) -> bool:
    if not value or not (2 <= len(value) <= 25):
        return False
    if value in BRANDS:
        return False
    return re.fullmatch(r"[A-Z0-9][A-Z0-9\-/ ]{1,24}", value) is not None


def match_brand(text: str | None) -> str | None:
    """Находит бренд в тексте, допуская одну ошибку распознавания в слове."""
    if not text:
        return None
    words = re.findall(r"[A-Z][A-Z\-]{1,20}", clean_text(text))
    for word in words:
        if word in BRANDS:
            return word
    for word in words:
        if len(word) < 4:
            continue
        for brand in BRANDS:
            if len(brand) < 4 or abs(len(word) - len(brand)) > 1:
                continue
            if SequenceMatcher(None, word, brand).ratio() >= 0.85:
                return brand
    return None


def _confusable_candidates(value: str, limit: int = 64) -> list[str]:
    positions = [i for i, char in enumerate(value) if char in CONFUSABLES]
    if not positions or len(positions) > 6:
        return []
    options = [(char, CONFUSABLES[char]) for char in (value[i] for i in positions)]
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
    if MAC_RE.search(value):
        return True
    index = context.find(value)
    if index == -1:
        return False
    return NOISE_LABELS.search(context[max(0, index - 20) : index]) is not None
