import os

# Настройки читаются при импорте приложения, поэтому подставляем тестовые значения заранее.
os.environ.setdefault("BOT_TOKEN", "0:test")
os.environ.setdefault("OCR_ENABLED", "false")
os.environ.setdefault("VLM_ENABLED", "false")
os.environ.setdefault("GEOCODE_ENABLED", "false")
