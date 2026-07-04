# syntax=docker/dockerfile:1.7
#
# vps1777 gateway — multi-stage uv + python:3.12-slim non-root.
#
# Stage 1 (builder): installa deps in /build/.venv con uv
# Stage 2 (runtime): python:3.12-slim, utente app (UID 1000), volumi chown-ati
#
# Niente distroless: serve shell per healthcheck/debug, e Python deve combaciare
# tra builder e runtime (distroless python3-debian12 = 3.11, mismatch col 3.12).

# ─────────────────────────────────────────── builder
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.5.18 /uv /uvx /usr/local/bin/
# UV_PROJECT_ENVIRONMENT=/opt/venv: venv nel path finale → shebang dei
# console-script corretti nel runtime (no /build/.venv rotto).
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /build
COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --no-install-project
COPY app ./app
RUN --mount=type=cache,target=/root/.cache/uv uv sync --no-dev

# ─────────────────────────────────────────── runtime
FROM python:3.12-slim

# tini per signal handling + ca-certificates per HTTPS uscente
RUN apt-get update && apt-get install -y --no-install-recommends tini ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Utente non-root condiviso (UID 1000 "app") — STESSO uid di nb1777-mcp/bot
# così i volumi condivisi (nlm-auth) sono accessibili a tutti.
RUN groupadd -g 1000 app && useradd -u 1000 -g 1000 -m -s /sbin/nologin app

# Mountpoint dei volumi creati con owner 1000 PRIMA del mount: un volume
# named vuoto eredita questi permessi al primo attach.
RUN mkdir -p /var/lib/gateway /var/lib/nlm && chown -R app:app /var/lib/gateway /var/lib/nlm

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /build/app /app/app

# Versione iniettata dalla CI di release (build-arg); nei build locali resta dev.
ARG VPS1777_VERSION=0.0.0-dev
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VPS1777_VERSION=${VPS1777_VERSION}

WORKDIR /app
USER app
EXPOSE 8080
ENTRYPOINT ["tini", "--", "python", "-m", "app"]
