"""`nlm-auth` — chi monta i cookie di sessione Google, e chi lo dichiara (#139).

**Cinque** punti del repo dicevano che quel volume lo monta un solo servizio —
`SECURITY.md`, `docs/ARCHITECTURE.md` (due volte), `README.md` e un commento in
`compose.yaml`. A montarlo sono in **quattro**, e solo due passano da un compose:

    nb1777-mcp   compose.yaml               rw   è il servizio che li usa
    backup       compose.ops.backup.yaml    ro   feature attiva di DEFAULT
                                                 (`DEFAULT_FEATURES = {"backup", …}`)
    backup.sh    docker run sull'host       ro   dump nel tar → archivio cifrato age
    busybox      `vps1777 secrets-status`   ro   --network none, legge SOLO l'mtime

🔑 NON è un difetto di disegno, ed è il motivo per cui questo test presidia la DOC e non
   il compose: `tools/vps1777.py` esclude `nlm-auth` dallo snapshot pre-update *proprio
   perché* quello non è cifrato, e la ragione scritta accanto dice «…ed è nel backup age».
   Il progetto sa dove finiscono quei cookie. Chi legge SECURITY.md per valutare il
   rischio, no: da «un solo container» conclude una superficie che non è quella vera —
   «un processo» invece di «un processo + chi ha la chiave privata age».

⚠️ PERCHÉ IL PERIMETRO È «TUTTI I COMPOSE» E NON `compose.yaml`: la garanzia regge
   esattamente finché la si guarda dal file da cui è stata scritta. Su `compose.yaml` è
   vera. Su tutti i `compose*.yaml` (più i `plugins/*/`) è falsa. Il test parte dal
   glob, non dal file — se domani un overlay nuovo monta quel volume, qui è rosso.

🔴 SOLO STDLIB, e l'ho imparato dalla CI: la prima versione importava PyYAML — che il
   repo usa davvero, ma in un ALTRO job (`uv run --with pyyaml security/check_findings.py`).
   `tools/tests/` gira con `uvx pytest`, stdlib-only: in locale passava, in CI
   `ModuleNotFoundError: No module named 'yaml'` e la suite si fermava in COLLECT — cioè
   il mio test non falliva: impediva agli altri 267 di partire.
   ⇒ «la libreria è già una dipendenza del repo» non vuol dire «è disponibile in questo
   job». Qui i compose si leggono con un parser minimo, e il suo limite sta scritto
   in `_montaggi()`.
"""
from __future__ import annotations

import glob
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_VOLUME = "nlm-auth"

# Chi PUÒ montarlo, e perché. Aggiungere una voce qui è una decisione di sicurezza:
# ogni riga vede i cookie di sessione Google.
_ATTESI = {
    "nb1777-mcp": "rw — è il servizio che quei cookie li usa davvero",
    "backup": "ro — li salva nell'archivio cifrato con la sola chiave pubblica",
}

# 🔴 E I MONTAGGI NON SONO SOLO NEI COMPOSE — l'ho scoperto DOPO aver scritto la prima
#    versione di questo test, che ne vedeva due e li dichiarava «tutti». Due lavori a
#    tempo montano lo stesso volume con `docker run`, e nessuno dei due passa da un
#    compose:
#      tools/vps1777.py  nlm_cookie_status()  busybox --network none, legge solo l'mtime
#      tools/backup.sh   dump host            busybox, tar dentro l'archivio poi cifrato
#    ⚠️ IL LIMITE, dichiarato invece che taciuto: il primo costruisce il mount da una
#    VARIABILE (`vol = f"vps1777_{NLM_AUTH_VOLUME}"` → `-v f"{vol}:/src:ro"`), quindi
#    NESSUNA sonda testuale sul mount lo trova. Per questo qui si presidia il
#    RIFERIMENTO al volume — i file che lo nominano — e non la stringa del mount: è più
#    largo, e un punto nuovo obbliga chi lo scrive a passare di qui.
_FILE_CHE_LO_NOMINANO = {
    "tools/vps1777.py": "volume, mount della migrazione, esclusione dallo snapshot, nlm_cookie_status",
    "tools/backup.sh": "dump dei volumi (host e container)",
    "systemd/vps1777-secrets-check.service": "commento: legge la freschezza dei cookie",
    "services/nb1777-mcp/app/nlm_profile.py": "il servizio che li usa",
    "services/gateway/tests/test_nlm_artifact_ponte.py": "test: il gateway NON deve vederlo",
    "tools/tests/test_vps1777.py": "test della CLI: nomina il volume fra i DATA_VOLUMES",
}

# 📌 I file che affermano l'ESCLUSIVITÀ, .md e codice insieme. Sono sette e le forme
#    sono tre: le prime cinque le ho trovate cercando la frase nei documenti, la sesta
#    @b82df434 cercando il NOME DEL VOLUME fuori dai .md, la settima @71d540e6 cercando
#    il LESSICO dell'esclusività nel codice. Tre sonde, tre raccolti diversi — e il
#    numero si è fermato solo quando le sonde hanno smesso di guardare lo stesso posto.


def _compose_files() -> list[Path]:
    files = [Path(p) for p in glob.glob(str(_ROOT / "compose*.yaml"))]
    files += [Path(p) for p in glob.glob(str(_ROOT / "plugins" / "*" / "compose*.yaml"))]
    return sorted(files)


def _montaggi() -> dict[str, list[str]]:
    """servizio → [file:mount] per ogni servizio che monta il volume, ovunque.

    Parser minimo, stdlib-only (vedi la testa del file: qui PyYAML non c'è). Regge sulla
    forma dei nostri compose — `services:` a colonna 0, il nome del servizio a 2 spazi,
    i volumi come `      - <volume>:<path>[:ro|rw]`. **Il limite è dichiarato e presidiato**:
    una riga che monta il volume ma non è attribuibile a un servizio non viene ignorata,
    fa fallire il test — un parser che non capisce deve dirlo, non rispondere zero.
    """
    out: dict[str, list[str]] = {}
    for f in _compose_files():
        righe = f.read_text().splitlines()
        dentro_services = False
        servizio: str | None = None
        for riga in righe:
            if re.match(r"^services:\s*$", riga):
                dentro_services = True
                servizio = None
                continue
            if re.match(r"^\S", riga):           # un'altra chiave di primo livello
                dentro_services = riga.startswith("services:")
                servizio = None
                continue
            m = re.match(r"^  ([A-Za-z0-9][\w.-]*):\s*$", riga)
            if m and dentro_services:
                servizio = m.group(1)
                continue
            mv = re.match(r"^\s+-\s+" + re.escape(_VOLUME) + r":(\S+)", riga)
            if mv:
                assert servizio and dentro_services, (
                    f"{f.name}: monta `{_VOLUME}` in una riga che questo parser non sa "
                    f"attribuire a un servizio ({riga.strip()!r}). Il compose ha cambiato "
                    f"forma: aggiorna il parser invece di lasciarlo rispondere zero."
                )
                out.setdefault(servizio, []).append(f"{f.name}:{_VOLUME}:{mv.group(1)}")
    return out


def test_il_parser_vede_i_servizi_che_esistono():
    """Controprova sullo STRUMENTO: se il parser smettesse di riconoscere i servizi,
    `_montaggi()` tornerebbe vuoto e gli altri test direbbero «nessun montaggio» —
    uno zero che somiglia a una buona notizia. Qui si verifica che sappia ancora
    leggere il compose principale."""
    principale = _ROOT / "compose.yaml"
    righe = principale.read_text().splitlines()
    attesi = {m.group(1) for r in righe
              if (m := re.match(r"^  ([A-Za-z0-9][\w.-]*):\s*$", r))}
    assert "nb1777-mcp" in attesi and "gateway" in attesi, (
        f"il parser non riconosce più i servizi di compose.yaml: {sorted(attesi)}"
    )


def test_i_montaggi_sono_quelli_dichiarati():
    """Un montaggio in più è una decisione di sicurezza, non un dettaglio di compose."""
    trovati = _montaggi()
    assert set(trovati) == set(_ATTESI), (
        f"i servizi che montano `{_VOLUME}` non sono quelli attesi.\n"
        f"attesi:  {sorted(_ATTESI)}\ntrovati: { {k: v for k, v in trovati.items()} }\n"
        "Se il montaggio nuovo è voluto: aggiornare _ATTESI QUI, la frase in SECURITY.md "
        "e quella in docs/ARCHITECTURE.md — sono la stessa decisione scritta in tre posti."
    )


@pytest.mark.parametrize("doc", ["SECURITY.md", "docs/ARCHITECTURE.md"])
def test_la_doc_nomina_tutti_quelli_che_montano(doc):
    """La doc deve nominare OGNI servizio che monta il volume, nel punto dove ne parla.

    Non basta che i nomi esistano da qualche parte nel file: devono stare nella finestra
    in cui si parla di `nlm-auth`, che è quella che legge chi valuta il rischio.
    """
    righe = (_ROOT / doc).read_text().splitlines()
    idx = [i for i, r in enumerate(righe) if _VOLUME in r]
    assert idx, f"{doc}: non nomina mai `{_VOLUME}` — la garanzia non ha più un posto dove vivere"

    # la finestra: da 6 righe prima della prima occorrenza a 12 dopo l'ultima, per
    # coprire il paragrafo e la riga di tabella senza leggere tutto il documento
    finestra = "\n".join(righe[max(0, idx[0] - 6): idx[-1] + 12])
    for servizio in _ATTESI:
        assert servizio in finestra, (
            f"{doc}: parla di `{_VOLUME}` senza nominare `{servizio}`, che lo monta "
            f"({_ATTESI[servizio]}). Chi legge conclude una superficie più piccola di "
            f"quella vera."
        )


# 🔎 La SESTA copia della frase non era in un .md: stava nella docstring di
#    `services/nb1777-mcp/app/nlm_profile.py` — «nb1777-mcp è l'UNICO servizio che monta»
#    — e l'ha trovata @b82df434 cercando il nome del volume FUORI dai .md, cioè
#    esattamente dove una sonda sulla documentazione non guarda. Una docstring sbagliata
#    non fa sbagliare chi legge la doc: fa sbagliare chi SCRIVE il codice.
#    ⇒ le forme dell'esclusività sono due, e vanno cercate entrambe: «solo nb1777-mcp»
#      e «nb1777-mcp è l'unico».
_ESCLUSIVITA = (
    re.compile(r"\bsolo\W{0,4}`?nb1777-mcp`?", re.IGNORECASE),
    re.compile(r"nb1777-mcp\W{0,24}(?:è|e')\W{0,8}l['’]?\s?unico", re.IGNORECASE),
    # la SETTIMA copia (@71d540e6, services/gateway/app/settings.py): «nb1777-mcp,
    # l'unico servizio che monta quel volume» — nessun verbo fra il nome e «unico».
    re.compile(r"nb1777-mcp\W{0,6}l['’]\s?unico", re.IGNORECASE),
)
_QUALIFICA = re.compile(r"in esercizio|fra i servizi|dei servizi", re.IGNORECASE)


@pytest.mark.parametrize("doc", [
    "SECURITY.md",
    "docs/ARCHITECTURE.md",
    "README.md",
    "services/nb1777-mcp/app/nlm_profile.py",
    "services/gateway/app/settings.py",
])
def test_il_solo_e_qualificato(doc):
    """«solo nb1777-mcp» resta dicibile — ma solo se la frase dice DI COSA è il solo.

    È la parola che ha prodotto #139. Non va vietata: fra i **servizi in esercizio**
    quel volume lo monta davvero solo lui, ed è l'informazione che conta per chi teme un
    servizio compromesso. Va vietata **nuda**: senza la qualifica, chi legge conclude che
    nessun altro processo li tocca, e i lavori a tempo (backup, check scadenze) spariscono
    dal modello di minaccia.
    """
    testo = (_ROOT / doc).read_text()
    for pattern in _ESCLUSIVITA:
      for m in pattern.finditer(testo):
        intorno = testo[max(0, m.start() - 260): m.end() + 260]
        assert _QUALIFICA.search(intorno), (
            f"{doc}: «{m.group(0)}» senza qualifica. Fra i SERVIZI è vero; senza dirlo, "
            f"esclude il backup (che li cifra) e il check scadenze (che ne legge la data) "
            f"— e con loro la parte di superficie che quei due portano."
        )


def test_i_riferimenti_nel_codice_sono_quelli_dichiarati():
    """Un file nuovo che nomina il volume è una decisione di sicurezza da dichiarare.

    Presidia il RIFERIMENTO e non il mount, perché il mount può nascere da una variabile
    (vedi il commento su `_FILE_CHE_LO_NOMINANO`): questa sonda è volutamente più larga
    del bersaglio — preferisce un falso positivo, che costa una riga qui, a un montaggio
    invisibile, che costa una garanzia falsa nella doc di sicurezza.
    """
    trovati = set()
    for pattern in ("**/*.py", "**/*.sh", "**/*.service"):
        for f in _ROOT.glob(pattern):
            rel = f.relative_to(_ROOT).as_posix()
            if rel.startswith(".git/") or rel == "tools/tests/test_nlm_auth_montaggi.py":
                continue
            try:
                testo = f.read_text(errors="ignore")
            except OSError:
                continue
            if _VOLUME in testo or "NLM_AUTH_VOLUME" in testo:
                trovati.add(rel)
    assert trovati == set(_FILE_CHE_LO_NOMINANO), (
        f"i file che nominano `{_VOLUME}` non sono quelli dichiarati.\n"
        f"in più:  {sorted(trovati - set(_FILE_CHE_LO_NOMINANO))}\n"
        f"in meno: {sorted(set(_FILE_CHE_LO_NOMINANO) - trovati)}\n"
        "Se il punto nuovo MONTA il volume, va anche nella doc (SECURITY.md, "
        "docs/ARCHITECTURE.md, README.md); se lo nomina soltanto, basta dichiararlo qui."
    )


# 🔎 LA SONDA CHE MANCAVA, e l'ha scritta @b82df434 revisionando la #140: l'elenco
#    `_FILE_CHE_LO_NOMINANO` verifica CHE un file nomini il volume, mai COSA DICE su di
#    esso. Cercando l'AFFERMAZIONE invece del termine sono uscite altre cinque copie —
#    tutte in commenti e docstring, cioè nel posto peggiore: *una frase falsa in un
#    README fa sbagliare chi legge; in un commento accanto al codice fa sbagliare chi
#    scrive.* Qui la classe è presidiata alla radice: qualunque file del repo può dire
#    «unico/solo … monta» dei cookie, ma deve dire di cosa è il solo.
# ⚠️ Il verbo è al PRESENTE apposta: `\b(monta|montano|montare|mount)\b` non prende
#    «montava». Una frase storica — «prima il gateway montava in scrittura…» — non
#    promette niente su oggi, e chiederle una qualifica sarebbe rumore: il primo giro di
#    questa sonda l'aveva presa (`nlm_client.py:4`) e il falso positivo era suo, non del
#    file. Il prezzo dichiarato: un'esclusività scritta con un verbo che non è qui
#    («ad accedere», «a leggere») non la vede — se ne compare una, si allarga questa riga.
_AFFERMAZIONE = re.compile(
    r"(unic\w+|solo|soltanto)[^.\n]{0,80}\b(monta|montano|montare|mount)\b",
    re.IGNORECASE)
_PARLA_DEI_COOKIE = re.compile(r"nlm-auth|cookie", re.IGNORECASE)


def test_nessuna_esclusivita_nuda_sui_cookie_in_tutto_il_repo():
    """Nessun file — codice, compose, unit — può dire «l'unico che monta» dei cookie
    senza dire *di cosa* è l'unico. Il perimetro è il repo, non la documentazione."""
    fuori = []
    for pattern in ("**/*.py", "**/*.yaml", "**/*.sh", "**/*.service"):
        for f in _ROOT.glob(pattern):
            rel = f.relative_to(_ROOT).as_posix()
            if rel.startswith(".git/") or rel == "tools/tests/test_nlm_auth_montaggi.py":
                continue
            try:
                testo = f.read_text(errors="ignore")
            except OSError:
                continue
            for m in _AFFERMAZIONE.finditer(testo):
                intorno = testo[max(0, m.start() - 200): m.end() + 200]
                if not _PARLA_DEI_COOKIE.search(intorno):
                    continue          # parla di un altro volume: non è affar nostro
                if _QUALIFICA.search(intorno):
                    continue
                riga = testo[: m.start()].count("\n") + 1
                fuori.append(f"{rel}:{riga}  «{m.group(0).strip()}»")
    assert not fuori, (
        "affermazioni di esclusività NUDE sui cookie (dicono «l'unico che monta» senza "
        "dire di cosa è l'unico — e sui servizi è falsa: anche il container `backup` "
        "monta quel volume):\n  " + "\n  ".join(fuori)
    )
