from app.keyboards.inline import confirmation
from app.models import Card
from app.services import normalize as nz
from app.texts import render_card

COMPACT = "CN0Y71R3TV20019B13QTA01"
PRINTED = "CN-0Y71R3-TV200-19B-13QT-A01"


def test_hyphens_are_stripped_only_for_ppid():
    assert nz.canonical_serial(PRINTED) == COMPACT
    # У других производителей дефис может быть частью номера
    assert nz.canonical_serial("ABC-1234-XY") == "ABC-1234-XY"
    assert nz.canonical_serial(COMPACT) == COMPACT


def test_display_form_restores_label_grouping():
    assert nz.display_serial(COMPACT) == PRINTED
    assert nz.display_serial("CN07MT01QDC0074Q0DDSA04") == "CN-07MT01-QDC00-74Q-0DDS-A04"


def test_display_form_prefers_what_ocr_actually_read():
    assert nz.display_serial(COMPACT, "CN-0Y71R3-TV200-19B-13QT-A01") == PRINTED
    # Прочитанное не сходится с машинным видом — используется расчётная разбивка
    assert nz.display_serial(COMPACT, "CN-XXXX") == PRINTED


def test_unknown_format_is_shown_as_is():
    assert nz.display_serial("ABC12345") == "ABC12345"
    assert nz.display_serial(None) is None


def test_card_shows_printed_form():
    card = Card(serial_number=COMPACT, serial_display=PRINTED)
    text = render_card(card)
    assert f"<code>{PRINTED}</code>" in text
    assert COMPACT not in text.replace(PRINTED, "")


def test_copy_button_carries_compact_value():
    markup = confirmation(1, Card(serial_number=COMPACT, serial_display=PRINTED))
    button = markup.inline_keyboard[0][0]
    assert button.copy_text.text == COMPACT


def test_copy_button_is_absent_when_forms_match():
    markup = confirmation(1, Card(serial_number="ABC12345", serial_display="ABC12345"))
    assert all(button.copy_text is None for row in markup.inline_keyboard for button in row)
