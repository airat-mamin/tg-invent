import asyncio
import json
import logging
import re

from app.config import settings
from app.models import Card, Confidence, Source
from app.services import normalize as nz

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Ты — ассистент системного администратора. Твоя задача — внимательно изучить изображение "
    "наклейки ИТ-оборудования. Найди и извлеки следующие параметры: Производитель (Brand), "
    "Модель (Model), Серийный номер (S/N или Serial Number), Сервисный тег (Service Tag, только "
    "для Dell). Верни ответ СТРОГО в формате JSON с ключами: brand, model, serial_number, "
    "service_tag. Если поле не найдено, укажи null. Никакого лишнего текста в ответе быть "
    "не должно."
)
RETRY_PROMPT = "Верни только JSON-объект с ключами brand, model, serial_number, service_tag."

JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


class VlmUnavailableError(RuntimeError):
    pass


def extract_json(text: str) -> dict | None:
    """Достаёт JSON-объект из ответа модели, даже если он обёрнут пояснениями."""
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        match = JSON_OBJECT_RE.search(text)
        if not match:
            return None
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return payload if isinstance(payload, dict) else None


def card_from_payload(payload: dict, raw: str) -> Card | None:
    tag, tag_fixed = nz.repair_identifier(payload.get("service_tag"), nz.is_valid_service_tag)
    serial, serial_fixed = nz.repair_identifier(payload.get("serial_number"), nz.is_valid_serial)
    serial, serial_polished = nz.polish_serial(serial)
    serial_fixed = serial_fixed or serial_polished
    printed_serial = serial
    serial = nz.canonical_serial(serial)
    model = nz.normalize_value(payload.get("model"))
    if not nz.is_valid_model(model):
        model = None
    brand = nz.match_brand(payload.get("brand")) or nz.normalize_value(payload.get("brand"))

    if not (serial or tag):
        return None
    return Card(
        brand=brand,
        model=model,
        serial_number=serial,
        serial_display=nz.display_serial(serial, printed_serial),
        service_tag=tag,
        source=Source.VLM,
        confidence=Confidence.LOW,
        corrected_symbols=tag_fixed or serial_fixed,
        raw_text=raw[:2000],
    )


class VlmClient:
    def __init__(self) -> None:
        self._client = None
        self._semaphore = asyncio.Semaphore(max(1, settings.max_concurrent_vlm))

    @property
    def enabled(self) -> bool:
        return settings.vlm_enabled

    def _get_client(self):
        if self._client is None:
            from ollama import AsyncClient

            self._client = AsyncClient(host=settings.ollama_host, timeout=settings.ollama_timeout)
        return self._client

    async def health(self) -> bool:
        if not self.enabled:
            return False
        try:
            await asyncio.wait_for(self._get_client().list(), timeout=10)
            return True
        except Exception as error:  # noqa: BLE001
            logger.warning("Ollama недоступна (%s): %s", settings.ollama_host, error)
            return False

    async def _ask(self, image: bytes, prompt: str) -> str:
        response = await self._get_client().chat(
            model=settings.ollama_model,
            format="json",
            options={"temperature": 0},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt, "images": [image]},
            ],
        )
        return (response.get("message") or {}).get("content", "")

    async def scan(self, image: bytes) -> Card | None:
        if not self.enabled:
            return None
        async with self._semaphore:
            try:
                raw = await asyncio.wait_for(
                    self._ask(image, "Извлеки данные с этой наклейки."),
                    timeout=settings.ollama_timeout,
                )
                payload = extract_json(raw)
                if payload is None:
                    logger.info("VLM вернула невалидный JSON, повторный запрос")
                    raw = await asyncio.wait_for(
                        self._ask(image, RETRY_PROMPT), timeout=settings.ollama_timeout
                    )
                    payload = extract_json(raw)
            except asyncio.TimeoutError as error:
                raise VlmUnavailableError("timeout") from error
            except Exception as error:  # noqa: BLE001
                raise VlmUnavailableError(str(error)) from error

        if payload is None:
            return None
        return card_from_payload(payload, raw)


client = VlmClient()
