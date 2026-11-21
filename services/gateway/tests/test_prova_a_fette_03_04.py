"""Le cure nate dalle fette 03 (indicizzatore e ingest) e 04 (Mini App) della revisione col
catalogo. Solo libreria standard; i moduli si leggono dal loro file, perché altri test di questa
cartella mettono dei finti `app.*` in `sys.modules`."""
from __future__ import annotations

import importlib.util
import io
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

RADICE = Path(__file__).resolve().parents[1]


def _carica(nome: str):
    spec = importlib.util.spec_from_file_location(f"_fette0304_{nome}", RADICE / "app" / f"{nome}.py")
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


ai = _carica("archive_indexer")
mc = _carica("miniapp_core")


def _scarti(righe) -> list:
    return [r for r in righe if isinstance(r, ai._Skip)]


# ── fetta 03 ────────────────────────────────────────────────────────────────────────────────

def test_un_db_che_non_si_legge_non_sembra_vuoto(tmp_path):
    rotto = tmp_path / "rotto.db"
    rotto.write_bytes(b"questo non e' un database sqlite, ma ha il nome giusto" * 40)
    scheda = ai.db_info(rotto, cache=False)
    assert scheda["rows"] == 0 and scheda["illeggibile"], "un DB illeggibile deve dirlo"
    sano = tmp_path / "sano.db"
    ai.write_rows(sano, iter([("u1", "p", "2026-01-01T00:00:00Z", "ciao", "user", "", "", "", "")]))
    assert ai.db_info(sano, cache=False)["illeggibile"] == ""


def test_le_righe_jsonl_rotte_lasciano_una_lapide_sola():
    testo = '{"type":"user","uuid":"a","message":{"content":"ciao"},"timestamp":"2026-01-01T00:00:00Z"}\n' \
            '{rotta\n{anche questa\n'
    scarti = [s for s in _scarti(ai._iter_claude_code(io.StringIO(testo), "p"))
              if s.reason == "righe-non-json"]
    assert len(scarti) == 1 and scarti[0].detail.startswith("2 righe")
    assert not [s for s in _scarti(ai._iter_claude_code(io.StringIO(testo.split("{rotta")[0]), "p"))
                if s.reason == "righe-non-json"]


def test_un_membro_json_rotto_di_un_export_lascia_la_sua_lapide(tmp_path):
    z = tmp_path / "export.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("conversations.json", "[]")
        f.writestr("users.json", "{rotto")
        f.writestr("projects/p1.json", "{rotto anche")
    nomi = {(s.reason, s.detail) for s in _scarti(ai._iter_claude_zip(z, ai._Budget()))}
    assert ("json-malformato", "users.json") in nomi
    assert ("json-malformato", "projects/p1.json") in nomi


def test_le_impronte_non_crittografiche_lo_dichiarano():
    sorgente = (RADICE / "app" / "archive_indexer.py").read_text(encoding="utf-8")
    codice = "\n".join(r for r in sorgente.splitlines() if not r.lstrip().startswith("#"))
    assert codice.count("hashlib.sha1(") == codice.count("usedforsecurity=False") >= 3
    import hashlib
    # dichiararlo non cambia l'impronta: gli id già indicizzati restano quelli
    assert ai._uid("a", "b") == hashlib.sha1(b"a\x1fb").hexdigest()


def test_l_ora_dei_file_ha_il_fuso(tmp_path):
    f = tmp_path / "x"
    f.write_text("x")
    ts = ai._file_ts(f)
    assert ts.endswith("Z") and abs(
        datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
        - f.stat().st_mtime) < 2


def test_il_tetto_di_un_file_che_non_si_misura_non_si_salta(tmp_path):
    try:
        ai._check_file_size(tmp_path / "non-esiste", 10)
    except OSError:
        return
    raise AssertionError("un file che non si misura deve sollevare, non passare il tetto")


def test_la_risposta_dell_ocr_ha_un_tetto(monkeypatch):
    class Risposta:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n=-1):
            assert n == ai._OCR_MAX_RISPOSTA + 1, "la risposta va letta con un tetto"
            return b"x" * n

    monkeypatch.setattr(ai, "_ocr_url", lambda: "http://ocr.example.invalid/ocr")
    monkeypatch.setattr(ai.urllib.request, "urlopen", lambda *a, **k: Risposta())
    esiti = list(ai._iter_immagine_bytes(b"\x89PNG" + b"0" * 2000, "foto.png", "p", ""))
    assert [s.reason for s in _scarti(esiti)] == ["ocr-risposta-troppo-grande"]


# ── fetta 04 ────────────────────────────────────────────────────────────────────────────────

def test_una_versione_che_non_si_interpreta_non_e_piu_nuova():
    assert mc.version_gt("0.9.0-rc", "0.10.0") is False      # fra stringhe sarebbe stata True
    assert mc.version_gt("0.10.0", "0.9.0-rc") is False
    assert mc.version_gt("0.10.0", "0.9.9") is True


def test_un_initdata_enorme_o_con_troppi_campi_non_si_analizza():
    chiave = "ab" * 32
    assert mc.verify_init_data("a=1&" * 10_000, webapp_secret_hex=chiave) is None
    troppi = "&".join(f"k{i}=v" for i in range(mc.INIT_DATA_MAX_CAMPI + 5))
    assert mc.verify_init_data(troppi, webapp_secret_hex=chiave) is None
    assert mc._chiave_di_firma("", "zz") is None and mc._chiave_di_firma("", "ab" * 10) is None
    assert mc._chiave_di_firma("", chiave) == bytes.fromhex(chiave)


def test_un_posticipo_scritto_senza_fuso_vale_utc():
    ora = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
    assert mc.posticipo_attivo({"fino_a": "2026-11-22T00:00:00"}, ora) == "2026-11-22T00:00:00"
    assert mc.posticipo_attivo({"fino_a": "2026-11-20T00:00:00"}, ora) is None


def test_i_corpi_json_della_mini_app_devono_essere_oggetti():
    sorgente = (RADICE / "app" / "miniapp.py").read_text(encoding="utf-8")
    assert sorgente.count("body = await request.json()") == \
        sorgente.count("if not isinstance(body, dict):      # `[1]` è JSON valido") == 6
    assert "except Exception:\n        return JSONResponse({\"error\": \"invalid_request\"}" not in sorgente


def test_la_richiesta_di_aggiornamento_si_scrive_tutta_o_niente():
    sorgente = (RADICE / "app" / "miniapp.py").read_text(encoding="utf-8")
    i = sorgente.index("async def api_update_trigger(")
    corpo = sorgente[i:sorgente.index("\nasync def ", i + 1)]
    assert "os.replace(tmp, path)" in corpo and "path.write_text(" not in corpo
    assert "except OSError" in corpo and "status_code=507" in corpo


def test_le_due_copie_di_client_ip_fanno_la_stessa_cosa():
    def corpo(nome_file: str) -> str:
        s = (RADICE / "app" / nome_file).read_text(encoding="utf-8")
        i = s.index("def _client_ip(request: Request) -> str:")
        righe = [r.strip() for r in s[i:s.index("\n\n\n", i)].splitlines()[1:]]
        return "\n".join(r for r in righe if r.startswith(("if ", "return ")))
    assert corpo("admin.py") == corpo("miniapp.py") != ""
