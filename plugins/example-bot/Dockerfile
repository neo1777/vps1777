# syntax=docker/dockerfile:1.7
# Scheletro plugin bot — stesso schema di plugins/example-mcp/Dockerfile e dei
# servizi in services/*/Dockerfile: builder uv + runtime python:3.12-slim, utente non-root.
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.5.18 /uv /uvx /usr/local/bin/
# UV_PROJECT_ENVIRONMENT=/opt/venv: il venv nasce nel path finale → shebang corretti nel runtime.
# Prima nasceva in /build/.venv e veniva copiato in /opt/venv: gli script di bin/ puntavano
# ancora a /build/.venv/bin/python, che nel runtime non esiste (`python -m app` partiva lo
# stesso, ogni console-script del venv no).
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /build
COPY pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --no-dev --no-install-project
COPY app ./app
RUN --mount=type=cache,target=/root/.cache/uv uv sync --no-dev

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tini ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd -g 1000 bot && useradd -u 1000 -g 1000 -m -s /sbin/nologin bot
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /build/app /app/app
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
USER bot
ENTRYPOINT ["tini", "--", "python", "-m", "app"]
