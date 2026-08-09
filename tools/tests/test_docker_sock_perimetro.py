#!/usr/bin/env python3
"""Nessun compose monta il docker.sock — tranne UNO, nominato, e solo con l'avviso scritto.

PERCHÉ ESISTE, per intero — serve a chi lo vedrà fallire.

Montare `/var/run/docker.sock` in un container significa dargli **accesso root all'host**:
chi raggiunge quel socket parla con l'API Docker e può creare un container che monta `/`.
Il finding H13 lo dice, e il repo ha già la lezione scritta in `compose.ops.backup.yaml`
(«NIENTE docker.sock (finding 2.8/H13)»).

## Il difetto che questo file cura (issue #69, punto ②)

Il gate di H13 era:

    evidence:
      - file: compose.ops.backup.yaml
        not_contains: ["/var/run/docker.sock"]

⇒ garantiva **«il container di backup non monta il socket»** — vero — mentre la proprietà
che interessa a chi legge un registro di sicurezza è **«nessun container di questo repo
monta il socket»**, che è un'altra cosa. Se domani un compose nuovo lo montasse, H13
resterebbe `closed` e verde: *il gate guarda un nome di file, non la proprietà.*
⭐ È la forma che ci è costata tutto il 09/08: una sonda che risponde benissimo a una
domanda VICINA a quella che si ha in testa.

## Cosa presidia, e perché l'eccezione è dentro il test

`compose.ops.watchtower.yaml` il socket lo monta davvero, e resta: quel profilo è opt-in,
non attivo di default, e Watchtower è dichiarato declassato. **L'eccezione non si toglie:
si NOMINA** — così è una decisione scritta invece di un'assenza di controllo, e aggiungerne
una seconda richiede di modificare questo file, cioè di dichiararla.

E l'eccezione è **condizionata**: vale solo finché accanto al mount resta l'avviso che
`:ro` non limita l'API. *Senza quell'avviso chi attiva il profilo legge `:ro` e ha ogni
ragione di intenderlo come una limitazione.* Se qualcuno cancella il commento «per pulizia»,
questo test diventa rosso: il perché non può sparire in silenzio lasciando il cosa.

Stile: stdlib-only, nessuna dipendenza — gira ovunque giri Python.
Uso:  python3 tools/tests/test_docker_sock_perimetro.py     (esce 1 al primo difetto)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOCK = "/var/run/docker.sock"

# L'eccezione, nominata: file → (ragione, aghi che DEVONO restare accanto al mount).
# Aggiungerne una significa modificare questa riga, cioè dichiararla per iscritto.
ECCEZIONI: dict[str, tuple[str, tuple[str, ...]]] = {
    "compose.ops.watchtower.yaml": (
        "profilo ops.autoupdate: opt-in, non attivo di default, Watchtower declassato",
        ("`:ro` NON LIMITA L'API", "accesso root all'host"),
    ),
    # 🔎 TROVATO DA QUESTO TEST AL PRIMO GIRO (09/08), e non era nella issue #69: quella
    # nominava solo watchtower e diceva «se un domani un ALTRO compose lo montasse, H13
    # resterebbe verde». Non era un domani — c'era già, e nessuno se n'era accorto perché
    # il gate guardava un file solo. *La proprietà che un presidio non misura non è
    # «probabilmente a posto»: è semplicemente non misurata.*
    # Portainer senza socket non esiste (è la sua funzione): l'alternativa non è montarlo
    # meglio, è non attivare il profilo. Qui non c'è nemmeno `:ro` — ed è più onesto.
    "compose.ops.portainer.yaml": (
        "profilo ops.portainer: opt-in, porta su loopback (tunnel SSH), no-new-privileges",
        ("ACCESSO ROOT ALL'HOST", "non attivare il profilo"),
    ),
}


def main() -> int:
    compose = sorted(p for p in ROOT.glob("compose*.y*ml") if p.is_file())
    if not compose:
        print("✗ nessun compose trovato: la sonda non sta guardando il repo giusto")
        return 1
    print(f"perimetro: {len(compose)} file compose*.y*ml")

    errori = 0
    montano = []
    for p in compose:
        testo = p.read_text(encoding="utf-8")
        # solo le righe EFFETTIVE: un commento che nomina il socket (come in
        # compose.ops.backup.yaml, che spiega perché NON lo monta) non è un mount.
        righe = [r for r in testo.splitlines()
                 if SOCK in r and not r.lstrip().startswith("#")]
        if not righe:
            continue
        montano.append(p.name)
        if p.name not in ECCEZIONI:
            errori += 1
            print(f"  ✗ {p.name} monta {SOCK} e NON è fra le eccezioni nominate.\n"
                  f"      È accesso root all'host (il `:ro` non limita l'API Docker).\n"
                  f"      Se è deliberato, aggiungilo a ECCEZIONI con la ragione: una\n"
                  f"      decisione scritta, non un controllo che tace.")
            continue
        ragione, aghi = ECCEZIONI[p.name]
        mancanti = [a for a in aghi if a not in testo]
        if mancanti:
            errori += 1
            print(f"  ✗ {p.name}: l'eccezione è ammessa ({ragione}) ma l'AVVISO è sparito.\n"
                  f"      Manca: {mancanti}\n"
                  f"      Chi attiva il profilo legge `:ro` e lo intende come una\n"
                  f"      limitazione: senza l'avviso, il cosa resta e il perché no.")
        else:
            print(f"  ✓ {p.name} — eccezione nominata, avviso presente ({ragione})")

    non_montano = len(compose) - len(montano)
    print(f"\n  {non_montano}/{len(compose)} compose NON montano il socket · "
          f"{len(montano)} lo montano ({', '.join(montano) or '—'})")
    # controprova positiva: se NESSUNO lo montasse, l'eccezione sarebbe morta e questo
    # test non starebbe più presidiando niente — va detto, non lasciato passare in verde.
    if not montano:
        print("  ⚠️ nessun compose monta il socket: l'eccezione in ECCEZIONI è ormai\n"
              "     senza oggetto — toglila, o questo test presidia una regola vuota.")
    return 1 if errori else 0


if __name__ == "__main__":
    sys.exit(main())
