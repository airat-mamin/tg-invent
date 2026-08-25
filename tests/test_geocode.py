from app.services.geocode import (
    Place,
    format_location,
    normalize_room,
    parse_typed_address,
    place_from_nominatim,
)

NOMINATIM_MOSCOW = {
    "address": {
        "house_number": "5",
        "road": "улица Ленина",
        "city": "Москва",
        "country": "Россия",
    }
}


def test_address_drops_street_prefix():
    place = place_from_nominatim(NOMINATIM_MOSCOW, 55.75, 37.61)
    assert place.address() == "Москва, Ленина 5"


def test_location_includes_room():
    place = Place(city="Москва", street="Ленина", house="5")
    assert format_location(place, "12") == "Москва, Ленина 5, кабинет 12"


def test_location_without_room():
    place = Place(city="Москва", street="Ленина", house="5")
    assert format_location(place, None) == "Москва, Ленина 5"


def test_room_only():
    assert format_location(None, "12") == "кабинет 12"


def test_town_is_used_when_city_is_missing():
    payload = {
        "address": {
            "town": "Зеленоград",
            "road": "Панфиловский проспект",
            "house_number": "10",
        }
    }
    assert place_from_nominatim(payload, 0, 0).address() == "Зеленоград, Панфиловский проспект 10"


def test_normalize_room_strips_label():
    assert normalize_room("кабинет 12") == "12"
    assert normalize_room("каб. 3а") == "3а"
    assert normalize_room("-") is None
    assert normalize_room("нет такого!!!!!!!") is None


def test_parse_typed_address_splits_city_street_house():
    place = parse_typed_address("Москва, Ленина 5")
    assert place.address() == "Москва, Ленина 5"
    assert (place.city, place.street, place.house) == ("Москва", "Ленина", "5")


def test_parse_typed_address_drops_street_prefix_and_cabinet():
    place = parse_typed_address("Москва, улица Ленина, д. 5, кабинет 12")
    assert place.address() == "Москва, Ленина 5"
    assert format_location(place, "12") == "Москва, Ленина 5, кабинет 12"
