"""Обратное геокодирование и сборка строки расположения.

Координаты бот получает только если пользователь сам отправил геопозицию
в Telegram: сжатые фотографии без EXIF, а IP клиента Bot API не отдаёт.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass

import aiohttp

from app.config import settings

logger = logging.getLogger(__name__)

STREET_PREFIXES = re.compile(
    r"^(улица|ул\.?|проспект|пр-кт|пр-т|проезд|переулок|пер\.?|"
    r"бульвар|б-р|набережная|наб\.?|шоссе|площадь|пл\.?|аллея)\s+",
    re.IGNORECASE,
)
CITY_KEYS = ("city", "town", "village", "municipality", "hamlet", "city_district", "state")
ROAD_KEYS = ("road", "pedestrian", "residential", "street")
HOUSE_TOKEN = re.compile(r"^(?:д(?:ом)?\.?\s*)?(\d+[A-Za-zА-Яа-яЁё/-]*)$", re.IGNORECASE)
CABINET_TAIL = re.compile(r",?\s*каб(?:инет)?\.?\s*\S+\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class Place:
    city: str | None = None
    street: str | None = None
    house: str | None = None
    latitude: float | None = None
    longitude: float | None = None

    def address(self) -> str | None:
        """Город и улица с номером дома: «Москва, Ленина 5»."""
        street_part = " ".join(part for part in (self.street, self.house) if part)
        value = ", ".join(part for part in (self.city, street_part) if part)
        return value or None

    def to_dict(self) -> dict:
        return asdict(self)


def format_location(place: Place | None, room: str | None) -> str | None:
    """Полное расположение: «Москва, Ленина 5, кабинет 12»."""
    address = place.address() if place else None
    cabinet = f"кабинет {room}" if room else None
    value = ", ".join(part for part in (address, cabinet) if part)
    return value or None


def normalize_room(raw: str) -> str | None:
    value = raw.strip()
    if not value or value == "-":
        return None
    value = re.sub(r"^(каб(инет)?\.?\s*)", "", value, flags=re.IGNORECASE).strip()
    if not re.fullmatch(r"[0-9A-Za-zА-Яа-яЁё\-/\.]{1,12}", value):
        return None
    return value


def parse_typed_address(text: str) -> Place:
    """Разбирает строку вроде «Москва, Ленина 5» или «Москва, улица Ленина, д. 5»."""
    value = CABINET_TAIL.sub("", text.strip())[:120].strip(" ,")
    if not value:
        return Place()
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if len(parts) == 1:
        return Place(city=parts[0])
    city = parts[0]
    street_part = _short_street(parts[1])
    house = None
    if len(parts) >= 3:
        match = HOUSE_TOKEN.match(parts[2])
        house = match.group(1) if match else parts[2]
    else:
        tokens = street_part.split()
        if len(tokens) >= 2:
            match = HOUSE_TOKEN.match(tokens[-1])
            if match:
                house = match.group(1)
                street_part = " ".join(tokens[:-1])
    return Place(city=city, street=street_part or None, house=house)


def _short_street(road: str) -> str:
    cleaned = STREET_PREFIXES.sub("", road).strip(" ,")
    return cleaned or road.strip()


def place_from_nominatim(payload: dict, lat: float, lon: float) -> Place:
    address = payload.get("address") or {}
    city = next((address[key] for key in CITY_KEYS if address.get(key)), None)
    road = next((address[key] for key in ROAD_KEYS if address.get(key)), None)
    house = address.get("house_number")
    return Place(
        city=city,
        street=_short_street(road) if road else None,
        house=str(house) if house else None,
        latitude=lat,
        longitude=lon,
    )


async def reverse_geocode(latitude: float, longitude: float) -> Place:
    if not settings.geocode_enabled:
        return Place(latitude=latitude, longitude=longitude)
    params = {
        "lat": f"{latitude:.6f}",
        "lon": f"{longitude:.6f}",
        "format": "jsonv2",
        "addressdetails": "1",
        "accept-language": "ru",
    }
    headers = {"User-Agent": settings.geocode_user_agent}
    try:
        timeout = aiohttp.ClientTimeout(total=settings.geocode_timeout)
        async with (
            aiohttp.ClientSession(timeout=timeout, headers=headers) as session,
            session.get(settings.geocode_url, params=params) as response,
        ):
            if response.status != 200:
                logger.warning("Геокодер ответил %s", response.status)
                return Place(latitude=latitude, longitude=longitude)
            payload = await response.json()
    except Exception as error:  # noqa: BLE001 — геокодер не должен ронять обработку
        logger.warning("Не удалось определить адрес: %s", error)
        return Place(latitude=latitude, longitude=longitude)
    if not isinstance(payload, dict):
        return Place(latitude=latitude, longitude=longitude)
    return place_from_nominatim(payload, latitude, longitude)
