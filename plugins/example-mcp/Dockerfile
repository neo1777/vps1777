# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.5.18 /uv /uvx /usr/local/bin/
WORKDIR /build
COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --no-dev --no-install-project
COPY app ./app
RUN --mount=type=cache,target=/root/.cache/uv uv sync --no-dev

FROM gcr.io/distroless/python3-debian12:nonroot
COPY --from=builder /build/.venv /opt/venv
COPY --from=builder /build/app /app/app
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1
WORKDIR /app
EXPOSE 8010
USER nonroot
ENTRYPOINT ["python", "-m", "app"]
