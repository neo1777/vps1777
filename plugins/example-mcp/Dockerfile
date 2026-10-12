# syntax=docker/dockerfile:1.7
# Scheletro plugin MCP — stesso schema dei servizi in services/*/Dockerfile:
# builder uv + runtime python:3.12-slim, utente non-root.
# Niente distroless: python3-debian12 porta Python 3.11, e un venv creato con 3.12
# nel builder non gira su un runtime 3.11 (il container va in crash-loop).
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.5.18 /uv /uvx /usr/local/bin/
# UV_PROJECT_ENVIRONMENT=/opt/venv: il venv nasce nel path finale → shebang corretti nel runtime.
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /build
COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --no-dev --no-install-project
COPY app ./app
RUN --mount=type=cache,target=/root/.cache/uv uv sync --no-dev

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd -g 1000 app && useradd -u 1000 -g 1000 -m -s /sbin/nologin app
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /build/app /app/app
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
USER app
EXPOSE 8010
ENTRYPOINT ["tini", "--", "python", "-m", "app"]
