"""Загрузка шаблонов разбора шильдиков из каталога конфигурации."""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


class TemplateError(RuntimeError):
    """Ошибка в файле шаблона: запуск с такой конфигурацией не имеет смысла."""


@dataclass(frozen=True)
class SerialFix:
    name: str
    pattern: re.Pattern[str]
    replacement: str


@dataclass(frozen=True)
class SerialRules:
    pattern: re.Pattern[str]
    min_length: int = 1
    max_length: int = 64
    hyphens_are_separators: bool = False
    groups: dict[int, tuple[int, ...]] = field(default_factory=dict)
    fixes: tuple[SerialFix, ...] = ()
    part_number: re.Pattern[str] | None = None
    extract: re.Pattern[str] | None = None
    short: re.Pattern[str] | None = None

    def matches(self, serial: str) -> bool:
        if not (self.min_length <= len(serial) <= self.max_length):
            return False
        if self.pattern.match(serial) is not None:
            return True
        return bool(self.short and self.short.fullmatch(serial))

    def inventory_value(self, serial: str) -> str:
        """Достаёт серийник из склеенного штрихкода (MTM+S/N у Lenovo)."""
        if self.extract is None:
            return serial
        match = self.extract.fullmatch(serial)
        if match and match.lastindex:
            return match.group(1)
        return serial

    def split_groups(self, serial: str) -> str | None:
        sizes = self.groups.get(len(serial))
        if not sizes:
            return None
        parts: list[str] = []
        position = 0
        for size in sizes:
            parts.append(serial[position : position + size])
            position += size
        if position != len(serial):
            return None
        return "-".join(parts)

    def extract_part_number(self, serial: str) -> str | None:
        if self.part_number is None:
            return None
        match = self.part_number.match(serial)
        return match.group(1) if match else None


@dataclass(frozen=True)
class VendorTemplate:
    brand: str
    aliases: tuple[str, ...] = ()
    serial: SerialRules | None = None
    model_token: re.Pattern[str] | None = None
    models_by_part: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CommonRules:
    brands: tuple[str, ...]
    service_tag_label: re.Pattern[str]
    serial_label: re.Pattern[str]
    model_label: re.Pattern[str]
    model_token: re.Pattern[str]
    model_stopwords: frozenset[str]
    noise_labels: re.Pattern[str]
    mac_address: re.Pattern[str]
    noise_values: frozenset[str]
    valid_service_tag: re.Pattern[str]
    valid_serial: re.Pattern[str]
    valid_model: re.Pattern[str]


@dataclass(frozen=True)
class Registry:
    common: CommonRules
    vendors: tuple[VendorTemplate, ...]

    def by_brand(self, brand: str | None) -> VendorTemplate | None:
        if not brand:
            return None
        wanted = brand.upper()
        for vendor in self.vendors:
            if vendor.brand == wanted or wanted in vendor.aliases:
                return vendor
        return None

    def match_serial(self, serial: str | None) -> VendorTemplate | None:
        """Определяет производителя по формату серийного номера."""
        if not serial:
            return None
        for vendor in self.vendors:
            if vendor.serial is not None and vendor.serial.matches(serial):
                return vendor
        return None

    @property
    def brand_names(self) -> tuple[str, ...]:
        names = list(self.common.brands)
        for vendor in self.vendors:
            for name in (vendor.brand, *vendor.aliases):
                if name not in names:
                    names.append(name)
        return tuple(names)


def _compile(source: Any, where: str) -> re.Pattern[str]:
    if not isinstance(source, str) or not source.strip():
        raise TemplateError(f"{where}: ожидалось регулярное выражение")
    try:
        return re.compile(source.strip())
    except re.error as error:
        raise TemplateError(f"{where}: некорректное регулярное выражение ({error})") from error


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise TemplateError(f"{path.name}: файл не читается как YAML ({error})") from error
    if not isinstance(data, dict):
        raise TemplateError(f"{path.name}: ожидался словарь на верхнем уровне")
    return data


def _require(data: dict[str, Any], key: str, where: str) -> Any:
    value = data.get(key)
    if value is None:
        raise TemplateError(f"{where}: отсутствует обязательное поле «{key}»")
    return value


def _load_common(path: Path) -> CommonRules:
    data = _read_yaml(path)
    where = path.name
    labels = _require(data, "labels", where)
    model = _require(data, "model", where)
    noise = _require(data, "noise", where)
    validation = _require(data, "validation", where)

    brands = tuple(str(brand).upper() for brand in _require(data, "brands", where))
    if not brands:
        raise TemplateError(f"{where}: список brands пуст")

    return CommonRules(
        brands=brands,
        service_tag_label=_compile(labels.get("service_tag"), f"{where}: labels.service_tag"),
        serial_label=_compile(labels.get("serial"), f"{where}: labels.serial"),
        model_label=_compile(labels.get("model"), f"{where}: labels.model"),
        model_token=_compile(model.get("token_pattern"), f"{where}: model.token_pattern"),
        model_stopwords=frozenset(str(word).upper() for word in model.get("stopwords", ())),
        noise_labels=_compile(noise.get("labels"), f"{where}: noise.labels"),
        mac_address=_compile(noise.get("mac_address"), f"{where}: noise.mac_address"),
        noise_values=frozenset(str(value).upper() for value in noise.get("values", ())) | {""},
        valid_service_tag=_compile(
            validation.get("service_tag"), f"{where}: validation.service_tag"
        ),
        valid_serial=_compile(validation.get("serial"), f"{where}: validation.serial"),
        valid_model=_compile(validation.get("model"), f"{where}: validation.model"),
    )


def _load_serial_rules(data: dict[str, Any], where: str) -> SerialRules:
    pattern = _compile(data.get("pattern"), f"{where}: serial.pattern")

    length = data.get("length", [1, 64])
    if not (isinstance(length, list | tuple) and len(length) == 2):
        raise TemplateError(f"{where}: serial.length должен быть парой [минимум, максимум]")

    hyphens = str(data.get("hyphens", "significant")).lower()
    if hyphens not in {"separator", "significant"}:
        raise TemplateError(f"{where}: serial.hyphens должен быть separator или significant")

    groups: dict[int, tuple[int, ...]] = {}
    for total, sizes in (data.get("groups") or {}).items():
        sizes = tuple(int(size) for size in sizes)
        if sum(sizes) != int(total):
            raise TemplateError(
                f"{where}: serial.groups[{total}] в сумме даёт {sum(sizes)} символов"
            )
        groups[int(total)] = sizes

    fixes = []
    for index, item in enumerate(data.get("fixes") or ()):
        fixes.append(
            SerialFix(
                name=str(item.get("name", f"правка {index + 1}")),
                pattern=_compile(item.get("pattern"), f"{where}: serial.fixes[{index}].pattern"),
                replacement=str(_require(item, "replacement", f"{where}: serial.fixes[{index}]")),
            )
        )

    part_number = data.get("part_number")
    extract = data.get("extract")
    short = data.get("short")
    return SerialRules(
        pattern=pattern,
        min_length=int(length[0]),
        max_length=int(length[1]),
        hyphens_are_separators=hyphens == "separator",
        groups=groups,
        fixes=tuple(fixes),
        part_number=_compile(part_number, f"{where}: serial.part_number") if part_number else None,
        extract=_compile(extract, f"{where}: serial.extract") if extract else None,
        short=_compile(short, f"{where}: serial.short") if short else None,
    )


def _load_vendor(path: Path) -> VendorTemplate:
    data = _read_yaml(path)
    where = path.name
    brand = str(_require(data, "brand", where)).upper()

    serial = data.get("serial")
    model = data.get("model") or {}
    token = model.get("token_pattern")
    by_part = {
        str(part).upper(): str(value).upper()
        for part, value in (model.get("by_part") or {}).items()
    }

    return VendorTemplate(
        brand=brand,
        aliases=tuple(str(alias).upper() for alias in data.get("aliases", ())),
        serial=_load_serial_rules(serial, where) if serial else None,
        model_token=_compile(token, f"{where}: model.token_pattern") if token else None,
        models_by_part=by_part,
    )


def load_registry(directory: Path) -> Registry:
    common_path = directory / "common.yaml"
    if not common_path.is_file():
        raise TemplateError(f"не найден файл общих правил: {common_path}")

    vendors = [_load_vendor(path) for path in sorted((directory / "vendors").glob("*.yaml"))]
    registry = Registry(common=_load_common(common_path), vendors=tuple(vendors))
    logger.info(
        "Шаблоны загружены из %s: производителей %s (%s)",
        directory,
        len(vendors),
        ", ".join(vendor.brand for vendor in vendors) or "нет",
    )
    return registry
