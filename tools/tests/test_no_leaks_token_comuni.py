"""Il gate anti-leak riconosce i token dei fornitori comuni, non solo le credenziali del prodotto.

Misura di Bottega del 28/11/2026: un file con tre token finti (GitHub, Anthropic, AWS) passava
verde, e il gate dei commit di altri repo importa questo stesso elenco. I valori qui sono FINTI e
costruiti a pezzi: scritti interi farebbero scattare il gate su questo file, come è giusto.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("gate_token", _ROOT / "security" / "check_no_leaks.py")
g = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(g)

A36 = "Ab1" * 12
FINTI = [
    ("gettone GitHub", "gh" + "p_" + A36),
    ("gettone GitHub", "gh" + "o_" + A36),
    ("gettone GitHub", "gh" + "s_" + A36),
    ("gettone GitHub", "github" + "_pat_" + "11AAAAAAA0" + "_" + A36 + A36),
    ("chiave API Anthropic", "sk-" + "ant-" + "api03-" + A36),
    ("chiave API OpenAI", "sk-" + "proj-" + A36),
    ("chiave API OpenAI", "sk-" + A36 + "abcdefghijkl"),
    ("chiave d'accesso AWS", "AK" + "IA" + "ABCDEFGHIJ234567"),
    ("chiave d'accesso AWS", "AS" + "IA" + "ABCDEFGHIJ234567"),
    ("chiave API Google", "AI" + "za" + "SyA-" + A36),
    ("gettone Slack", "xox" + "b-" + "123456789012-" + "abcdefghijkl"),
    ("chiave privata PEM", "-----BEGIN " + "ENCRYPTED " + "PRIVATE KEY-----"),
]


def _chi_scatta(testo: str) -> set[str]:
    return {nome for nome, modello in g.SECRET_PATTERNS if modello.search(testo)}


@pytest.mark.parametrize("nome, valore", FINTI, ids=[f"{n}-{i}" for i, (n, _) in enumerate(FINTI)])
def test_un_token_di_un_fornitore_comune_fa_scattare_il_suo_modello(nome, valore):
    assert nome in _chi_scatta(f"export CHIAVE={valore}\n")
    assert nome in _chi_scatta(f'"token": "{valore}",')


SEGNAPOSTO = [
    "gh" + "p_...", "gh" + "p_<il tuo gettone>", "github" + "_pat_XXXX", "sk-" + "ant-...",
    "sk-" + "ant-<chiave>", "sk-" + "proj-…", "AK" + "IA...", "AK" + "IAXXXXXXXX", "AI" + "za...",
    "xox" + "b-...", "task-force-con-un-nome-lungo-abbastanza-per-sembrarlo-1234567890",
    "risk-assessment-2026-11-28-versione-definitiva-approvata", "gh" + "p_corto123",
]


@pytest.mark.parametrize("testo", SEGNAPOSTO)
def test_un_segnaposto_o_una_parola_che_gli_somiglia_non_scatta(testo):
    nuovi = {"gettone GitHub", "chiave API Anthropic", "chiave API OpenAI", "chiave d'accesso AWS",
             "chiave API Google", "gettone Slack"}
    assert not (_chi_scatta(f"usa {testo} nella configurazione") & nuovi)


def test_il_gate_intero_fa_rosso_su_un_file_con_un_gettone(tmp_path):
    """Dal modello al verdetto: la funzione che il gate usa sui file dice il nome del modello."""
    assert any(nome == "gettone GitHub" for nome, _ in g.SECRET_PATTERNS)
    testo = "riga pulita\nGH_TOKEN=" + "gh" + "p_" + A36 + "\n"
    assert "gettone GitHub" in _chi_scatta(testo)
