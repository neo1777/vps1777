"""`_valore_innocuo` del gate anti-leak, regola per regola: che cosa NON è una password dopo una
parola-spia, e che cosa lo sembra. I valori «sospetti» qui sono finti e costruiti per
concatenazione: nessuno è un segreto vero.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("gate_valore", _ROOT / "security" / "check_no_leaks.py")
g = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(g)

# ognuno ha una lettera e una cifra (o un simbolo forte): passa le prime domande e si ferma alla sua
INNOCUI = [
    ("un percorso assoluto", "/etc/x1"), ("un percorso di casa", "~/x1"), ("un sito", "www.x1.it"),
    ("un flag", "--flag1"), ("un segnaposto", "<valore1>"), ("un redatto", "[redatto1"),
    ("un indirizzo email", "utente1@example.invalid"),
    ("un prompt di shell", "root@vps1:~#"), ("un nome di casa", "neo" + "1777"), ("un orario", "10:30h"),
    ("un percorso relativo", "dir/file1"), ("un file", "note1.md"), ("un file maiuscolo", "FOTO1.PNG"),
    ("uno slug", "my-long-slug-9"), ("un pacchetto", "python3-passlib"), ("un algoritmo", "sha256"),
    ("un identificatore", "admin_password_hash1"),
    ("un'assegnazione", "a1=b2"), ("una chiamata", "f(x1)"), ("una variabile", "$pw1"),
    ("una menzione", "@BotFather"), ("solo cifre", "123456"), ("solo lettere", "abcdefgh"),
    ("troppo corto", "a1b2"),
]


@pytest.mark.parametrize("che_cosa, tok", INNOCUI, ids=[c for c, _ in INNOCUI])
def test_non_e_una_password(che_cosa, tok):
    assert g._valore_innocuo("password", tok) is True, che_cosa


SOSPETTI = [
    ("una cifra fra maiuscole e minuscole", "Tr0ub" + "adour"),
    ("due cifre", "abc" + "12x"),
    ("un simbolo forte", "abc" + "!def"),
    ("un percorso con un simbolo forte", "dir/fi" + "!le1"),
    ("uno slug con una maiuscola in mezzo", "ab-cD-e" + "f-9"),
    ("il separatore incollato si toglie", "=Tr0ub" + "adour"),
]


@pytest.mark.parametrize("che_cosa, tok", SOSPETTI, ids=[c for c, _ in SOSPETTI])
def test_dopo_una_spia_forte_ha_la_forma_di_una_password(che_cosa, tok):
    assert g._valore_innocuo("password", tok) is False, che_cosa


def test_dopo_una_spia_debole_la_forma_deve_essere_piu_netta():
    """«token» e «chiave» sono parole comuni nella prosa: serve un simbolo forte, oppure almeno
    due cifre con maiuscole e minuscole su dodici caratteri."""
    corto = "Tr0ub" + "adour"                    # 10 caratteri, una cifra
    lungo = "Abc1defg" + "hi2j"                  # 12 caratteri, due cifre in mezzo, misto
    assert g._valore_innocuo("token", corto) is True
    assert g._valore_innocuo("token", lungo) is False
    assert g._valore_innocuo("token", "Abc1defg" + "h2j") is True       # undici: uno in meno
    assert g._valore_innocuo("token", "abc1defg" + "hi2j") is True      # dodici ma tutto minuscolo
    assert g._valore_innocuo("token", "Abcdefghij" + "12") is True      # lettere e poi cifre: la forma di un pacchetto
    assert g._valore_innocuo("token", "abcdefgh" + "!x") is False       # il simbolo forte basta
    assert g._valore_innocuo("chiave", "abc" + "!xy1") is True          # sotto la soglia di «chiave» (8)
    assert g._valore_innocuo("Password", corto) is False                # la spia non guarda le maiuscole
