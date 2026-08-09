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

# I DUE file che possono portare il gateway su 0.0.0.0, ciascuno col pattern che lo dice.
# ⚠️ Il perimetro era UN file solo (`deploy.sh`), e il rilievo di abdd732a sulla #133 non
# era «copertura mancante»: era uno scenario in cui il test **chiede di togliere una
# garanzia ancora necessaria**. Se un domani il ramo `TS_FALLBACK` sparisce da deploy.sh e
# restano i tre di engine.py → `apre=False`, `nominato=True` → scatta il ramo «SECURITY.md
# descrive un pericolo inesistente, il paragrafo va tolto». *Il pericolo esisterebbe ancora,
# in un file che il test non guardava.* ⇒ un presidio col perimetro stretto non è solo
# cieco: può dare un ordine sbagliato con la voce di chi ha misurato.
PERCORSI = {
    "deploy.sh": (ROOT / "deploy.sh", re.compile(r"GATEWAY_BIND=0\.0\.0\.0")),
    "installer/engine.py": (ROOT / "installer" / "engine.py",
                            re.compile(r'_set_gateway_bind\([^)]*"0\.0\.0\.0"')),
}


def _righe_di_codice(testo: str) -> str:
    """Le righe eseguibili di uno shell script: i commenti nominano il fallback per
    SPIEGARLO, e un grep sul testo grezzo li conterebbe come il meccanismo stesso."""
    return "\n".join(r.split("#", 1)[0] for r in testo.splitlines())


def main() -> int:
    if not SEC.is_file():
        print("✗ SECURITY.md non trovato: la sonda non sta guardando il repo giusto")
        return 1
    mancanti = [n for n, (p, _) in PERCORSI.items() if not p.is_file()]
    if mancanti:
        # Un file del perimetro che sparisce NON è «un percorso in meno»: è la sonda che
        # non può più rispondere. Tacerlo lascerebbe `apre=False` per assenza di dati, e
        # quel False finisce dritto nel ramo «togli il paragrafo».
        print(f"✗ non trovo {', '.join(mancanti)}: NON posso dire se il fallback esiste.\n"
              "      (assenza di file ≠ assenza del percorso — e qui la differenza decide\n"
              "      se questo test chiede di TOGLIERE una garanzia.)")
        return 1
    sec = SEC.read_text(encoding="utf-8")

    # il percorso esiste? (nel CODICE, non nei commenti) — su OGNI file del perimetro
    dove = [n for n, (p, rx) in PERCORSI.items()
            if rx.search(_righe_di_codice(p.read_text(encoding="utf-8")))]
    apre = bool(dove)
    nominato = "TS_FALLBACK" in sec and "0.0.0.0" in sec

    if apre and not nominato:
        print(f"  ✗ il prodotto può portare il gateway su 0.0.0.0 ({', '.join(dove)}) e\n"
              "      SECURITY.md non lo nomina. La garanzia «solo la 443 via tunnel»\n"
              "      descrive lo stato normale e tace su quello d'eccezione — che è\n"
              "      esattamente ciò che si va a cercare in un modello di sicurezza.")
        return 1
    if nominato and not apre:
        print("  ✗ SECURITY.md descrive il fallback →0.0.0.0, ma in NESSUNO dei file del\n"
              f"      perimetro ({', '.join(PERCORSI)}) quel percorso c'è più. Un modello\n"
              "      di sicurezza che elenca un pericolo inesistente si legge male quanto\n"
              "      uno che ne tace: se il fallback è stato tolto, va tolto il paragrafo.")
        return 1

    if apre:
        print(f"  ✓ il fallback esiste ({', '.join(dove)}) ed è nominato in SECURITY.md")
    else:
        print("  ✓ nessun percorso porta il gateway su 0.0.0.0, e il documento non lo promette")
    return 0


def test_presidio_gira_anche_in_ci() -> None:
    """Il gancio senza il quale questo file NON viene eseguito dalla CI.

    `uvx pytest tools/tests/ -v` esegue le FUNZIONI `test_*`. Un file con solo `main()` +
    `if __name__` viene raccolto — il nome combacia — e non esegue niente: verde su zero
    test. Il 09/08 tre presidi erano in quello stato su `main` (misurato sabotandone uno:
    la suite restava «250 passed»), e questa PR era l'unica ancora aperta, cioè l'unica in
    cui si poteva curare PRIMA invece che dopo. Rilievo di abdd732a.
    ⭐ *Un test che non gira non è una verifica: è un commento con le parentesi.*
    """
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
