"""Test del PERIMETRO di `security/check_findings.py` — quali file hanno commenti.

Perché esiste: `solo_in_commenti()` impedisce a un `contains:` di essere soddisfatto
da una riga commentata — cioè al gate di restare verde mentre il codice che dovrebbe
presidiare non c'è più. Ma decideva **per suffisso**, e `Path(".env.example").suffix`
è `".example"`: quel file restava fuori benché `#` sia il suo carattere di commento.
🔴 CASO VIVO: H49 portava `VPS1777_REQUIRE_COSIGN` come `contains:` su `.env.example`,
dove compare su una riga sola ed è commentata.

📌 PERCHÉ ESTRAE LE FUNZIONI COL AST INVECE DI IMPORTARE IL MODULO, e non è eleganza:
`check_findings.py` importa `yaml`, e il job che lancia questa suite si chiama
**«Test CLI vps1777 (stdlib-only)»** — pyyaml lassù non c'è. La prima stesura di
questo file importava il modulo: in locale passava, **in CI l'import falliva in
fase di COLLECTION e portava giù tutti e 124 i test della suite**. Il gate intero è
già presidiato altrove (`ci.yml:89`, `uv run --with pyyaml`); qui si prova la
logica del perimetro, che è pura e non ha bisogno di yaml per esistere.
"""
from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_GATE = _ROOT / "security" / "check_findings.py"


def _dal_sorgente():
    """Estrae `_ha_commenti_hash` + `solo_in_commenti` e le rende eseguibili qui."""
    albero = ast.parse(_GATE.read_text(encoding="utf-8"))
    ns: dict = {"Path": Path}
    voluti = {"_SUFFISSI_CON_COMMENTI", "_NOMI_CON_COMMENTI"}
    corpo = []
    for n in albero.body:
        if isinstance(n, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id in voluti for t in n.targets):
            corpo.append(n)
        elif isinstance(n, ast.FunctionDef) and n.name in ("_ha_commenti_hash",
                                                           "solo_in_commenti"):
            n.returns = None
            for a in n.args.args:
                a.annotation = None
            corpo.append(n)
    exec(compile(ast.Module(body=corpo, type_ignores=[]), "<estratto>", "exec"), ns)
    return ns


def test_i_file_che_usano_hash_come_commento_sono_nel_perimetro():
    ha = _dal_sorgente()["_ha_commenti_hash"]
    for nome in (".env.example", ".env", "Dockerfile", "Caddyfile", "Makefile",
                 "compose.yaml", "deploy.sh", "vps1777.py", "unit.service",
                 "config.toml", "app.ini", "nginx.conf"):
        assert ha(Path(nome)), (
            f"{nome} usa `#` come commento ma resta fuori dal perimetro: un "
            f"`contains:` su questo file può essere soddisfatto da una riga commentata"
        )


def test_i_file_SENZA_commenti_restano_fuori():
    # Il verso opposto, e non è un dettaglio: nei `.md` un `contains` è SEMPRE una
    # citazione — trattarli come codice darebbe falsi rossi su tutta la doc, e un
    # gate che grida al lupo viene spento.
    ha = _dal_sorgente()["_ha_commenti_hash"]
    for nome in ("SECURITY.md", "README.md", "dati.json", "archivio.db", "logo.png"):
        assert not ha(Path(nome)), nome


def test_il_caso_vivo_H49_ora_sarebbe_visto():
    """Sul file VERO del repo, non su un finto: la guardia deve accorgersene."""
    env = _ROOT / ".env.example"
    if not env.is_file():                      # pragma: no cover
        import pytest
        pytest.skip(".env.example assente")
    solo = _dal_sorgente()["solo_in_commenti"]
    assert solo(env, "VPS1777_REQUIRE_COSIGN"), (
        "l'ago compare solo su una riga commentata e la guardia non lo vede: "
        "è esattamente il buco che questo perimetro chiude"
    )


def test_l_evidenza_di_H49_sta_sotto_ricevute_e_non_sotto_contains():
    """Controprova sul registro, letta come TESTO per non dipendere da yaml.

    Estendere il perimetro rende il gate rosso su H49 se quell'ago resta un
    `contains:`. Non è stato aggirato: è stato spostato sotto `ricevute:`, che è il
    canale prescritto dal messaggio d'errore del gate stesso. Se qualcuno lo
    riportasse indietro, la CI diventerebbe rossa — e questo test lo dice prima.
    """
    testo = (_ROOT / "security" / "findings.yml").read_text(encoding="utf-8")
    i = testo.find("file: .env.example")
    assert i > 0, "l'evidenza su .env.example non c'è più: la voce è stata riscritta"
    blocco = testo[i:i + 700]
    assert "ricevute: [\"VPS1777_REQUIRE_COSIGN\"]" in blocco, (
        "l'ago di .env.example non è più sotto `ricevute:` — se torna sotto "
        "`contains:` il gate diventa rosso, perché lì è una riga commentata"
    )
