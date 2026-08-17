FROM python:3.12-slim

# WITH_OCR=true устанавливает EasyOCR (тянет torch, ~2 ГБ) — Контур №1.
ARG WITH_OCR=false

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        libglib2.0-0 \
        libgl1 \
        libzbar0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-ocr.txt ./
RUN if [ "$WITH_OCR" = "true" ]; then \
        pip install -r requirements-ocr.txt; \
    else \
        pip install -r requirements.txt; \
    fi

COPY app ./app

RUN useradd --create-home --uid 1000 bot && mkdir -p /data && chown -R bot:bot /data /app
USER bot

VOLUME ["/data"]

CMD ["python", "-m", "app.main"]
