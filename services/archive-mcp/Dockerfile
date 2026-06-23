# syntax=docker/dockerfile:1.7
# vps1777 archive-mcp — python:3.12-slim non-root.
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.5.18 /uv /uvx /usr/local/bin/
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_COMPILE_BYTECODE=1
WORKDIR /build
COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --no-install-project
COPY app ./app
RUN --mount=type=cache,target=/root/.cache/uv uv sync --no-dev

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tini ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd -g 1000 app && useradd -u 1000 -g 1000 -m -s /sbin/nologin app
RUN mkdir -p /var/lib/archive/db /var/lib/archive/data && chown -R app:app /var/lib/archive
COPY --from=builder /build/.venv /opt/venv
COPY --from=builder /build/app /app/app
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
USER app
EXPOSE 8002
ENTRYPOINT ["tini", "--", "python", "-m", "app"]
