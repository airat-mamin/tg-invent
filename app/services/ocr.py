import logging
import re
import threading
from dataclasses import dataclass
from statistics import median

import numpy as np

from app.config import settings
from app.models import Card, Confidence, Source
from app.services import normalize as nz
from app.services.preprocess import ImageVariants

logger = logging.getLogger(__name__)

SERIAL_LABEL = re.compile(r"(?:S[/\\.\s]?N|SERIAL)\s*[:.#№]?\s*$")
TAG_LABEL = re.compile(r"(?:SERVICE\s*TAG|SERVICE\s*CODE|\bS[/\\.]?T)\s*[:.#№]?\s*$")
MODEL_LABEL = re.compile(r"(?:MODEL(?:\s*(?:NO\.?|NAME))?|\bMDL\b)\s*[:.#№]?\s*$")

# Перенос длинного идентификатора на следующую строку; тильду даёт OCR вместо дефиса.
CONTINUATION_CHARS = "-~–—"

MIN_OCR_SERIAL_LENGTH = 8


@dataclass
class Block:
    text: str
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def height(self) -> float:
        return max(self.y2 - self.y1, 1.0)

    @property
    def center_y(self) -> float:
        return (self.y1 + self.y2) / 2

    @property
    def center_x(self) -> float:
        return (self.x1 + self.x2) / 2


class OcrEngine:
    """Обёртка над EasyOCR: модель грузится один раз и переиспользуется."""

    def __init__(self) -> None:
        self._reader = None
        self._lock = threading.Lock()
        self._failed = False

    @property
    def enabled(self) -> bool:
        return settings.ocr_enabled and not self._failed

    def load(self) -> bool:
        if not self.enabled:
            return False
        if self._reader is not None:
            return True
        with self._lock:
            if self._reader is not None:
                return True
            try:
                import easyocr

                logger.info("Загрузка моделей EasyOCR (%s)…", settings.ocr_langs)
                self._reader = easyocr.Reader(settings.ocr_lang_list, gpu=False, verbose=False)
                logger.info("EasyOCR готов")
            except Exception as error:  # noqa: BLE001 - контур опционален
                self._failed = True
                logger.warning("EasyOCR недоступен, контур №1 отключён: %s", error)
                return False
        return True

    def read(self, image: np.ndarray) -> list[Block]:
        if not self.load() or self._reader is None:
            return []
        blocks: list[Block] = []
        for box, text, confidence in self._reader.readtext(image):
            xs = [point[0] for point in box]
            ys = [point[1] for point in box]
            blocks.append(
                Block(
                    text=nz.clean_text(str(text)),
                    confidence=float(confidence),
                    x1=float(min(xs)),
                    y1=float(min(ys)),
                    x2=float(max(xs)),
                    y2=float(max(ys)),
                )
            )
        return blocks


engine = OcrEngine()


def _neighbour_value(blocks: list[Block], label: Block) -> str | None:
    """Ищет значение в блоке справа или снизу от метки."""
    candidates: list[tuple[float, Block]] = []
    for block in blocks:
        if block is label or not block.text:
            continue
        right = (
            block.x1 >= label.x2 - label.height * 0.2
            and abs(block.center_y - label.center_y) <= label.height * 0.8
        )
        below = (
            block.y1 >= label.y2 - label.height * 0.2
            and block.y1 - label.y2 <= label.height * 1.5
            and abs(block.center_x - label.center_x)
            <= max(label.x2 - label.x1, block.x2 - block.x1)
        )
        if right:
            candidates.append((block.x1 - label.x2, block))
        elif below:
            candidates.append((label.height + block.y1 - label.y2, block))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1].text


def _search_by_labels(blocks: list[Block], pattern: re.Pattern[str]) -> str | None:
    for block in blocks:
        if pattern.search(block.text):
            value = _neighbour_value(blocks, block)
            if value:
                return value.split()[0] if " " in value else value
    return None


def _merge(first: Block, second: Block, separator: str) -> Block:
    return Block(
        text=f"{first.text}{separator}{second.text}",
        confidence=min(first.confidence, second.confidence),
        x1=min(first.x1, second.x1),
        y1=min(first.y1, second.y1),
        x2=max(first.x2, second.x2),
        y2=max(first.y2, second.y2),
    )


def _continuation_parent(blocks: list[Block], block: Block, height: float) -> Block | None:
    """Находит строку, продолжением которой является блок, начинающийся с дефиса."""
    candidates = [
        candidate
        for candidate in blocks
        if abs(candidate.x1 - block.x1) <= height * 1.5
        and 0 <= block.y1 - candidate.y2 <= height * 2
    ]
    return max(candidates, key=lambda candidate: candidate.y2) if candidates else None


def group_blocks(blocks: list[Block]) -> list[Block]:
    """Приводит блоки к порядку чтения и склеивает разорванные надписи.

    EasyOCR возвращает блоки в порядке детекции и дробит текст по пробелам, поэтому
    метка «Service Tag:» может приехать двумя кусками, а длинный S/N Dell — тремя
    строками вида «CN-0Y71R3», «-TV200-19B-1EHT», «-A01».
    """
    if not blocks:
        return []
    height = median(block.height for block in blocks)
    normalized = [
        Block(
            text=nz.clean_text(block.text).strip(),
            confidence=block.confidence,
            x1=block.x1,
            y1=block.y1,
            x2=block.x2,
            y2=block.y2,
        )
        for block in blocks
        if block.text.strip()
    ]

    rows: list[list[Block]] = []
    for block in sorted(normalized, key=lambda item: item.center_y):
        if rows and abs(block.center_y - rows[-1][0].center_y) <= height * 0.6:
            rows[-1].append(block)
        else:
            rows.append([block])

    grouped: list[Block] = []
    for row in rows:
        row.sort(key=lambda item: item.x1)
        line = [row[0]]
        for block in row[1:]:
            # Соседние куски одной надписи стоят вплотную, соседние колонки — далеко.
            if block.x1 - line[-1].x2 <= height * 1.2:
                line[-1] = _merge(line[-1], block, " ")
            else:
                line.append(block)

        for block in line:
            if block.text[:1] in CONTINUATION_CHARS and grouped:
                parent = _continuation_parent(grouped, block, height)
                if parent is not None:
                    tail = Block(
                        text="-" + block.text[1:],
                        confidence=block.confidence,
                        x1=block.x1,
                        y1=block.y1,
                        x2=block.x2,
                        y2=block.y2,
                    )
                    grouped[grouped.index(parent)] = _merge(parent, tail, "")
                    continue
            grouped.append(block)
    return grouped


def parse_blocks(raw_blocks: list[Block]) -> Card | None:
    if not raw_blocks:
        return None

    blocks = group_blocks(raw_blocks)
    inline = nz.clean_text(" ".join(block.text for block in blocks))
    multiline = nz.clean_text("\n".join(block.text for block in blocks))
    corpus = f"{inline}\n{multiline}"

    def find(pattern: re.Pattern[str], label_pattern: re.Pattern[str]) -> str | None:
        match = pattern.search(corpus)
        if match:
            value = match.group(1)
            if not nz.looks_like_noise(corpus, value):
                return value
        return _search_by_labels(blocks, label_pattern)

    tag, tag_fixed = nz.repair_identifier(
        find(nz.SERVICE_TAG_RE, TAG_LABEL), nz.is_valid_service_tag
    )
    serial, serial_fixed = nz.repair_identifier(
        find(nz.SERIAL_RE, SERIAL_LABEL), nz.is_valid_serial
    )
    serial, serial_polished = nz.polish_serial(serial)
    serial_fixed = serial_fixed or serial_polished
    printed_serial = serial
    serial = nz.canonical_serial(serial)
    if serial is not None and len(serial) < MIN_OCR_SERIAL_LENGTH:
        # Короткие «номера» из OCR почти всегда оказываются обрывком мусорного текста;
        # со штрихкода короткие значения принимаются, там источник надёжный.
        serial, printed_serial, serial_fixed = None, None, serial_fixed and bool(tag)
    model = nz.normalize_value(find(nz.MODEL_RE, MODEL_LABEL))
    if not nz.is_valid_model(model):
        model = nz.find_model_candidate(corpus, exclude=(serial, tag))

    if not (serial or tag):
        return None

    confidences = [block.confidence for block in blocks if block.confidence]
    corrected = tag_fixed or serial_fixed
    weak = bool(confidences) and min(confidences) < 0.8
    return Card(
        brand=nz.match_brand(corpus),
        model=model,
        serial_number=serial,
        serial_display=nz.display_serial(serial, printed_serial),
        service_tag=tag,
        source=Source.OCR,
        confidence=Confidence.MEDIUM if (corrected or weak) else Confidence.HIGH,
        corrected_symbols=corrected,
        raw_text=inline[:2000],
    )


def scan(variants: ImageVariants) -> tuple[Card | None, str]:
    """Возвращает карточку (если распознана) и сырой текст для следующих контуров."""
    if not engine.enabled:
        return None, ""
    raw_text = ""
    for image in variants.for_ocr():
        blocks = engine.read(image)
        if not blocks:
            continue
        raw_text = raw_text or nz.clean_text(" ".join(block.text for block in blocks))
        card = parse_blocks(blocks)
        if card is not None:
            return card, raw_text
    return None, raw_text
