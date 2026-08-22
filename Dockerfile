# syntax=docker/dockerfile:1
FROM python:3.11-slim

LABEL org.opencontainers.image.title="MPCWithGenerativeArt" \
      org.opencontainers.image.description="Generate custom-appearing decks of cards for MakePlayingCards with AI image generation and 800 DPI bleed compositing" \
      org.opencontainers.image.source="https://github.com/ROMzombie/MPCWithGenerativeArt"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    HOST=0.0.0.0 \
    ENV_FILE=none

WORKDIR /app

# Install system dependencies for Pillow and Playwright Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    libgl1 \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY requirements.txt .
RUN pip install -r requirements.txt

# Install Playwright Chromium browser binaries for perchance provider
RUN playwright install chromium

# Copy application files
COPY backend/ backend/
COPY frontend/ frontend/
COPY run.py .

# Create output and cache directories
RUN mkdir -p output/cards output/thumbnails cache/scryfall

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
