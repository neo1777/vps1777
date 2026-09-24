"""La redazione in uscita: cosa maschera, cosa NON maschera, e che copra TUTTI i tool.

⚠️ STDLIB-ONLY, e non è un dettaglio di stile: questi test girano in un job che non
installa `mcp`. Importare `app.server` per contare i tool farebbe fallire la COLLECTION e
porterebbe giù l'intera suite — è successo il 02/08 con `yaml`, 124 test non eseguiti.
Perciò la copertura dei tool si verifica con l'**AST**: legge il sorgente, non lo esegue.
"""
from __future__ import annotations

import ast
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import redazione  # noqa: E402


# ── cosa maschera ────────────────────────────────────────────────────────────────────
def test_email_e_telefono_sono_redatti_ovunque() -> None:
    """I pattern valgono su QUALUNQUE testo, non solo sull'anagrafica.

    È il pezzo che copre i transcript: un'email scritta a mano dentro un messaggio non è
    in anagrafica, e senza i pattern uscirebbe in chiaro.
    """
    s = "scrivimi a mario.rossi@example.com o chiama +39 333 1234567 grazie"
    out = redazione.maschera_testo(s)
    assert "mario.rossi@example.com" not in out
    assert "333 1234567" not in out
    assert redazione.SEGNAPOSTO_EMAIL in out and redazione.SEGNAPOSTO_TEL in out
    assert "scrivimi a" in out and "grazie" in out          # il resto del testo resta


def test_valori_noti_mascherati_anche_senza_formato() -> None:
    """Un NOME non ha un formato: si maschera perché è NOTO, non perché somiglia a un nome."""
    out = redazione.maschera_testo("ne ho parlato con Mario Rossi ieri", {"Mario Rossi"})
    assert "Mario Rossi" not in out
    assert redazione.SEGNAPOSTO_VALORE in out


def test_ricorsiva_su_strutture_annidate() -> None:
    """Ricorsiva e non «sui campi che so»: un campo nuovo nascerebbe scoperto."""
    dato = {"rows": [{"content": "a@b.co", "meta": {"note": ["chiama +39 3331234567"]}}],
            "n": 3, "ok": True}
    out = redazione.maschera(dato)
    assert out["rows"][0]["content"] == redazione.SEGNAPOSTO_EMAIL
    assert redazione.SEGNAPOSTO_TEL in out["rows"][0]["meta"]["note"][0]
    assert out["n"] == 3 and out["ok"] is True              # i non-stringa passano intatti


def test_valori_noti_letti_dallindice() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE messages (project TEXT, content TEXT)")
    conn.execute("INSERT INTO messages VALUES ('account:user', ?)",
                 ("full_name: Mario Rossi\nemail_address: m@r.it\nuuid: abc-123\n",))
    conn.execute("INSERT INTO messages VALUES ('altro', 'full_name: Non Contare')")
    noti = redazione.valori_noti(conn)
    assert "Mario Rossi" in noti
    assert "m@r.it" in noti
    assert "abc-123" not in noti, "uuid è tecnico: mascherarlo romperebbe get_context"
    assert "Non Contare" not in noti, "solo project='account:user' è l'anagrafica"


def test_anagrafica_illeggibile_non_spegne_la_redazione() -> None:
    """Insieme vuoto, non eccezione: i pattern devono restare attivi comunque.

    Un presidio che si spegne quando una query fallisce è un presidio assente proprio
    nell'istante in cui qualcosa non va.
    """
    conn = sqlite3.connect(":memory:")                      # niente tabella `messages`
    assert redazione.valori_noti(conn) == set()
    assert redazione.maschera_testo("x@y.zz") == redazione.SEGNAPOSTO_EMAIL


# ── cosa NON maschera: il limite, provato invece che dichiarato ──────────────────────
def test_il_limite_dichiarato_e_vero() -> None:
    """Un nome NON in anagrafica e senza formato riconoscibile PASSA — e va provato.

    Rilievo di abdd732a prima della stesura: un filtro sui dati sensibili si giudica sui
    FALSI NEGATIVI. Questo test esiste perché il limite sia **misurato** e non solo
    scritto in un docstring — la promessa deve essere della dimensione della misura.
    """
    out = redazione.maschera_testo("ne ho parlato con Giulia Bianchi", set())
    assert "Giulia Bianchi" in out


def test_un_anno_non_e_un_telefono() -> None:
    """Il pattern telefono non deve mangiarsi numeri qualunque: un falso positivo qui
    corromperebbe i risultati di ricerca, che è la ragione per cui la soglia è a 9 cifre."""
    for innocuo in ("nel 2026", "riga 1234", "v0.32.0", "12345678"):
        assert redazione.maschera_testo(innocuo) == innocuo, innocuo


# ── che copra TUTTI i tool, non i tre che ho avvolto ────────────────────────────────
_SERVER = Path(__file__).resolve().parents[1] / "app" / "server.py"


def test_redazione_copre_tutti_i_tool() -> None:
    """Ogni `@mcp.tool()` deve stare DOPO la sostituzione di `mcp.tool`.

    La domanda non è «i tool che ho avvolto sono avvolti» (tautologia) ma «esiste un tool
    che NON lo è?». La sostituzione del decoratore rende impossibile dimenticarsene, con
    un solo punto fragile: l'ORDINE nel file. È quello che questo test misura.
    """
    albero = ast.parse(_SERVER.read_text(encoding="utf-8"))
    riga_patch = None
    for nodo in ast.walk(albero):
        if isinstance(nodo, ast.Assign):
            for t in nodo.targets:
                if (isinstance(t, ast.Attribute) and t.attr == "tool"
                        and isinstance(t.value, ast.Name) and t.value.id == "mcp"):
                    riga_patch = nodo.lineno
    assert riga_patch is not None, "la sostituzione di mcp.tool non c'è più: i tool sono in chiaro"

    tool = [n.lineno for n in ast.walk(albero) if isinstance(n, ast.FunctionDef)
            for d in n.decorator_list
            if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
            and d.func.attr == "tool"]
    assert tool, "nessun @mcp.tool trovato: il test non sta misurando quello che crede"
    prima = [ln for ln in tool if ln < riga_patch]
    assert not prima, (f"{len(prima)} tool sono registrati PRIMA della redazione "
                       f"(righe {prima}): escono in chiaro")


def test_la_redazione_e_attiva_per_default() -> None:
    """Fail-closed: si spegne solo con una scelta esplicita, mai per una variabile assente."""
    sorgente = (Path(redazione.__file__)).read_text(encoding="utf-8")
    assert 'os.getenv("ARCHIVE_REDACT", "1")' in sorgente, \
        "il default deve essere ATTIVA: un presidio che nasce spento non è un presidio"


def test_un_timestamp_compatto_non_e_un_telefono() -> None:
    """`20260811-190343` è il nome di un bundle/DB (YYYYMMDD-HHMMSS), non un numero.

    Misurato il 28/08/2026: le description degli archivi uscivano dai tool con
    «[telefono redatto]» al posto del nome — chi legge non può più riferirsi al
    DB per nome, e la redazione perde credibilità proprio dove non protegge nulla.
    """
    out = redazione.maschera_testo("il DB recupero-sessioni-1777_20260811-190343 è il più fresco")
    assert "20260811-190343" in out


def test_l_esenzione_timestamp_e_stretta_nei_due_versi() -> None:
    """L'esenzione copre SOLO la sagoma data-ora con secolo plausibile.

    Verso 1: quattordici cifre col trattino ma secolo implausibile → resta telefono.
    Verso 2 (il caso noto che deve riuscire): il telefono vero continua a sparire —
    senza questo, l'esenzione potrebbe essersi mangiata la redazione intera.
    """
    assert "12345678-654321" not in redazione.maschera_testo("chiama 12345678-654321 ora")
    assert "333 1234567" not in redazione.maschera_testo("chiama +39 333 1234567 grazie")


# ── 24/09/2026: date con l'ora e uuid (misurato dal vivo via MCP) ─────────────────────
def test_una_data_con_l_ora_non_e_un_telefono() -> None:
    """«2026-09-05 13:10» usciva «[telefono redatto]:10» (TELEFONO si ferma ai due punti e il
    match «2026-09-05 13» ha 10 cifre). Una data valida con l'ora resta com'è."""
    for innocuo in ("quota tornata il 2026-09-05 13:10 UTC", "alle 2026-12-31 23:59",
                    "il 1999-01-01 00:00", "2026-09-24T20:32 e basta"):
        assert redazione.maschera_testo(innocuo) == innocuo, innocuo


def test_un_uuid_non_e_un_telefono() -> None:
    """Un uuid coi gruppi di sole cifre usciva spezzato («[telefono redatto]-4123-…»): la
    navigazione (`get_context`, `get_session`) si rompe proprio dove non si protegge nulla."""
    for u in ("12345678-1234-4123-8123-123456789012", "b3326245-7246-4cbb-ad80-267e5650544b",
              "ABCDEF12-3456-7890-ABCD-EF1234567890"):
        s = f"la riga {u} del thread"
        assert redazione.maschera_testo(s) == s, u


def test_le_esenzioni_nuove_sono_strette() -> None:
    """Il caso noto che deve riuscire: i telefoni veri spariscono ancora — accanto a un uuid,
    dopo una data, e con una «data» impossibile (mese 13, giorno 32) che resta telefono."""
    u = "123e4567-e89b-12d3-a456-426614174000"
    out = redazione.maschera_testo(f"chiama 333 1234567 per l'uuid {u}")
    assert "333 1234567" not in out and u in out
    out = redazione.maschera_testo("il 2026-09-05 chiama +39 333 1234567")
    assert "333 1234567" not in out and "2026-09-05" in out
    for falso in ("2026-13-05 13", "2026-09-32 13", "2026-09-05 24", "3026-09-05 13"):
        assert redazione.SEGNAPOSTO_TEL in redazione.maschera_testo(f"x {falso} y"), falso
    # un uuid con un gruppo di troppo non è un uuid: resta soggetto al pattern
    assert redazione.SEGNAPOSTO_TEL in redazione.maschera_testo("12345678-1234-4123-8123")
