# Imagem única de deploy: o FastAPI serve a API e o build do React (mesma origem, sem CORS).
# Nada processual é gravado na imagem; o PDF vive só em tempfile durante o job.

# --- Build do frontend ---
FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Backend ---
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    STATIC_DIR=/app/static \
    TIME_CARD_OCR=true \
    TESSERACT_CMD=tesseract

# Tesseract com português: cartão de ponto escaneado lido no servidor.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-por \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend
COPY backend/pyproject.toml ./
COPY backend/api ./api
COPY backend/core ./core
COPY backend/models ./models
COPY backend/pipeline ./pipeline
COPY backend/repositories ./repositories
COPY backend/schemas ./schemas
COPY backend/services ./services
COPY backend/alembic ./alembic
COPY backend/alembic.ini backend/main.py ./
RUN pip install . && useradd --create-home --uid 1000 veritas
COPY --from=frontend /app/frontend/dist /app/static

USER veritas
EXPOSE 8765
# PORT vem da plataforma (Render, etc.); local usa 8765. Um worker: as sessões ficam em memória.
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8765} --proxy-headers --forwarded-allow-ips='*'"]
