"""CIÒ CHE ESCE DAL PROCESSO NON PORTA FUORI UN SEGRETO — e il buco è provato come tale.

🔴 PERCHÉ ESISTE. Round-15 (03/08): il prodotto proteggeva DUE canali e ne lasciava
   scoperti tre, perché **la redazione era agganciata al TRASPORTO invece che al DATO**.
   La catena misurata a mano su `v0.40.14` (cioè su ciò che GIRA, non su `main`):

     tools/vps1777.py   MigrationError(f"…fallita (exit {rc}):\\n{stdout}\\n{stderr}")
                        ↓ diventa `reason`
                        telegram_notify(repo, f"❌ …fallito ({reason})…")
                        ↓
                        urlencode({"text": text}) → api.telegram.org   ← NIENTE

   Gli stessi byte, nei log, sarebbero stati `***` (logredact.py); nell'audit
   sarebbero caduti fuori dall'allowlist (audit.py). Su Telegram e sul terminale
   uscivano interi.

⭐ QUESTO TEST NON PROVA CHE «FUNZIONA»: prova le tre cose che possono ROMPERSI in
   silenzio, e ognuna è un difetto già pagato altrove nel repo.
     ① il segreto esce                      → il presidio non c'è o non è agganciato
     ② un segreto CORTO redige tutto        → output illeggibile ⇒ qualcuno lo spegne
     ③ prefisso: il corto spezza il lungo   → resta la CODA in chiaro, e sembra redatto

🖐️ E prova il BUCO DICHIARATO invece di nasconderlo: prima di `arma_redazione` la
   redazione è un no-op. Un limite che il test non copre è un limite che qualcuno
   scoprirà credendolo un bug.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location("vps1777_cli", REPO / "tools" / "vps1777.py")
v = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v)


def _repo_finto(tmp_path: Path, secrets: dict[str, str], env: dict[str, str]) -> Path:
    (tmp_path / "secrets").mkdir()
    for nome, val in secrets.items():
        (tmp_path / "secrets" / nome).write_text(val + "\n")
    (tmp_path / ".env").write_text("".join(f"{k}={x}\n" for k, x in env.items()))
    return tmp_path


def test_il_segreto_non_esce(tmp_path):
    """① Il caso per cui il presidio esiste."""
    r = _repo_finto(tmp_path, {"telegram_bot_token.txt": "1234567890:AAH-segretissimo_xyz"},
                    {"GATEWAY_SECRET": "s3cr3t-lunghissimo-abcdef"})
    assert v.arma_redazione(r) == 2
    # il testo che il round-15 ha misurato uscire davvero
    reason = "migrazione 003 fallita (exit 1):\nDSN=1234567890:AAH-segretissimo_xyz\n"
    out = v._redigi(f"❌ vps1777: update fallito ({reason})")
    assert "AAH-segretissimo_xyz" not in out
    assert "***" in out


def test_il_valore_corto_non_redige_tutto(tmp_path):
    """② Un segreto corto sostituirebbe pezzi di parole ovunque.

    Un output pieno di `***` a caso è illeggibile, e un presidio illeggibile viene
    disattivato dal primo che deve leggere un errore alle tre di notte.
    """
    r = _repo_finto(tmp_path, {"corto.txt": "abc"}, {"API_KEY": "xy"})
    assert v.arma_redazione(r) == 0, "valori sotto la soglia non devono entrare"
    assert v._redigi("abc: operazione xy completata") == "abc: operazione xy completata"


def test_prefisso_il_lungo_va_sostituito_prima(tmp_path):
    """③ Il difetto che LASCIA LA CODA IN CHIARO e sembra redatto.

    Se `token` è prefisso di `tokenLUNGO` e si sostituisce prima il corto, il
    risultato è `***LUNGO`: c'è un `***` — sembra che il presidio abbia lavorato —
    e metà del segreto lungo è ancora lì. È la stessa cura che ha `logredact.py`.
    """
    r = _repo_finto(tmp_path, {"a.txt": "TOKENbase123", "b.txt": "TOKENbase123CODA456"}, {})
    assert v.arma_redazione(r) == 2
    out = v._redigi("errore: TOKENbase123CODA456 rifiutato")
    assert "CODA456" not in out, "la coda del segreto lungo è rimasta in chiaro"
    assert out == "errore: *** rifiutato"


def test_il_buco_dichiarato_esiste_ed_e_quello(tmp_path):
    """Prima di `arma_redazione`, `_redigi` è un no-op — DICHIARATO, non scoperto.

    Non è un test che «passa»: è la coordinata del limite. Se un giorno qualcuno
    chiude il buco (armando la redazione prima di `find_repo`), questo test
    fallisce e lo obbliga a leggere qui perché esisteva.
    """
    v._SEGRETI = []
    assert v._redigi("token=1234567890:AAH-segretissimo") == "token=1234567890:AAH-segretissimo"


def test_le_quattro_uscite_sono_agganciate():
    """Le funzioni che stampano DEVONO passare da `_redigi`.

    Non provo l'output (servirebbe capturare stdout per ognuna): provo
    l'AGGANCIO sul sorgente. Una `print` aggiunta domani senza `_redigi` è
    esattamente il modo in cui questo difetto è nato la prima volta.
    """
    src = (REPO / "tools" / "vps1777.py").read_text()
    for fn in ("def log(", "def ok(", "def warn(", "def die("):
        i = src.index(fn)
        corpo = src[i:src.index("\n\n", i)]
        assert "_redigi(" in corpo, f"{fn.strip('def (')} stampa senza redigere"
    # e il canale che il round-15 ha trovato scoperto
    i = src.index("def telegram_notify(")
    assert '"text": _redigi(text)' in src[i:i + 1400], "telegram_notify non redige"
