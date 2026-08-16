"""Ogni immagine di TERZI nei compose è digest-pinnata — o il test la nomina.

🔓 Gemella dichiarata di `test_actions_pinnate_a_sha.py` (abdd732a, PR #143), che
   presidia la prima metà di `SECURITY.md:171-175`. Questa presidia l'ultima riga
   dello stesso punto elenco, che era rimasta scoperta e lo era **per dichiarazione**:

     «Le immagini di terzi nei compose sono digest-pinnate.»

   Verificata il 10/08 su `origin/main` (206abdf): **5 immagini di terzi su 5**
   portano `@sha256:` — caddy · alpine · cloudflared · watchtower · portainer.
   La garanzia REGGE, e come la gemella merita un presidio proprio per questo:
   *una promessa vera e non presidiata è una promessa che nessuno saprà quando
   smette di esserlo.*

⚠️ LA PAROLA CHE DECIDE È «TERZI», E NON È UN'INTERPRETAZIONE: sta nella frase.
   Nei compose ci sono **13** `image:`, e pretendere il digest da tutte darebbe un
   rosso permanente su 8 righe legittime — *il falso allarme che insegna a ignorare
   gli allarmi*, cioè il modo in cui un presidio si fa disattivare. Le 8 non sono
   scoperte: sono coperte **altrove**, e le due esenzioni qui sotto dicono dove.

   ① `vps1777/…`      4 immagini, in `compose.build.yaml` — hanno un `build:`
                      accanto: si COSTRUISCONO qui, non si scaricano da nessuno.
                      Non esiste un digest a monte da pinnare.
   ② `${…}` nel rif.   4 immagini, in `compose.yaml` — il tag è parametrico
                      (`${VPS1777_TAG:-dev}`) e un digest non è nemmeno esprimibile.
                      Sono le nostre da GHCR, e SECURITY.md le copre col punto
                      successivo: «le immagini si pullano da GHCR e si verificano
                      contro `images.lock` del bundle». Presidio vero, non promessa:
                      `release.yml` risolve i digest delle 4 immagini appena pushate
                      (r.177-192) e `tools/vps1777.py` li verifica (r.1199, 2538).

🔑 IL DEFAULT È SEVERO, ED È IL PUNTO DEL DISEGNO. Le esenzioni sono una lista, e
   una lista scritta a mano dimentica sempre qualcuno — quello che conta è **cosa
   succede a chi non è in lista**. Qui chi non è in lista è «di terzi» e deve essere
   pinnato: un `redis:7` aggiunto domani non prende un'esenzione per silenzio, prende
   un rosso. *Una lista di esenzioni è sicura quando il default urla; è pericolosa
   quando il default tace.*

🔑 E il difetto che previene non è teorico: basta che una di noi scriva
   `image: qualcosa:latest` — la forma che ogni README del mondo suggerisce — e la
   riga di SECURITY.md diventa falsa **senza che nessun file cambi il proprio testo**.

STDLIB-ONLY: `tools/tests/` gira con `uvx pytest tools/tests/` (ci.yml), che non ha
PyYAML. Niente import di terze parti, e niente `importorskip` — uno skip qui si
leggerebbe come un pass.
"""
from __future__ import annotations

import re
from pathlib import Path

RADICE = Path(__file__).resolve().parents[2]

# `image:` con valore, ignorando i commenti in coda (`@sha256:…  # digest pinnato`
# è la forma che usiamo in compose.ops.portainer.yaml, ed è quella giusta: il
# commento parla all'umano, il digest alla macchina).
IMMAGINE = re.compile(r"^\s*image:\s*([^\s#]+)")
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")


def _compose():
    """I file compose della radice. `compose*.y*ml` è il nome che usa il progetto
    (compose.yaml + gli overlay compose.<ruolo>.<cosa>.yaml)."""
    return sorted(RADICE.glob("compose*.yaml")) + sorted(RADICE.glob("compose*.yml"))


def _immagini():
    """(file, riga, valore) di ogni `image:` nei compose."""
    fuori = []
    for f in _compose():
        for n, riga in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            m = IMMAGINE.match(riga)
            if m:
                fuori.append((f.name, n, m.group(1)))
    return fuori


def _e_di_terzi(valore: str) -> bool:
    """False solo per le due esenzioni motivate nel docstring. Tutto il resto è di
    terzi e va pinnato: è qui che sta la severità del default, e se un giorno si
    aggiunge un'esenzione va aggiunta QUI, dove chi legge il test la vede — non
    allargando la regex del digest, dove sparirebbe."""
    return not (valore.startswith("vps1777/") or "${" in valore)


def test_ci_sono_compose_e_immagini_di_terzi_da_controllare():
    """La guardia della guardia: se i compose sparissero, cambiassero nome o le
    immagini di terzi finissero altrove, il test sotto passerebbe su una lista
    VUOTA — verde per assenza di bersaglio, che è il modo più comune in cui un
    presidio smette di proteggere senza diventare rosso."""
    assert _compose(), f"nessun file compose*.y*ml in {RADICE}"
    terzi = [v for _, _, v in _immagini() if _e_di_terzi(v)]
    assert len(terzi) >= 4, (
        f"solo {len(terzi)} immagini di terzi trovate nei compose: erano 5 il "
        "10/08/2026 (caddy, alpine, cloudflared, watchtower, portainer). Se gli "
        "overlay si sono spostati, questo test sta guardando nel vuoto."
    )


def test_ogni_immagine_di_terzi_e_digest_pinnata():
    """SECURITY.md: «Le immagini di terzi nei compose sono digest-pinnate»."""
    non_pinnate = [
        f"{f}:{n}  image: {v}"
        for f, n, v in _immagini()
        if _e_di_terzi(v) and not DIGEST.search(v)
    ]
    assert not non_pinnate, (
        "SECURITY.md dichiara «Le immagini di terzi nei compose sono "
        "digest-pinnate»: un tag mobile ripuntato a monte può cambiare il "
        "contenuto sotto di noi.\n"
        "Queste non lo sono — o si pinnano al digest, o la frase in SECURITY.md "
        "va corretta (le due cose insieme, mai una sola). Se invece è un'immagine "
        "NOSTRA, l'esenzione va dichiarata in `_e_di_terzi()` col suo perché:\n  "
        + "\n  ".join(non_pinnate)
    )
