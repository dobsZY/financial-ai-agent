# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

# opencv-python-headless -> libGL/glib; matplotlib -> temel fontlar
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        fonts-dejavu-core \
        curl \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    MPLBACKEND=Agg \
    TZ=Europe/Istanbul

WORKDIR /app

# Bagimliliklar once: kod degisince tekrar kurulmasin.
# Not: ultralytics -> torch cektigi icin ilk imaj ~2-3 GB olur.
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

# Uygulama root olarak calismaz
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/data /app/models \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
