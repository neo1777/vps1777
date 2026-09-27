# syntax=docker/dockerfile:1.7
#
# vps1777 nb1777-mcp — NotebookLM via CLI `nlm`.
#
# Runtime: python:3.12-slim + tini. NIENTE browser dalla 0.61.0: fino alla 0.60.0 qui
# c'erano `chromium` e le librerie di Playwright «per nlm headless», ma il server non
# lancia mai il browser. nlm lo userebbe solo per il refresh headless, che è spento
# (NOTEBOOKLM_DISABLE_HEADLESS_REFRESH=1 in compose.yaml) e che in ogni caso vuole un
# profilo di browser salvato che nel container non c'è: da /admin/nlm arrivano solo i
# cookie. Chromium pesava 376 MB su 902 MB. Presidio: tools/tests/test_nb1777_senza_browser.py.

# ─────────────────────────────────────── builder
FROM python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f AS builder
COPY --from=ghcr.io/astral-sh/uv:0.5.18@sha256:e2101b9e627153b8fe4e8a1249cc4194f1b38ece7f28a5a9b8f958e3b560e69c /uv /uvx /usr/local/bin/
# UV_PROJECT_ENVIRONMENT=/opt/venv: costruisce il venv direttamente nel path
# finale, così gli shebang dei console-script (es. `nlm`) puntano a
# /opt/venv/bin/python (esistente nel runtime). Senza, il venv nasce in
# /build/.venv e gli script restano con shebang rotto → ENOENT all'exec di nlm.
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

# ─────────────────────────────────────── runtime
FROM python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        tini ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Utente non-root condiviso (UID 1000 "app") — STESSO uid di gateway/bot
# così il volume nlm-auth è accessibile da tutti i servizi che lo montano.
RUN groupadd -g 1000 app && useradd -u 1000 -g 1000 -m -s /sbin/nologin app

# Il pip della BASE è peso morto qui: le dipendenze le installa uv nel builder
# (/opt/venv) e a runtime nessuno lo chiama — ma è l'unica fonte di CVE
# ricorrenti sulle immagini (issue #263: 6 CVE con fix che python:3.12-slim
# non porta ancora). Un tool inutilizzato che accumula CVE si rimuove.
RUN python -m pip uninstall -y pip
# ── ANCHE nlm-artifacts, e con l'owner giusto: la dir è nata (24/08) senza chown,
#    il named volume ne ha copiato l'ownership root e OGNI studio_download moriva
#    in «Download failed» senza diagnosi (misurato 05/09; dentro il container il
#    chown è impossibile anche da root: cap_drop ALL toglie CAP_CHOWN).
RUN mkdir -p /var/lib/nlm /var/lib/nlm-artifacts && \
    chown -R app:app /var/lib/nlm /var/lib/nlm-artifacts

# Copia venv (già in /opt/venv, shebang corretti) + codice dal builder
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /build/app /app/app

# Versione iniettata dalla CI di release (build-arg); nei build locali resta dev.
ARG VPS1777_VERSION=0.0.0-dev
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NLM_HOME=/var/lib/nlm \
    HOME=/var/lib/nlm \
    VPS1777_VERSION=${VPS1777_VERSION}

WORKDIR /app
USER app

EXPOSE 8003

# tini come PID 1 per signal handling pulito
ENTRYPOINT ["tini", "--", "python", "-m", "app"]
