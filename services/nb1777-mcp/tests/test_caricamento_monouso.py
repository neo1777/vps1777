"""P15, seconda metà (10/10/2026): il caricamento monouso di una fonte, senza pannello.

`source_add_file` legge un path sul server: da claude.ai o dal telefono non c'era modo di
mandare un file. Ora `source_upload_link` dà un link `/carica/<gettone>` valido 15 minuti
e UNA volta sola; il gateway passa il corpo in streaming a `/internal/nlm/carica`, e qui il
file si scrive a pezzi (tetto 200 MB, il limite di NotebookLM per fonte), diventa una fonte
del notebook e si cancella. Il gettone si consuma PRIMA di leggere un byte del file.
"""
from __future__ import annotations

import asyncio
from urllib.parse import urlencode

import pytest
from starlette.requests import Request

from app import caricamenti, core, server


@pytest.fixture(autouse=True)
def registro_pulito(monkeypatch):
    monkeypatch.setattr(caricamenti, "_APERTI", {})


def test_il_gettone_vale_una_volta_sola():
    t = caricamenti.apri("nb-1", "Titolo")
    assert caricamenti.consuma(t) == ("nb-1", "Titolo")
    assert "non vale" in caricamenti.consuma(t), "il secondo uso deve fallire"
    assert "non vale" in caricamenti.consuma("inventato")


def test_il_gettone_scade_in_un_quarto_d_ora():
    assert caricamenti.DURATA_S == 15 * 60
    t = caricamenti.apri("nb-1", "", ora=1000)
    assert "scaduto" in caricamenti.consuma(t, ora=1000 + caricamenti.DURATA_S + 1)


def test_i_link_aperti_hanno_un_tetto():
    for _ in range(caricamenti.MAX_APERTI):
        caricamenti.apri("nb", "")
    with pytest.raises(ValueError):
        caricamenti.apri("nb", "")


def test_il_link(monkeypatch):
    monkeypatch.setenv("GATEWAY_PUBLIC_BASE", "https://vps.example.invalid/")
    collegamento = caricamenti.link("abc", 1000)
    assert collegamento == {"url": "https://vps.example.invalid/carica/abc", "scade_il": "1970-01-01T00:16:40Z"}


async def _pezzi(*pp):
    for p in pp:
        yield p


def test_scrivi_a_pezzi_e_tetto(tmp_path, monkeypatch):
    dest = tmp_path / "f.txt"
    assert asyncio.run(caricamenti.scrivi(_pezzi(b"ab", b"cd"), dest)) == 4
    assert dest.read_bytes() == b"abcd"
    monkeypatch.setattr(caricamenti, "TETTO_BYTE", 3)
    with pytest.raises(caricamenti.TroppoGrande):
        asyncio.run(caricamenti.scrivi(_pezzi(b"ab", b"cd"), tmp_path / "g.txt"))
    assert not (tmp_path / "g.txt").exists(), "un file oltre il tetto non resta sul disco"


def test_senza_spazio_non_scrive(tmp_path, monkeypatch):
    monkeypatch.setattr(caricamenti.shutil, "disk_usage",
                        lambda p: type("U", (), {"free": 10})())
    with pytest.raises(caricamenti.SenzaSpazio):
        asyncio.run(caricamenti.scrivi(_pezzi(b"x"), tmp_path / "h.txt"))


def _richiesta(t: str, nome: str, corpo: bytes, cl: int | None = None) -> Request:
    inviato = {"fatto": False}

    async def ricevi():
        if inviato["fatto"]:
            return {"type": "http.request", "body": b"", "more_body": False}
        inviato["fatto"] = True
        return {"type": "http.request", "body": corpo, "more_body": False}

    intestazioni = [(b"content-length", str(len(corpo) if cl is None else cl).encode())]
    return Request({"type": "http", "method": "PUT", "path": "/internal/nlm/carica",
                    "headers": intestazioni,
                    "query_string": urlencode({"t": t, "nome": nome}).encode()}, ricevi)


@pytest.fixture
def servizio(monkeypatch, tmp_path):
    monkeypatch.setenv("NLM_ARTIFACTS", str(tmp_path))
    monkeypatch.setattr(server, "_internal_ok", lambda request: True)
    monkeypatch.setattr(server, "_check_auth_or_raise", lambda: None)
    visti = []

    def finto_add(nb, path, *, title=None, **k):
        visti.append((nb, path.read_bytes(), title))
        return "src-1"
    monkeypatch.setattr(core, "source_add_file", finto_add)
    return visti, tmp_path


def test_caricamento_buono(servizio):
    visti, cartella = servizio
    t = caricamenti.apri("nb-1", "Il mio PDF")
    r = asyncio.run(server.internal_nlm_carica(_richiesta(t, "../../relazione finale.pdf", b"%PDF-1")))
    assert r.status_code == 200, r.body
    assert visti == [("nb-1", b"%PDF-1", "Il mio PDF")]
    assert list(cartella.iterdir()) == [], "il file temporaneo si cancella dopo"
    r2 = asyncio.run(server.internal_nlm_carica(_richiesta(t, "x.pdf", b"%PDF-1")))
    assert r2.status_code == 403, "il link vale una volta sola"


def test_senza_titolo_si_usa_il_nome_del_file(servizio):
    visti, _ = servizio
    t = caricamenti.apri("nb-1", "")
    asyncio.run(server.internal_nlm_carica(_richiesta(t, "note.md", b"# ciao")))
    assert visti[0][2] == "note.md"


def test_troppo_grande_dichiarato_non_consuma_il_gettone(servizio, monkeypatch):
    monkeypatch.setattr(caricamenti, "TETTO_BYTE", 3)
    t = caricamenti.apri("nb-1", "")
    r = asyncio.run(server.internal_nlm_carica(_richiesta(t, "a.txt", b"abcd")))
    assert r.status_code == 413
    assert caricamenti.consuma(t) == ("nb-1", ""), "con un file più piccolo il link vale ancora"


def test_file_vuoto(servizio):
    t = caricamenti.apri("nb-1", "")
    r = asyncio.run(server.internal_nlm_carica(_richiesta(t, "a.txt", b"")))
    assert r.status_code == 400


def test_senza_segreto_interno_niente(servizio, monkeypatch):
    monkeypatch.setattr(server, "_internal_ok", lambda request: False)
    t = caricamenti.apri("nb-1", "")
    assert asyncio.run(server.internal_nlm_carica(_richiesta(t, "a.txt", b"x"))).status_code == 403
    assert caricamenti.consuma(t) == ("nb-1", ""), "una richiesta rifiutata non consuma il link"


def test_il_tool_da_il_link(monkeypatch):
    monkeypatch.setattr(server, "_check_auth_or_raise", lambda: None)
    monkeypatch.setattr(core, "nb_get", lambda nb: {"id": nb, "title": "Prova"})
    monkeypatch.setenv("GATEWAY_PUBLIC_BASE", "https://vps.example.invalid")
    out = asyncio.run(server.source_upload_link("nb-1", title="T"))
    assert out["url"].startswith("https://vps.example.invalid/carica/")
    assert out["notebook"] == "Prova" and "curl -T" in out["come"]
    t = out["url"].rsplit("/", 1)[1]
    assert caricamenti.consuma(t) == ("nb-1", "T")
