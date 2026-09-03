# syntax=docker/dockerfile:1.7
# vps1777 archive-mcp — python:3.12-slim non-root.
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.5.18 /uv /uvx /usr/local/bin/
# UV_PROJECT_ENVIRONMENT=/opt/venv: venv nel path finale → shebang corretti nel runtime.
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /build
# 🔒 IL LOCK ENTRA NELLA BUILD (rilievo `23cc4783`, round-16). Prima qui c'era
#   solo `pyproject.toml` e `uv sync` senza `--frozen`: **ogni ricostruzione
#   risolveva le dipendenze da capo** e poteva prendere una minore nuova.
#   ⚠️ E i lock che c'erano NON servivano a niente: `nb1777-mcp` e `nb1777-bot`
#   avevano `uv.lock` nel repo e **nessun Dockerfile lo copiava** — versionato e
#   mai usato. *Il file esisteva, la garanzia no.*
# 🔑 `--frozen` è la metà che conta: senza, `uv sync` **riscriverebbe** il lock
#   se non combacia col pyproject, e la build tornerebbe a decidere da sé. Con
#   `--frozen` fallisce e lo dice — che è ciò che deve fare un lock.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
COPY app ./app
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tini ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd -g 1000 app && useradd -u 1000 -g 1000 -m -s /sbin/nologin app

# Il pip della BASE è peso morto qui: le dipendenze le installa uv nel builder
# (/opt/venv) e a runtime nessuno lo chiama — ma è l'unica fonte di CVE
# ricorrenti sulle immagini (issue #263: 6 CVE con fix che python:3.12-slim
# non porta ancora). Un tool inutilizzato che accumula CVE si rimuove.
RUN python -m pip uninstall -y pip
RUN mkdir -p /var/lib/archive/db /var/lib/archive/data && chown -R app:app /var/lib/archive
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /build/app /app/app
# Versione iniettata dalla CI di release (build-arg); nei build locali resta dev.
ARG VPS1777_VERSION=0.0.0-dev
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    VPS1777_VERSION=${VPS1777_VERSION}
WORKDIR /app
USER app
EXPOSE 8002
ENTRYPOINT ["tini", "--", "python", "-m", "app"]
