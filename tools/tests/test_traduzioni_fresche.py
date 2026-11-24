"""Le traduzioni inglesi non possono mentire: o sono fresche, o la CI lo dice.

Perché esiste (01/09/2026, decisione dell'owner: «la CI che verifica anche la
doc … è la mia firma»): una doc bilingue ha un modo solo di morire — le due
copie divergono IN SILENZIO, e la copia stantia continua a sembrare buona. È la
stessa classe del «README ha detto 35 tool per due release», al quadrato,
perché qui il lettore della copia inglese non ha nemmeno l'originale davanti.

Il contratto: docs/en/MANIFEST.json registra, per ogni pagina inglese, lo
sha256 del sorgente italiano al momento della traduzione. Chi tocca l'italiano
di una pagina tradotta DEVE aggiornare la traduzione e poi riallineare l'hash
(`tools/aggiorna-traduzioni.py`). Stdlib-only, come il resto della suite."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
from pathlib import Path

RADICE = Path(__file__).resolve().parents[2]
MANIFEST = RADICE / "docs" / "en" / "MANIFEST.json"
DATI = json.loads(MANIFEST.read_text(encoding="utf-8"))
TRADUZIONI = DATI["traduzioni"]


def test_ogni_pagina_inglese_e_nel_manifest():
    """Una traduzione fuori manifest è una copia senza sorveglianza: il buco
    esatto che il manifest esiste per chiudere."""
    fuori = [p.name for p in (RADICE / "docs" / "en").glob("*.md")
             if f"docs/en/{p.name}" not in TRADUZIONI]
    assert not fuori, (
        f"pagine in docs/en/ non registrate nel MANIFEST: {fuori} — "
        "aggiungi la coppia (sorgente, sha256) o la copia invecchierà in silenzio")


def test_sorgenti_e_traduzioni_esistono():
    for en, voce in TRADUZIONI.items():
        assert (RADICE / en).is_file(), f"traduzione registrata ma assente: {en}"
        assert (RADICE / voce["sorgente"]).is_file(), (
            f"{en}: sorgente {voce['sorgente']} sparito — se il doc italiano è stato "
            "rinominato, la voce del manifest segue")


def test_le_traduzioni_sono_fresche():
    """IL verso che morde: l'italiano si è mosso dopo la traduzione → rosso,
    con l'elenco esatto e la cura. Niente warning: un warning schedulato non lo
    legge nessuno (lezione del trivy-verde-che-non-scansiona)."""
    stantie = []
    for en, voce in TRADUZIONI.items():
        reale = hashlib.sha256((RADICE / voce["sorgente"]).read_bytes()).hexdigest()
        if reale != voce["sorgente_sha256"]:
            stantie.append(f"{en} (sorgente {voce['sorgente']} cambiato)")
    assert not stantie, (
        "traduzioni STANTIE — l'originale italiano si è mosso dopo la traduzione:\n  "
        + "\n  ".join(stantie)
        + "\nCura: aggiorna la pagina inglese, POI `python3 tools/aggiorna-traduzioni.py`."
          " Aggiornare solo l'hash senza la traduzione è mentire al presidio.")


def test_l_aggiornatore_esiste_e_il_manifest_lo_nomina():
    """Il messaggio d'errore manda a uno strumento: deve esistere davvero."""
    assert (RADICE / "tools" / "aggiorna-traduzioni.py").is_file()
    assert "aggiorna-traduzioni" in DATI["_nota"]


# ── 24/11/2026: tre controlli in più, da una domanda del proprietario («la documentazione non era
#    legata a controlli fra inglese e italiano?»). Lo era, ma solo per la FRESCHEZZA: il manifest
#    diceva «l'italiano non si è mosso da quando hai tradotto». Non diceva se l'inglese era stato
#    toccato davvero, né se le due pagine si somigliano, né se una pagina mancava del tutto.
_spec = importlib.util.spec_from_file_location("aggiorna_traduzioni", RADICE / "tools" / "aggiorna-traduzioni.py")
aggiorna = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(aggiorna)


def test_la_traduzione_registrata_e_quella_sul_disco():
    """La seconda impronta: chi tocca l'inglese (o l'italiano) rilancia lo strumento, che guarda
    ENTRAMBE le pagine. Un manifest scritto a mano con la sola impronta del sorgente non passa."""
    fuori = [en for en, v in TRADUZIONI.items()
             if hashlib.sha256((RADICE / en).read_bytes()).hexdigest() != v.get("traduzione_sha256")]
    assert not fuori, (f"pagine inglesi cambiate dopo l'ultimo allineamento (o mai registrate): {fuori}\n"
                       "Cura: `python3 tools/aggiorna-traduzioni.py`.")


def _copia_di_prova(tmp_path):
    (tmp_path / "it.md").write_text("# Titolo\n\nuno\n", encoding="utf-8")
    (tmp_path / "en.md").write_text("# Title\n\none\n", encoding="utf-8")
    sha = aggiorna.sha
    return {"traduzioni": {"en.md": {"sorgente": "it.md", "sorgente_sha256": sha(tmp_path / "it.md"),
                                     "traduzione_sha256": sha(tmp_path / "en.md")}}}


def test_lo_strumento_rifiuta_di_riallineare_una_traduzione_non_toccata(tmp_path):
    """Il difetto di prima: bastava lanciarlo e tutto tornava «fresco»."""
    dati = _copia_di_prova(tmp_path)
    prima = dict(dati["traduzioni"]["en.md"])
    (tmp_path / "it.md").write_text("# Titolo\n\nuno\n\n## Una sezione nuova\n", encoding="utf-8")
    cambiate, rifiutate = aggiorna.allinea(dati, tmp_path, scrivi=True, solo_sorgente={})
    assert (cambiate, rifiutate) == (0, ["en.md"]) and dati["traduzioni"]["en.md"] == prima
    # tradotta davvero: ora si riallinea
    (tmp_path / "en.md").write_text("# Title\n\none\n\n## A new section\n", encoding="utf-8")
    assert aggiorna.allinea(dati, tmp_path, scrivi=True, solo_sorgente={}) == (1, [])
    assert aggiorna.allinea(dati, tmp_path, scrivi=True, solo_sorgente={}) == (0, [])


def test_il_caso_solo_italiano_si_dichiara_e_resta_scritto(tmp_path):
    dati = _copia_di_prova(tmp_path)
    (tmp_path / "it.md").write_text("# Titolo\n\nuno.\n", encoding="utf-8")       # un refuso
    assert aggiorna.allinea(dati, tmp_path, scrivi=True, solo_sorgente={"en.md": "refuso in italiano"}) == (1, [])
    assert dati["traduzioni"]["en.md"]["solo_sorgente"] == "refuso in italiano"


def _forma(p: Path, senza: tuple[str, ...] = ()) -> tuple[list[int], int, int]:
    """(livelli dei titoli in ordine, blocchi di codice, righe di tabella). `senza`: titoli da non contare."""
    livelli, blocchi, tabella, dentro = [], 0, 0, False
    for riga in p.read_text(encoding="utf-8").split("\n"):
        if riga.lstrip().startswith("```"):
            dentro = not dentro
            blocchi += dentro
            continue
        if dentro:
            continue
        m = re.match(r"^(#{1,6}) ", riga)
        if m and riga.strip() not in senza:
            livelli.append(len(m.group(1)))
        tabella += riga.startswith("|")
    return livelli, blocchi, tabella


# Il README inglese ha una sezione che l'italiano non ha, per costruzione: spiega a chi legge in
# inglese perché il resto è in italiano.
_SOLO_IN_INGLESE = {"README.md": ["## Language policy"]}


def test_le_due_lingue_hanno_la_stessa_struttura():
    """Stessi titoli (per livello e ordine), stessi blocchi di codice, stesse righe di tabella.
    Non dice che la traduzione è BUONA: dice che una sezione, un esempio o una riga di tabella
    aggiunti in una lingua ci sono anche nell'altra. È il caso che la sola impronta non vedeva."""
    diverse = []
    for en, voce in TRADUZIONI.items():
        it = _forma(RADICE / voce["sorgente"])
        extra = tuple(_SOLO_IN_INGLESE.get(en, []))
        for titolo in extra:
            assert f"\n{titolo}\n" in (RADICE / en).read_text(encoding="utf-8"), f"{en}: «{titolo}» non c'è più: toglilo dall'elenco"
        livelli, blocchi, tabella = _forma(RADICE / en, senza=extra)
        if (livelli, blocchi, tabella) != it:
            diverse.append(f"{en}: titoli {len(it[0])}/{len(livelli)}, blocchi di codice {it[1]}/{blocchi}, "
                           f"righe di tabella {it[2]}/{tabella} (italiano/inglese)")
    assert not diverse, "struttura diversa fra italiano e inglese:\n  " + "\n  ".join(diverse)


def test_ogni_pagina_di_docs_e_tradotta_o_dichiarata_solo_italiana():
    """Una pagina nuova non resta senza traduzione per dimenticanza: o entra fra le traduzioni, o
    nell'elenco `solo_italiano` del manifest, col motivo."""
    tradotte = {v["sorgente"] for v in TRADUZIONI.values()}
    solo = {k: v for k, v in DATI["solo_italiano"].items() if not k.startswith("_")}
    pagine = {f"docs/{p.name}" for p in (RADICE / "docs").glob("*.md")}
    assert not (pagine - tradotte - set(solo)), f"pagine né tradotte né dichiarate: {sorted(pagine - tradotte - set(solo))}"
    assert not (set(solo) & tradotte), f"dichiarate solo italiane ma tradotte: {sorted(set(solo) & tradotte)}"
    assert not (set(solo) - pagine), f"dichiarate ma sparite: {sorted(set(solo) - pagine)}"
    assert all(isinstance(m, str) and len(m) > 15 for m in solo.values())


def test_la_struttura_morde_su_una_sezione_non_tradotta(tmp_path):
    """Controprova: una sezione aggiunta solo in italiano cambia la forma."""
    shutil.copy(RADICE / "docs" / "UPDATE.md", tmp_path / "it.md")
    prima = _forma(tmp_path / "it.md")
    with (tmp_path / "it.md").open("a", encoding="utf-8") as f:
        f.write("\n## Una sezione in più\n\n```bash\ntrue\n```\n")
    assert _forma(tmp_path / "it.md") != prima
