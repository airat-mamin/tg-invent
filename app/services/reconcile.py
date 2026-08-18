"""Сверка карточки контуров №0/№1 с облачным OCR Cloud Vision."""

from app.models import FIELD_TITLES, Card, Confidence
from app.services import normalize as nz

COMPARED_FIELDS = ("brand", "model", "serial_number", "service_tag")


def _compact(value: str | None) -> str:
    if not value:
        return ""
    canonical = nz.canonical_serial(nz.normalize_identifier(value)) or ""
    return canonical.replace("-", "")


def serials_agree(left: str | None, right: str | None) -> bool:
    """Совпадение или один номер — хвост другого (Lenovo MTM+S/N и короткий S/N)."""
    first, second = _compact(left), _compact(right)
    if not first or not second:
        return False
    if first == second:
        return True
    shorter, longer = (first, second) if len(first) <= len(second) else (second, first)
    if len(shorter) < 8:
        return False
    extracted = nz.inventory_serial(longer) or ""
    return longer.endswith(shorter) or _compact(extracted) == shorter


def values_agree(field: str, left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    if field == "serial_number":
        return serials_agree(left, right)
    if field == "brand":
        return (nz.match_brand(left) or left) == (nz.match_brand(right) or right)
    if field == "model":
        first, _ = nz.polish_model(left)
        second, _ = nz.polish_model(right)
        return bool(first and second and first == second) or left == right
    return _compact(left) == _compact(right)


def _prefer_serial(primary: str | None, extra: str | None) -> str | None:
    if extra and not primary:
        return extra
    if primary and not extra:
        return primary
    if not serials_agree(primary, extra):
        return primary
    first, second = _compact(primary), _compact(extra)
    return extra if len(second) > len(first) else primary


def reconcile(primary: Card | None, vision: Card | None) -> Card | None:
    """Оставляет результат первого контура, дополняет пустое и отмечает совпадения.

    Штрихкод и EasyOCR — источник истины при конфликте. Cloud Vision может
    подтвердить те же значения, заполнить пробелы или отдать карточку, если
    первые контуры ничего не собрали.
    """
    if vision is None:
        return primary
    if primary is None:
        vision.notes.append("Карточка собрана Cloud Vision")
        return vision

    confirmed: list[str] = []
    filled: list[str] = []
    conflicts: list[str] = []

    for field in COMPARED_FIELDS:
        current = getattr(primary, field)
        other = getattr(vision, field)
        title = FIELD_TITLES[field]
        if current and other:
            if values_agree(field, current, other):
                confirmed.append(title)
                if field == "serial_number":
                    chosen = _prefer_serial(current, other)
                    if chosen != current:
                        primary.serial_number = nz.canonical_serial(chosen)
                        primary.serial_display = nz.display_serial(
                            primary.serial_number, vision.serial_display or chosen
                        )
                        filled.append(f"{title} (полный номер из Cloud Vision)")
            else:
                conflicts.append(title)
        elif other and not current:
            if field == "serial_number":
                primary.serial_number = nz.canonical_serial(other)
                primary.serial_display = vision.serial_display or nz.display_serial(
                    primary.serial_number
                )
            else:
                setattr(primary, field, other)
            filled.append(title)

    if confirmed:
        primary.notes.append("Cloud Vision подтвердил: " + ", ".join(confirmed))
        if not conflicts:
            primary.confidence = Confidence.HIGH
    if filled:
        primary.notes.append("Cloud Vision дополнил: " + ", ".join(filled))
    if conflicts:
        primary.notes.append(
            "Cloud Vision расходится (" + ", ".join(conflicts) + ") — оставили первый контур"
        )
        if primary.confidence is Confidence.HIGH:
            primary.confidence = Confidence.MEDIUM
    return primary
