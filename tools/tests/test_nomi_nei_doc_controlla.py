"""`controlla` di tools/nomi-nei-doc.py: che cosa prende e che cosa lascia, tipo per tipo.

Il contesto (comandi della CLI, testo del codice, funzioni, comandi del bot) qui è finto e
piccolo: la prova dice la regola, non lo stato del repo (quello lo dice lo strumento in check.sh).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("nomi_nei_doc", _ROOT / "tools" / "nomi-nei-doc.py")
nd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nd)

C = {"comandi": {"update": {"--version", "--yes"}, "status": set()},
     "codice": "VPS1777_HOME archive_db_dir \"/aiuto\"",
     "funzioni": {"search", "get_many"},
     "bot": {"start"}}


def _errori(testo: str, rel: str = "docs/X.md") -> list[str]:
    return nd.controlla(rel, testo, C)


def test_un_documento_giusto_non_ha_errori():
    assert _errori("Usa `vps1777 update --version v1 --yes`, poi `vps1777 status`.\n"
                   "La variabile `VPS1777_HOME` e `ARCHIVE_DB_DIR`; il tool `search(q)`.\n"
                   "Il bot su Telegram ha `/start` e `/aiuto`.") == []


def test_un_comando_o_un_flag_che_la_cli_non_ha():
    e = _errori("`vps1777 inventato --x`\n`vps1777 update --forza --yes`")
    assert e == ["docs/X.md:1  `vps1777 inventato`: la CLI non ha questo comando",
                 "docs/X.md:2  `vps1777 update --forza`: il comando non ha questo flag"]


def test_dopo_un_comando_che_non_esiste_si_guarda_anche_il_secondo():
    e = _errori("`vps1777 inventato; vps1777 fantasma`")
    assert [x.split("`")[1] for x in e] == ["vps1777 inventato", "vps1777 fantasma"]


def test_fuori_dagli_apici_la_prosa_non_si_guarda_ma_un_blocco_di_codice_si():
    assert _errori("scrivi vps1777 inventato a mano") == []
    e = _errori("```bash\nvps1777 inventato\nVAR_INVENTATA=1\n```\ndopo: `VAR_INVENTATA`")
    assert e == ["docs/X.md:2  `vps1777 inventato`: la CLI non ha questo comando",
                 "docs/X.md:5  `VAR_INVENTATA`: nessun file di codice o di config la nomina"]


def test_una_variabile_un_tool_e_un_comando_del_bot_che_non_esistono():
    e = _errori("`VAR_INVENTATA`\n`search_inventata(q)` e `altro(x)`\nil bot ha `/inventato`")
    assert e == ["docs/X.md:1  `VAR_INVENTATA`: nessun file di codice o di config la nomina",
                 "docs/X.md:2  `search_inventata(q)`: non è un tool né una funzione del repo",
                 "docs/X.md:3  `/inventato`: il bot non ha questo comando (ha: /start)"]


def test_un_percorso_con_la_barra_non_e_un_comando_del_bot_senza_il_bot_nella_riga():
    assert _errori("apri `/inventato` nel browser") == []
    assert _errori("da BotFather il bot riceve `/inventato`") == []


def test_una_riga_che_racconta_il_passato_non_si_controlla():
    assert _errori("`vps1777 inventato` è stato tolto nella 0.5\n`VAR_INVENTATA` era la vecchia") == []


def test_env_example_si_legge_riga_per_riga_dalle_assegnazioni():
    e = _errori("VPS1777_HOME=/x\n# VAR_COMMENTATA=1\nARCHIVE_DB_DIR=/y\n  rientrata: VAR_ALTRA=2",
                rel=".env.example")
    assert e == [".env.example:2  `VAR_COMMENTATA`: nessun file di codice o di config la nomina"]
    assert _errori("# esempio: vps1777 inventato", rel=".env.example") == [
        ".env.example:1  `vps1777 inventato`: la CLI non ha questo comando"]
