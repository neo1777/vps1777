# syntax=docker/dockerfile:1.7
#
# vps1777 nb1777-bot — long-poll Telegram + chiamate MCP via httpx.
# Runtime: python:3.12-slim + tini (no Chromium qui — l'auth si carica
# dall'admin del gateway, il bot consuma solo il volume).

FROM python:3.14-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.5.18 /uv /uvx /usr/local/bin/
# UV_PROJECT_ENVIRONMENT=/opt/venv: venv nel path finale → shebang corretti nel runtime.
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /build
COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --no-install-project
COPY app ./app
RUN --mount=type=cache,target=/root/.cache/uv uv sync --no-dev

FROM python:3.14-slim
RUN apt-get update && apt-get install -y --no-install-recommends tini ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd -g 1000 app && useradd -u 1000 -g 1000 -m -s /sbin/nologin app
RUN mkdir -p /var/lib/nlm && chown -R app:app /var/lib/nlm
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /build/app /app/app
# Versione iniettata dalla CI di release (build-arg); nei build locali resta dev.
ARG VPS1777_VERSION=0.0.0-dev
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    NLM_HOME=/var/lib/nlm \
    VPS1777_VERSION=${VPS1777_VERSION}
WORKDIR /app
USER app
ENTRYPOINT ["tini", "--", "python", "-m", "app"]
