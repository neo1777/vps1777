# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.5.18 /uv /uvx /usr/local/bin/
WORKDIR /build
COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --no-dev --no-install-project
COPY app ./app
RUN --mount=type=cache,target=/root/.cache/uv uv sync --no-dev

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tini ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd -g 1000 bot && useradd -u 1000 -g 1000 -m -s /sbin/nologin bot
COPY --from=builder /build/.venv /opt/venv
COPY --from=builder /build/app /app/app
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1
WORKDIR /app
USER bot
ENTRYPOINT ["tini", "--", "python", "-m", "app"]
