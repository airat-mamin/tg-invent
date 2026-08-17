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
    # «Service Code» намеренно не поддерживается: на шильдиках Dell так начинается
    # Express Service Code — числовой код, а не сервисный тег.
    r"(?:SERVICE\s*TAG|\bS[/\\.]?T\b)\s*[:.#№]?\s*([A-Z0-9]{7})\b"
)
SERIAL_RE = re.compile(
    # Границы слова обязательны: без них «SN» находится внутри мусорного текста
    # OCR вроде «SSNATSUNT», и из шума собирается правдоподобный серийный номер.
    r"(?:\bS[/\\.\s]?N\b|\bSERIAL\s*(?:NO\.?|NUMBER|NUM)?|序列号|序号)"
    r"\s*[:.#№]?\s*([A-Z0-9][A-Z0-9-]{4,29})\b"
)
MODEL_RE = re.compile(
    r"(?:MODEL(?:\s*(?:NO\.?|NAME))?|\bMDL\b|型号|型號)\s*[:.#№]?\s*([A-Z0-9][A-Z0-9\-/]{1,23})\b"
)

# Типовая форма обозначения модели монитора или ПК: E2722H, U2723QE, P2419HC, T3600.
MODEL_TOKEN_RE = re.compile(r"\b([A-Z]{1,3}\d{3,4}[A-Z]{0,4})\b")
MODEL_STOPWORDS = frozenset(
    {"CCC", "CE", "FCC", "EAC", "HF", "XY", "AC", "DC", "HZ", "USB", "HDMI", "LED", "LCD"}
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


# PPID Dell печатается двумя способами: слитно (CN011PWC…) и через дефисы (CN-0Y71R3-TV200-…).
# Первые два символа — код страны сборки, следом всегда идёт цифра.
DELL_COUNTRIES = "CN|MY|TW|SG|MX|BR|IN|PH|TH|CZ|IE"
DELL_PPID_RE = re.compile(rf"^(?:{DELL_COUNTRIES})-?0[A-Z0-9]{{5}}-?[A-Z0-9-]{{5,}}$")
PPID_LETTER_O_RE = re.compile(rf"^((?:{DELL_COUNTRIES})-?)O")


def polish_serial(serial: str | None) -> tuple[str | None, bool]:
    """Исправляет типичную ошибку OCR в PPID: букву O вместо нуля после кода страны."""
    if not serial or DELL_PPID_RE.match(serial):
        return serial, False
    candidate = PPID_LETTER_O_RE.sub(r"\g<1>0", serial)
    if candidate != serial and DELL_PPID_RE.match(candidate):
        return candidate, True
    return serial, False


# Группировка PPID при печати на наклейке: CN-0Y71R3-TV200-19B-13QT-A01.
PPID_GROUPS = {23: (2, 6, 5, 3, 4, 3), 22: (2, 5, 5, 3, 4, 3)}


def canonical_serial(serial: str | None) -> str | None:
    """Приводит серийный номер к машинному виду.

    Дефисы в PPID Dell — только визуальное разделение групп, в штрихкоде их нет.
    У остальных производителей дефис может быть частью номера, поэтому убираем
    его лишь тогда, когда результат опознаётся как PPID.
    """
    if not serial:
        return serial
    compact = serial.replace("-", "")
    if "-" in serial and DELL_PPID_RE.match(compact):
        return compact
    return serial


def display_serial(canonical: str | None, printed: str | None = None) -> str | None:
    """Возвращает номер в том виде, в каком он напечатан на наклейке.

    Если OCR прочитал номер с дефисами и он сходится с машинным вариантом,
    используется прочитанная разбивка, иначе группы расставляются по формату PPID.
    """
    if not canonical:
        return canonical
    if printed and "-" in printed and printed.replace("-", "") == canonical:
        return printed
    groups = PPID_GROUPS.get(len(canonical))
    if groups is None or not DELL_PPID_RE.match(canonical):
        return canonical
    parts = []
    position = 0
    for size in groups:
        parts.append(canonical[position : position + size])
        position += size
    return "-".join(parts)


def infer_brand_from_serial(serial: str | None) -> str | None:
    """Определяет бренд по формату идентификатора.

    Dell печатает на шильдиках PPID, начинающийся с кода страны и кода детали,
    поэтому по одному штрихкоду можно заполнить производителя без OCR.
    """
    if serial and 18 <= len(serial) <= 30 and DELL_PPID_RE.match(serial):
        return "DELL"
    return None


def find_model_candidate(text: str, exclude: tuple[str | None, ...] = ()) -> str | None:
    """Ищет обозначение модели, не опираясь на метку.

    На части шильдиков метка модели напечатана только на языке страны выпуска
    (например, 型号), зато само обозначение продублировано в углу наклейки.
    """
    if not text:
        return None
    corpus = clean_text(text)
    blocked = tuple(value for value in exclude if value)
    counts: dict[str, int] = {}
    positions: dict[str, int] = {}
    for match in MODEL_TOKEN_RE.finditer(corpus):
        token = match.group(1)
        if token in MODEL_STOPWORDS or token in BRANDS:
            continue
        if any(token in value for value in blocked):
            continue
        if NOISE_LABELS.search(corpus[max(0, match.start() - 20) : match.start()]):
            continue
        counts[token] = counts.get(token, 0) + 1
        positions.setdefault(token, match.start())
    if not counts:
        return None
    # Обозначение модели обычно повторяется на наклейке дважды, это лучший признак.
    best = max(counts, key=lambda token: (counts[token], -positions[token]))
    return best if is_valid_model(best) else None


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
