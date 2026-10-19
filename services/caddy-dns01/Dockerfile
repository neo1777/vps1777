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
FROM caddy:2.11-builder-alpine@sha256:d6161a2c82fd58b3205048958fb6246d0c5d892beee8a47e90944610c4efd100 AS build
RUN xcaddy build --with github.com/caddy-dns/cloudflare@v0.2.4

# ─────────────────────────────────────────── runtime
FROM caddy:2.11-alpine@sha256:d8542f48d34a9cf4e4c11a478865229840e87e4c96ea3f439101f31a5d35f75f
COPY --from=build /usr/bin/caddy /usr/bin/caddy
# La versione del rilascio, come nelle altre immagini (release.yml la passa come
# build-arg): `vps1777 version` la legge dal container per segnalare la deriva.
ARG VPS1777_VERSION=0.0.0-dev
ENV VPS1777_VERSION=${VPS1777_VERSION}
