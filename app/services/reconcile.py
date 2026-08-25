"""Сверка карточки контуров №0/№1 с облачным OCR Cloud Vision."""

from app.models import FIELD_TITLES, Card, Confidence, Source
from app.services import normalize as nz

COMPARED_FIELDS = ("brand", "model", "serial_number", "service_tag")


def _compact(value: str | None) -> str:
    if not value:
        return ""
    ident = nz.normalize_identifier(value)
    polished, _ = nz.polish_serial(ident)
    canonical = nz.canonical_serial(polished or ident) or ""
    return canonical.replace("-", "")


_SERIAL_CONFUSABLES = {
    "0": "OQ",
    "O": "0Q",
    "Q": "0O",
    "8": "B",
    "B": "8",
    "5": "S",
    "S": "5",
    "1": "I",
    "I": "1",
}


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
    if longer.endswith(shorter) or _compact(extracted) == shorter:
        return True
    if len(first) == len(second) >= 12:
        left_v, right_v = nz.rules().match_serial(first), nz.rules().match_serial(second)
        same_vendor = (
            left_v is not None and right_v is not None and left_v.brand == right_v.brand
        )
        # Один формат, отличаются первые символы (2/4, Q/0) — хвост серийника тот же.
        if first[4:] == second[4:] and same_vendor:
            return True
        # EasyOCR: O/0 и Q/0 в середине и в хвосте BenQ ETR4MO2620010 vs ETR4M0262001Q.
        if same_vendor and all(
            a == b or b in _SERIAL_CONFUSABLES.get(a, "") for a, b in zip(first, second)
        ):
            return True
    return False


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


def prefer_specific_model(current: str | None, other: str | None, brand: str | None) -> str | None:
    """Между Type GW2480 и Model ID GW2480-T оставляет более полное имя."""
    first, _ = nz.polish_model(current, brand)
    second, _ = nz.polish_model(other, brand)
    if first and second:
        left = first.replace("-", "").replace(" ", "")
        right = second.replace("-", "").replace(" ", "")
        if left.startswith(right) and len(left) > len(right):
            return first
        if right.startswith(left) and len(right) > len(left):
            return second
        return second
    if second:
        return second
    # P24H G4 не сходится с шаблоном Dell, но это настоящая модель HP.
    other_any, _ = nz.polish_model(other, None)
    if other_any:
        return other_any
    return first or other


def model_from_barcode(card: Card) -> bool:
    """Модель взята из полезной нагрузки штрихкода, а не из OCR рядом с ним."""
    if not card.model:
        return False
    return any(
        not values_agree("serial_number", card.serial_number, payload)
        and values_agree("model", card.model, payload)
        for payload in card.barcode_payloads
    )


def prefer_serial(primary: str | None, extra: str | None) -> str | None:
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

    Штрихкод — источник истины, если модель или серийник были в его строке.
    Иначе при том же серийнике модель Cloud Vision точнее мусора EasyOCR.
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
                    chosen = prefer_serial(current, other)
                    current_c, other_c = _compact(current), _compact(other)
                    # EasyOCR часто путает цифры в начале Samsung S/N; хвост тот же —
                    # берём более чистую строку Cloud Vision, но не трогаем штрихкод.
                    if (
                        primary.source is Source.OCR
                        and len(current_c) == len(other_c) >= 12
                        and current_c != other_c
                    ):
                        chosen = other
                    if chosen != current:
                        polished, _ = nz.polish_serial(chosen)
                        primary.serial_number = nz.canonical_serial(polished or chosen)
                        primary.serial_display = nz.display_serial(
                            primary.serial_number, vision.serial_display or chosen
                        )
                        if len(_compact(chosen)) > len(_compact(current)):
                            filled.append(f"{title} (полный номер из Cloud Vision)")
                        else:
                            filled.append(f"{title} (уточнил Cloud Vision)")
            else:
                # QR вроде 90106-45981 проходит общую валидацию, а Cloud Vision
                # читает настоящий S/N производителя — берём его.
                if (
                    field == "serial_number"
                    and primary.source in {Source.BARCODE, Source.OCR}
                    and nz.rules().match_serial(current) is None
                    and nz.rules().match_serial(other) is not None
                ):
                    polished, _ = nz.polish_serial(other)
                    primary.serial_number = nz.canonical_serial(polished or other)
                    primary.serial_display = nz.display_serial(
                        primary.serial_number, vision.serial_display or other
                    )
                    filled.append(f"{title} (уточнил Cloud Vision)")
                # EasyOCR часто подставляет мусор в модель, пока штрихкод уже дал
                # верный серийник. Если облако читает ту же этикетку и модель не
                # была в штрихкоде — берём маркетинговое имя Cloud Vision.
                elif (
                    field in {"model", "brand"}
                    and serials_agree(primary.serial_number, vision.serial_number)
                    and not (field == "model" and model_from_barcode(primary))
                ):
                    if field == "model":
                        chosen = prefer_specific_model(
                            current, other, primary.brand or vision.brand
                        )
                        if chosen == current or nz.polish_model(chosen, primary.brand)[0] == nz.polish_model(current, primary.brand)[0]:
                            confirmed.append(title)
                            continue
                        primary.model = chosen
                    else:
                        setattr(primary, field, other)
                    filled.append(f"{title} (уточнил Cloud Vision)")
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

    barcode_hits = [
        payload
        for payload in vision.barcode_payloads
        if serials_agree(primary.serial_number, payload)
        or values_agree("service_tag", primary.service_tag, payload)
    ]
    if barcode_hits:
        confirmed_barcode = "Cloud Vision подтвердил штрихкод: " + ", ".join(barcode_hits)
        if confirmed_barcode not in primary.notes:
            primary.notes.append(confirmed_barcode)
        if not conflicts:
            primary.confidence = Confidence.HIGH

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
