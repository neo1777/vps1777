# syntax=docker/dockerfile:1.7
#
# vps1777 gateway — multi-stage build con uv + distroless runtime.
#
# Stage 1 (builder): python:3.12-slim + uv → installa deps + pacchetto in /opt/venv
# Stage 2 (runtime): distroless/python3 nonroot (UID 65532) + venv copiato
#
# Output image: ~80-100 MB, no shell, no apt, no package manager.

# ─────────────────────────────────────────────────────────────────────── builder
FROM python:3.12-slim AS builder

# Installa uv (manager Python ufficiale Astral, lock + install veloce)
COPY --from=ghcr.io/astral-sh/uv:0.5.18 /uv /uvx /usr/local/bin/

ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1

WORKDIR /build

# Copia metadata prima del codice → cache layer migliore
COPY pyproject.toml ./
# (uv.lock opzionale — se non c'è uv lo crea)

# Crea venv + installa dipendenze (BuildKit cache mount per --no-install-project)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project 2>/dev/null || \
    uv sync --no-dev --no-install-project

# Copia codice e installa il pacchetto
COPY app ./app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev

# ─────────────────────────────────────────────────────────────────────── runtime
FROM gcr.io/distroless/python3-debian12:nonroot

# Copia venv intero (sotto /build/.venv) + codice
COPY --from=builder /build/.venv /opt/venv
COPY --from=builder /build/app /app/app

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

EXPOSE 8080

# Distroless nonroot già esegue come UID 65532 ("nonroot")
USER nonroot

# Entry point: chiama il main del package
ENTRYPOINT ["python", "-m", "app"]
