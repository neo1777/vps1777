#!/usr/bin/env python3
"""Se l'installer può aprire il gateway su 0.0.0.0, la garanzia deve dirlo.

PERCHÉ ESISTE, per intero — serve a chi lo vedrà fallire.

`SECURITY.md` apre con:

> vps1777 espone su Internet **solo** il gateway (porta 443 via Tailscale Funnel /
> Caddy / Cloudflared).

Ed è vera nello stato normale. Ma `deploy.sh`, nel ramo `TS_FALLBACK=1`, scrive
`GATEWAY_BIND=0.0.0.0` nel `.env` quando il Funnel non risponde: il gateway finisce in
ascolto **su tutte le interfacce, sulla 8080 in HTTP**. Il *soggetto* della garanzia
regge (è sempre e solo il gateway); cambiano **la porta e il canale** — e passare da
HTTPS-via-tunnel a HTTP-in-chiaro sull'indirizzo pubblico è proprio la proprietà che
quella riga promette (issue #70).

## Cosa presidia, e cosa NON pretende

Non pretende che il fallback sparisca: è un rimedio esplicito e opt-in a una VPS che
resterebbe irraggiungibile, e l'alternativa — dire all'utente «entra e sistema» dopo
avergli detto che non serviva — è peggiore. *Il difetto era della frase, non del ramo.*

Presidia **l'accoppiamento**: finché nel repo esiste un percorso che porta il gateway su
`0.0.0.0`, `SECURITY.md` deve nominarlo. Le due cose stanno in due file che nessuno
apre insieme — chi domani aggiunge un secondo fallback (o cambia il meccanismo) non ha
niente che gli ricordi il documento.

⭐ E l'accoppiamento vale nei **due** versi, che è la parte che rende questo test diverso
da un grep: se un giorno il fallback venisse **tolto**, il paragrafo resterebbe a
descrivere un rischio inesistente — e un modello di sicurezza che elenca pericoli finti
si legge male quanto uno che ne tace di veri. In quel caso il test lo dice.

Stile: stdlib-only, legge i sorgenti.
Uso:  python3 tools/tests/test_garanzia_443_nomina_il_fallback.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEC = ROOT / "SECURITY.md"
DEPLOY = ROOT / "deploy.sh"


def _righe_di_codice(testo: str) -> str:
    """Le righe eseguibili di uno shell script: i commenti nominano il fallback per
    SPIEGARLO, e un grep sul testo grezzo li conterebbe come il meccanismo stesso."""
    return "\n".join(r.split("#", 1)[0] for r in testo.splitlines())


def main() -> int:
    if not (SEC.is_file() and DEPLOY.is_file()):
        print("✗ SECURITY.md o deploy.sh non trovati: la sonda non sta guardando il repo giusto")
        return 1
    sec, dep = SEC.read_text(encoding="utf-8"), _righe_di_codice(DEPLOY.read_text(encoding="utf-8"))

    # il percorso esiste? (nel CODICE, non nei commenti)
    apre = bool(re.search(r"GATEWAY_BIND=0\.0\.0\.0", dep))
    nominato = "TS_FALLBACK" in sec and "0.0.0.0" in sec

    if apre and not nominato:
        print("  ✗ `deploy.sh` può portare il gateway su 0.0.0.0 (ramo TS_FALLBACK) e\n"
              "      SECURITY.md non lo nomina. La garanzia «solo la 443 via tunnel»\n"
              "      descrive lo stato normale e tace su quello d'eccezione — che è\n"
              "      esattamente ciò che si va a cercare in un modello di sicurezza.")
        return 1
    if nominato and not apre:
        print("  ✗ SECURITY.md descrive il fallback TS_FALLBACK→0.0.0.0, ma nel codice di\n"
              "      deploy.sh quel percorso NON c'è più. Un modello di sicurezza che\n"
              "      elenca un pericolo inesistente si legge male quanto uno che ne tace:\n"
              "      se il fallback è stato tolto, il paragrafo va tolto con lui.")
        return 1

    if apre:
        print("  ✓ il fallback esiste in deploy.sh ed è nominato in SECURITY.md")
    else:
        print("  ✓ nessun percorso porta il gateway su 0.0.0.0, e il documento non lo promette")
    return 0


if __name__ == "__main__":
    sys.exit(main())
