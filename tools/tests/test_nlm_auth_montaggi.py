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

Solo stdlib + PyYAML (già dipendenza dei gate del repo). Nessun docker, nessuna rete.
"""
from __future__ import annotations

import glob
import re
from pathlib import Path

import pytest
import yaml

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


def _compose_files() -> list[Path]:
    files = [Path(p) for p in glob.glob(str(_ROOT / "compose*.yaml"))]
    files += [Path(p) for p in glob.glob(str(_ROOT / "plugins" / "*" / "compose*.yaml"))]
    return sorted(files)


def _montaggi() -> dict[str, list[str]]:
    """servizio → [file:mount] per ogni servizio che monta il volume, ovunque."""
    out: dict[str, list[str]] = {}
    for f in _compose_files():
        try:
            d = yaml.safe_load(f.read_text()) or {}
        except yaml.YAMLError as exc:  # un compose illeggibile è un rosso, non uno zero
            pytest.fail(f"{f.name}: YAML non parsabile ({exc})")
        for nome, svc in (d.get("services") or {}).items():
            for v in ((svc or {}).get("volumes") or []):
                riga = v if isinstance(v, str) else str(v)
                if riga.split(":")[0] == _VOLUME:
                    out.setdefault(nome, []).append(f"{f.name}:{riga}")
    return out


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


@pytest.mark.parametrize("doc", ["SECURITY.md", "docs/ARCHITECTURE.md", "README.md"])
def test_il_solo_e_qualificato(doc):
    """«solo nb1777-mcp» resta dicibile — ma solo se la frase dice DI COSA è il solo.

    È la parola che ha prodotto #139. Non va vietata: fra i **servizi in esercizio**
    quel volume lo monta davvero solo lui, ed è l'informazione che conta per chi teme un
    servizio compromesso. Va vietata **nuda**: senza la qualifica, chi legge conclude che
    nessun altro processo li tocca, e i lavori a tempo (backup, check scadenze) spariscono
    dal modello di minaccia.
    """
    testo = (_ROOT / doc).read_text()
    for m in re.finditer(r"\bsolo\W{0,4}`?nb1777-mcp`?", testo, re.IGNORECASE):
        intorno = testo[max(0, m.start() - 260): m.end() + 260]
        assert re.search(r"in esercizio|fra i servizi|dei servizi", intorno, re.IGNORECASE), (
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
