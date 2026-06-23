# syntax=docker/dockerfile:1.7
#
# vps1777 nb1777-mcp — NotebookLM via CLI `nlm`.
#
# Chromium headless serve a nlm per le sessioni di scraping del frontend
# NotebookLM. Non possiamo usare distroless (no Chromium). Runtime è
# python:3.12-slim + chromium + libs Playwright.

# ─────────────────────────────────────── builder
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.5.18 /uv /uvx /usr/local/bin/
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_COMPILE_BYTECODE=1
WORKDIR /build
COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --no-install-project
COPY app ./app
RUN --mount=type=cache,target=/root/.cache/uv uv sync --no-dev

# ─────────────────────────────────────── runtime
FROM python:3.12-slim

# Chromium + dipendenze Playwright (per nlm headless)
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        chromium \
        libgbm1 libasound2 libnss3 libxshmfence1 libxss1 libxtst6 \
        libxrandr2 libxcomposite1 libxdamage1 libxfixes3 \
        libgtk-3-0 libpangocairo-1.0-0 fonts-liberation \
        tini ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Utente non-root condiviso (UID 1000 "app") — STESSO uid di gateway/bot
# così il volume nlm-auth è accessibile da tutti i servizi che lo montano.
RUN groupadd -g 1000 app && useradd -u 1000 -g 1000 -m -s /sbin/nologin app
RUN mkdir -p /var/lib/nlm && chown -R app:app /var/lib/nlm

# Copia venv + codice dal builder
COPY --from=builder /build/.venv /opt/venv
COPY --from=builder /build/app /app/app

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NLM_HOME=/var/lib/nlm \
    HOME=/var/lib/nlm \
    CHROME_BIN=/usr/bin/chromium

WORKDIR /app
USER app

EXPOSE 8003

# tini come PID 1 per signal handling pulito
ENTRYPOINT ["tini", "--", "python", "-m", "app"]
