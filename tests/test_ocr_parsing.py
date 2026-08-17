from app.services.ocr import Block, parse_blocks


def block(text: str, x1: float, y1: float, width: float = 200, height: float = 30, conf=0.95):
    return Block(text=text, confidence=conf, x1=x1, y1=y1, x2=x1 + width, y2=y1 + height)


def test_parses_inline_labels():
    blocks = [
        block("DELL", 10, 10),
        block("MODEL: E2722H", 10, 50),
        block("SERVICE TAG: 9YSCSF3", 10, 90),
        block("S/N: CN0Y71R3TV20019B13QT", 10, 130, width=400),
    ]
    card = parse_blocks(blocks)
    assert card is not None
    assert card.brand == "DELL"
    assert card.model == "E2722H"
    assert card.service_tag == "9YSCSF3"
    assert card.serial_number == "CN0Y71R3TV20019B13QT"


def test_parses_value_in_neighbouring_block():
    blocks = [
        block("SERVICE TAG:", 10, 90, width=150),
        block("9YSCSF3", 180, 92, width=100),
        block("S/N", 10, 140, width=50),
        block("CN0Y71R3TV20019B13QT", 70, 140, width=350),
    ]
    card = parse_blocks(blocks)
    assert card is not None
    assert card.service_tag == "9YSCSF3"
    assert card.serial_number == "CN0Y71R3TV20019B13QT"


def test_low_confidence_downgrades_card():
    blocks = [block("S/N: ABC12345", 10, 10, conf=0.55)]
    card = parse_blocks(blocks)
    assert card is not None and card.confidence == "medium"


def test_returns_none_without_identifiers():
    assert parse_blocks([block("DELL", 10, 10), block("MADE IN CHINA", 10, 50)]) is None
    assert parse_blocks([]) is None
