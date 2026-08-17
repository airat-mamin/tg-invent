from functools import cached_property
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def _parse_ids(raw: str) -> frozenset[int]:
    return frozenset(int(part) for part in raw.replace(";", ",").split(",") if part.strip())


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    bot_token: SecretStr
    allowed_user_ids: str = ""
    admin_user_ids: str = ""

    ocr_enabled: bool = True
    ocr_langs: str = "en"
    # Штрихкод не содержит модель: флаг разрешает дочитать её через OCR ценой времени ответа.
    ocr_enrich_after_barcode: bool = False

    vlm_enabled: bool = False
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llama3.2-vision:11b"
    ollama_timeout: int = 60
    max_concurrent_vlm: int = 1

    db_path: Path = Path("data/bot.db")
    store_images: bool = False
    image_dir: Path = Path("data/images")
    image_retention_days: int = 30

    rate_limit_per_minute: int = 10
    log_level: str = "INFO"
    log_json: bool = False

    @cached_property
    def allowed_ids(self) -> frozenset[int]:
        return _parse_ids(self.allowed_user_ids)

    @cached_property
    def admin_ids(self) -> frozenset[int]:
        return _parse_ids(self.admin_user_ids)

    @property
    def ocr_lang_list(self) -> list[str]:
        return [lang.strip() for lang in self.ocr_langs.split(",") if lang.strip()]

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_ids

    def is_allowed(self, user_id: int) -> bool:
        # Пустой список означает открытый доступ и допустим только при отладке.
        return not self.allowed_ids or user_id in self.allowed_ids or self.is_admin(user_id)


settings = Settings()  # type: ignore[call-arg]
