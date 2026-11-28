"""Le strade di `main()` del controllo del registro che nessuna prova percorreva (QUA-04).

PERCHÉ ESISTE. Il 24/11/2026 `main()` di `security/check_findings.py` misurava complessità
40, e le prove ne percorrevano 59 rami su 78. Fra i 19 scoperti: il modo «epoca», il registro
assente, il CHANGELOG senza versioni, i tre confronti con SECURITY.md quando il documento
cambia forma, e le righe che il controllo stampa senza accusare (voci senza natura, senza
scoperta, sorvegliate, non ancora rilasciate). Si scrivono PRIMA di spezzarla.

Il metodo è quello di `test_checker_sa_rifiutare.py`: si parte dal registro VERO e da
SECURITY.md VERO, e si manomettono. Stdlib + PyYAML (che il controllo stesso richiede).
"""
from __future__ import annotations

import contextlib
import copy
import importlib.util
import io
import re
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="check_findings.py stesso richiede PyYAML")

_ROOT = Path(__file__).resolve().parents[2]
_CHECKER = _ROOT / "security" / "check_findings.py"
_REGISTRO = yaml.safe_load((_ROOT / "security" / "findings.yml").read_text(encoding="utf-8"))
_SECURITY = (_ROOT / "SECURITY.md").read_text(encoding="utf-8")


def _carica():
    spec = importlib.util.spec_from_file_location("cf_percorsi", _CHECKER)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture()
def cf(tmp_path, monkeypatch):
    m = _carica()
    m._tmp = tmp_path
    monkeypatch.setattr(sys, "argv", ["check_findings.py"])
    return m


def _esegui(m, registro: dict | None = None, security: str | None = None) -> tuple[int, str]:
    if registro is not None:
        m.REGISTRY = m._tmp / "findings.yml"
        m.REGISTRY.write_text(yaml.safe_dump(registro, allow_unicode=True, sort_keys=False),
                              encoding="utf-8")
    if security is not None:
        m.SECURITY_MD = m._tmp / "SECURITY.md"
        m.SECURITY_MD.write_text(security, encoding="utf-8")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = m.main()
    return rc, re.sub(r"\x1b\[[0-9;]*m", "", buf.getvalue())


def _reg() -> dict:
    return copy.deepcopy(_REGISTRO)


def _voce(reg: dict, stato: str) -> dict:
    return next(v for v in reg["findings"] if v.get("status") == stato)


def test_il_registro_vero_passa(cf):
    rc, out = _esegui(cf)
    assert rc == 0, out
    assert "ogni voce chiusa ha la sua evidenza" in out


# ── il modo «epoca» ──────────────────────────────────────────────────────────

def test_epoca_senza_data_dice_come_si_usa(cf, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["check_findings.py", "--epoca"])
    rc, out = _esegui(cf)
    assert rc == 2 and "uso: check_findings.py --epoca AAAA-MM-GG" in out


def test_epoca_con_la_data_passa_al_rapporto(cf, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["check_findings.py", "--epoca", "2026-11-01"])
    visto = {}
    monkeypatch.setattr(cf, "rapporto_epoca", lambda voci, data: visto.update(n=len(voci), data=data) or 7)
    rc, _ = _esegui(cf)
    assert rc == 7 and visto == {"n": len(_REGISTRO["findings"]), "data": "2026-11-01"}


# ── il registro e il CHANGELOG ───────────────────────────────────────────────

def test_registro_assente(cf):
    cf.REGISTRY = cf._tmp / "non-c-e.yml"
    rc, out = _esegui(cf)
    assert rc == 1 and "registro assente" in out


def test_changelog_senza_versioni_e_un_difetto_solo(cf, monkeypatch):
    monkeypatch.setattr(cf, "versioni_rilasciate", lambda: set())
    rc, out = _esegui(cf)
    assert rc == 1 and out.count("CHANGELOG.md assente o senza intestazioni di versione") == 1


# ── le regole di ogni voce ───────────────────────────────────────────────────

def test_severita_non_valida_e_titolo_mancante(cf):
    reg = _reg()
    v = _voce(reg, "closed")
    v["severity"] = "gravissima"
    v["title"] = ""
    rc, out = _esegui(cf, reg)
    assert rc == 1
    assert f"{v['id']}: severity «gravissima» non valida" in out
    assert f"{v['id']}: manca il titolo" in out


def test_un_accettato_senza_perche(cf):
    reg = _reg()
    v = _voce(reg, "accepted")
    v.pop("missing", None)
    v.pop("rationale", None)
    rc, out = _esegui(cf, reg)
    assert rc == 1 and f"{v['id']}: è `accepted` ma non dice PERCHÉ non si fa" in out


def test_le_voci_non_ancora_rilasciate_si_stampano_sempre(cf, monkeypatch):
    primo = _REGISTRO["findings"][0]["id"]
    monkeypatch.setattr(cf, "check_since", lambda f, ril, err: f.get("id") == primo)
    rc, out = _esegui(cf)
    assert rc == 0 and f"⧗ 1 su main, non ancora rilasciati: {primo}" in out


# ── i confronti con SECURITY.md ──────────────────────────────────────────────

def test_un_residuo_non_nominato_in_security_md(cf):
    v = _voce(_reg(), "partial")
    testo = re.sub(rf"\b{re.escape(v['id'])}\b", "HXXX", _SECURITY)
    rc, out = _esegui(cf, security=testo)
    assert rc == 1 and f"{v['id']}: è `partial` ma SECURITY.md non lo NOMINA mai" in out


def test_la_tabella_dei_conteggi_che_cambia_forma(cf):
    testo = re.sub(r"\*\*accettati\*\*", "**accolti**", _SECURITY)
    rc, out = _esegui(cf, security=testo)
    assert rc == 1 and "non trovo il conteggio «accettati» nella tabella dei residui" in out


def test_la_frase_dei_conteggi_che_cambia_forma(cf):
    testo = _SECURITY.replace("Il registro conta **", "Nel registro ci sono **")
    rc, out = _esegui(cf, security=testo)
    assert rc == 1 and "non trovo la frase «Il registro conta **N voci**" in out


def test_la_prosa_che_non_torna_con_se_stessa(cf):
    m = re.search(r"Il registro conta \*\*(\d+) voci\*\*\s*\(\s*(\d+)\s+critiche?", _SECURITY)
    assert m, "SECURITY.md ha cambiato la frase: aggiorna anche questa prova"
    testo = _SECURITY.replace(m.group(0), m.group(0)[: -len(m.group(2) + " critiche")]
                              + f"{int(m.group(2)) + 1} critiche", 1)
    rc, out = _esegui(cf, security=testo)
    assert rc == 1
    assert "SECURITY.md (prosa) dichiara" in out and "«critical»" in out
    assert "le severità dichiarate sommano a" in out


def test_una_severita_sconosciuta_non_entra_nel_conto_della_prosa(cf):
    reg = _reg()
    _voce(reg, "closed")["severity"] = "boh"
    rc, out = _esegui(cf, reg)
    assert rc == 1 and "SECURITY.md (prosa) dichiara" in out


# ── ciò che si stampa senza accusare ─────────────────────────────────────────

def test_senza_voci_da_segnalare_le_righe_gialle_non_compaiono(cf, monkeypatch):
    monkeypatch.setattr(cf, "check_natura_e_prova", lambda f, err, senza: None)
    monkeypatch.setattr(cf, "check_scoperta", lambda f, err, senza: None)
    # SORVEGLIATE la riempie check_rilievo_esterno mentre il controllo gira
    monkeypatch.setattr(cf, "check_rilievo_esterno", lambda f, err: None)
    monkeypatch.setattr(cf, "SORVEGLIATE", [])
    rc, out = _esegui(cf)
    assert rc == 0
    assert "senza `natura`" not in out and "senza `scoperta`" not in out
    assert "da analisi esterna SENZA i tre verdetti" not in out
    # la riga ⧗ non è un'accusa: c'è se e solo se il registro vero ha una voce che aspetta il rilascio
    in_attesa = any(f.get("since") == "unreleased" for f in _REGISTRO["findings"])
    assert ("⧗" in out) == in_attesa


def test_le_voci_sorvegliate_si_nominano(cf, monkeypatch):
    monkeypatch.setattr(cf, "check_rilievo_esterno", lambda f, err: None)
    monkeypatch.setattr(cf, "SORVEGLIATE", ["H01 (da un audit)", "H02 (da un audit)"])
    monkeypatch.setattr(cf, "check_natura_e_prova",
                        lambda f, err, senza: senza.append(f.get("id")))
    monkeypatch.setattr(cf, "check_scoperta", lambda f, err, senza: senza.append(f.get("id")))
    rc, out = _esegui(cf)
    n = len(_REGISTRO["findings"])
    assert rc == 0
    assert f"◍ {n} voci senza `natura` dichiarata" in out
    assert f"◍ {n} voci senza `scoperta`" in out
    assert "◍ 2 voci da analisi esterna SENZA i tre verdetti" in out
    assert "  · H01 (da un audit)" in out and "  · H02 (da un audit)" in out


def test_nel_ramo_rosso_la_regola_non_si_legge_come_un_resoconto(cf):
    reg = _reg()
    _voce(reg, "closed")["title"] = ""
    rc, out = _esegui(cf, reg)
    assert rc == 1
    assert out.rstrip().endswith("Sopra c'è dove non regge.")
    assert "ogni voce chiusa ha la sua evidenza" not in out


def test_un_parziale_che_non_dice_cosa_manca(cf):
    reg = _reg()
    v = _voce(reg, "partial")
    v.pop("missing", None)
    rc, out = _esegui(cf, reg)
    assert rc == 1 and f"{v['id']}: è `partial` ma non dichiara cosa manca" in out


def test_una_voce_senza_id_si_dice_invece_di_crollare(cf):
    """Prima: KeyError 'id' in check_evidence, cioè un traceback (Sagoma, 24/11/2026)."""
    reg = _reg()
    v = _voce(reg, "closed")
    titolo = v["title"]
    v.pop("id")
    rc, out = _esegui(cf, reg)
    assert rc == 1
    assert f"una voce senza `id` (titolo: «{titolo}»)" in out


# ── la scomposizione per origine scritta in prosa (28/11/2026, rilievo di Arianna) ─────────────

def test_il_numero_della_campagna_originaria_sbagliato_fa_rosso(cf):
    """La prova rifatta da Arianna il 27/11 su una copia: «43 dalla campagna» → «44», e il
    guardiano usciva 0 mentre SECURITY.md promette che fallisce."""
    assert re.search(r"\b43 dalla\s+campagna originaria", _SECURITY)
    rc, out = _esegui(cf, security=re.sub(r"\b43 dalla(\s+campagna originaria)", r"44 dalla\1",
                                          _SECURITY, count=1))
    assert rc != 0
    assert "dichiara 44 rilievi «dalla campagna originaria», il registro ne conta 43" in out


def test_un_gruppo_col_numero_sbagliato_fa_rosso(cf):
    assert "7 (`H44`-`H50`)" in _SECURITY
    rc, out = _esegui(cf, security=_SECURITY.replace("7 (`H44`-`H50`)", "8 (`H44`-`H50`)", 1))
    assert rc != 0 and "dichiara 8 rilievi in H44…H50, il registro ne conta 7" in out


def test_un_rilievo_nuovo_che_la_prosa_non_nomina_fa_rosso(cf):
    ultimo = _REGISTRO["findings"][-1]["id"]
    senza = re.sub(r"`" + ultimo + r"`", "`una voce`", _SECURITY)
    rc, out = _esegui(cf, security=senza)
    assert rc != 0 and f"la scomposizione per origine non nomina {ultimo}" in out


def test_un_rilievo_nominato_che_non_esiste_fa_rosso(cf):
    rc, out = _esegui(cf, security=_SECURITY.replace("7 (`H44`-`H50`)", "7 (`H44`-`H50`) e `H999`", 1))
    assert rc != 0 and "nomina H999, che nel registro non ci sono" in out


def test_senza_la_frase_della_campagna_il_controllo_lo_dice(cf):
    rc, out = _esegui(cf, security=re.sub(r"dalla(\s+)campagna originaria", r"dal\1primo giro",
                                          _SECURITY, count=1))
    assert rc != 0 and "non trovo la scomposizione per origine" in out


def test_la_prosa_di_oggi_torna_col_registro(cf):
    rc, out = _esegui(cf)
    assert rc == 0 and "scomposizione per origine" not in out


def test_un_gruppo_scritto_come_elenco_col_numero_sbagliato_fa_rosso(cf):
    """Il 43 → 44 in piccolo (nota di Sagoma): i gruppi scritti come elenco e in lettere."""
    assert "Due (`H69`, `H70`)" in _SECURITY
    rc, out = _esegui(cf, security=_SECURITY.replace("Due (`H69`, `H70`)", "Tre (`H69`, `H70`)", 1))
    assert rc != 0 and "dichiara 3 rilievi in H69…H70, il registro ne conta 2" in out
    m = re.search(r"\b4 che\s+non\s+vengono", _SECURITY)
    assert m, "il gruppo H51-H54 non è più scritto così: aggiorna la prova"
    rc, out = _esegui(cf, security=_SECURITY[:m.start()] + "5" + _SECURITY[m.start() + 1:])
    assert rc != 0 and "dichiara 5 rilievi in H51…H54, il registro ne conta 4" in out


def test_un_numero_di_versione_prima_della_parentesi_non_e_un_conto(cf):
    """`v0.40.3, 4 che … (H51 …)`: il «3» della versione non è il numero del gruppo."""
    gruppi = cf._gruppi_contati("culminato nella `v0.40.3`, 4 che vengono da altro (`H51`, `H52` e "
                                "`H54`, `H53`), e sette (`H94`-`H100`, 21/11).")
    assert [(n, sorted(ids)) for n, _, ids in gruppi] == [(4, [51, 52, 53, 54]),
                                                         (7, list(range(94, 101)))]
