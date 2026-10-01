# syntax=docker/dockerfile:1.7
#
# vps1777 caddy-dns01 — Caddy con il plugin DNS di Cloudflare, per la feature
# OPZIONALE `caddy-dns01` (overlay compose.ops.caddy-dns01.yaml, docs/INGRESS.md).
#
# PERCHÉ UN'IMMAGINE NOSTRA: l'immagine ufficiale `caddy` non contiene provider DNS,
# e la sfida ACME DNS-01 (certificati senza porta 80, o wildcard) ne vuole uno. Il
# plugin si compila dentro il binario con xcaddy: non esiste un «caddy + cloudflare»
# ufficiale da pinnare. Costruirla qui significa che passa dalla stessa catena delle
# altre immagini — build in CI, firma cosign, digest in images.lock, scansione Trivy —
# invece di essere un'immagine di terzi presa sulla fiducia.
#
# 📏 MISURATO il 01/10/2026: su Caddy 2.8 il plugin cloudflare@v0.2.4 NON compila
#   (`undefined: zapslog.HandlerOptions`); su 2.11 sì. Per questo la base è la stessa
#   2.11 dell'ingresso normale (compose.ingress.caddy.yaml): chi passa da HTTP-01 a
#   DNS-01 cambia il modo di ottenere il certificato, non la versione di Caddy.
#
# ⚠️ Niente uv.lock né Python: è l'unico servizio di services/ senza pyproject.toml
#   (test_lock_nella_build.py lo esenta per questo, non per nome).
# Il token Cloudflare NON entra nell'immagine né nell'ambiente: Caddy lo legge da
# /run/secrets/cf_api_token col segnaposto {file.…} (ingress/Caddyfile.dns01).

# ─────────────────────────────────────────── builder
FROM caddy:2.11-builder-alpine@sha256:0aa610043dab5da82ad0a0268e46bb852785e6f5160f12f1c6fe3f42903d7e1b AS build
RUN xcaddy build --with github.com/caddy-dns/cloudflare@v0.2.4

# ─────────────────────────────────────────── runtime
FROM caddy:2.11-alpine@sha256:6aeddd44c3078b0f9a35206472a11420648a79c184603ef95957d0a20044cb2b
COPY --from=build /usr/bin/caddy /usr/bin/caddy
# La versione del rilascio, come nelle altre immagini (release.yml la passa come
# build-arg): `vps1777 version` la legge dal container per segnalare la deriva.
ARG VPS1777_VERSION=0.0.0-dev
ENV VPS1777_VERSION=${VPS1777_VERSION}
