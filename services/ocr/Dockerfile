# syntax=docker/dockerfile:1.7
#
# vps1777 ocr — il servizio interno che presta gli occhi all'ingest (B5).
# Stessa sagoma dei fratelli (multi-stage uv + python:3.12-slim non-root),
# anche se le dipendenze sono zero: il lock nella build è un invariante del
# repo (rilievo 23cc4783), non un'usanza da applicare solo quando pesa.

# ─────────────────────────────────────────── builder
FROM python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f AS builder
COPY --from=ghcr.io/astral-sh/uv:0.5.18@sha256:e2101b9e627153b8fe4e8a1249cc4194f1b38ece7f28a5a9b8f958e3b560e69c /uv /uvx /usr/local/bin/
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /build
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
COPY app ./app

# ─────────────────────────────────────────── runtime
FROM python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f

# tini per i segnali; tesseract è IL mestiere di questo container (eng è nel
# pacchetto base, ita si aggiunge: la ricetta `-l ita+eng` è quella provata
# su _chat/ocr1777 — 562/562 immagini, 0 errori).
RUN apt-get update && apt-get install -y --no-install-recommends tini \
    tesseract-ocr tesseract-ocr-ita \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -g 1000 app && useradd -u 1000 -g 1000 -m -s /sbin/nologin app

# Il pip della BASE è peso morto qui: le dipendenze le installa uv nel builder
# (/opt/venv) e a runtime nessuno lo chiama — ma è l'unica fonte di CVE
# ricorrenti sulle immagini (issue #263: 6 CVE con fix che python:3.12-slim
# non porta ancora). Un tool inutilizzato che accumula CVE si rimuove.
RUN python -m pip uninstall -y pip

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /build/app /app/app

ARG VPS1777_VERSION=0.0.0-dev
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VPS1777_VERSION=${VPS1777_VERSION}

WORKDIR /app
USER app
EXPOSE 8004
ENTRYPOINT ["tini", "--", "python", "-m", "app"]
