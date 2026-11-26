"""Le strade di `_iter_zip_annidato`: ogni tipo di membro nella sua trafila, e ogni lapide.

Un archivio dentro i workfiles (zip o .skill) si apre per UN livello. Qui ogni strada ha la
sua prova: archivio illeggibile, troppi membri, membro oltre il suo tetto (lapide) contro il
tetto dell'archivio intero (errore che sale), membro rotto, e i sei tipi di contenuto.
"""
from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import archive_indexer as ai  # noqa: E402

TS = "2026-01-01T00:00:00Z"


def _zip(membri: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for nome, dati in membri.items():
            z.writestr(nome, dati)
    return buf.getvalue()


def _corri(raw: bytes, budget=None, **kw) -> list:
    return list(ai._iter_zip_annidato(raw, "arch.zip", "etichetta", TS, budget or ai._Budget(), **kw))


def _lapidi(righe: list) -> list[tuple]:
    return [(r.source, r.reason, r.detail) for r in righe if isinstance(r, ai._Skip)]


def test_un_archivio_illeggibile_e_una_lapide_sola():
    assert _lapidi(_corri(b"non uno zip")) == [("bundle-workfiles", "zip-illeggibile", "arch.zip")]


def test_troppi_membri_una_lapide_col_numero_e_niente_altro(monkeypatch):
    monkeypatch.setattr(ai, "MAX_ZIP_ANNIDATO_MEMBRI", 1)
    righe = _corri(_zip({"a.txt": b"uno", "b.txt": b"due", "cartella/": b""}), fonte="bundle-documents")
    assert _lapidi(righe) == [("bundle-documents", "zip-troppi-membri", "arch.zip: 2")]
    assert len(righe) == 1


def test_le_cartelle_non_contano_e_non_si_leggono(monkeypatch):
    monkeypatch.setattr(ai, "MAX_ZIP_ANNIDATO_MEMBRI", 1)
    righe = _corri(_zip({"cartella/": b"", "a.txt": b"uno"}))
    assert _lapidi(righe) == [] and len(righe) == 1


def test_un_membro_oltre_il_suo_tetto_e_una_lapide_e_il_vicino_entra(monkeypatch):
    monkeypatch.setattr(ai, "MAX_MEMBER_BYTES", 10)
    righe = _corri(_zip({"grande.txt": b"x" * 50, "dopo.txt": b"ciao"}))
    assert _lapidi(righe) == [("bundle-workfiles", "membro-oltre-tetto", "arch.zip!grande.txt")]
    assert [r[3] for r in righe if not isinstance(r, ai._Skip)] == ["[arch.zip!dopo.txt]\nciao"]


def test_il_budget_arrivato_a_zero_giusto_non_e_ancora_il_tetto_dell_archivio(monkeypatch):
    monkeypatch.setattr(ai, "MAX_MEMBER_BYTES", 10)
    budget = ai._Budget(50)
    righe = _corri(_zip({"grande.txt": b"x" * 50}), budget)
    assert budget.left == 0
    assert _lapidi(righe) == [("bundle-workfiles", "membro-oltre-tetto", "arch.zip!grande.txt")]


def test_il_tetto_dell_archivio_intero_non_si_assorbe():
    with pytest.raises(ValueError):
        _corri(_zip({"a.txt": b"x" * 50, "b.txt": b"mai letto"}), ai._Budget(20))


def test_un_membro_rotto_e_una_lapide_e_il_vicino_entra():
    raw = bytearray(_zip({"rotto.txt": b"contenuto-da-rovinare", "dopo.txt": b"ciao"}))
    i = raw.index(b"contenuto-da-rovinare")
    raw[i:i + 4] = b"XXXX"                     # il CRC non torna più
    righe = _corri(bytes(raw))
    assert _lapidi(righe) == [("bundle-workfiles", "membro-illeggibile", "arch.zip!rotto.txt")]
    assert len(righe) == 2


@pytest.mark.parametrize("nome", ["dentro.zip", "cosa.skill", "MAIUSCOLO.ZIP"])
def test_un_archivio_dentro_l_archivio_non_si_apre(nome):
    righe = _corri(_zip({nome: _zip({"x.txt": b"ciao"})}))
    assert _lapidi(righe) == [("bundle-workfiles", "zip-annidato-oltre-profondita", f"arch.zip!{nome}")]


def test_immagini_e_pdf_vanno_alla_loro_trafila_con_la_fonte(monkeypatch):
    visti = []
    monkeypatch.setattr(ai, "_iter_immagine_bytes",
                        lambda raw, name, label, ts, *, fonte: visti.append(("img", raw, name, label, ts, fonte)) or iter(()))
    monkeypatch.setattr(ai, "_iter_pdf_bytes",
                        lambda raw, name, label, ts, *, fonte: visti.append(("pdf", raw, name, label, ts, fonte)) or iter(()))
    assert _corri(_zip({"foto.PNG": b"i", "carta.pdf": b"p"}), fonte="bundle-documents") == []
    assert visti == [("img", b"i", "arch.zip!foto.PNG", "etichetta", TS, "bundle-documents"),
                     ("pdf", b"p", "arch.zip!carta.pdf", "etichetta", TS, "bundle-documents")]


def test_un_jsonl_di_claude_code_entra_come_conversazione():
    riga = json.dumps({"type": "user", "uuid": "u1", "timestamp": TS, "sessionId": "s",
                       "cwd": "/home/x/progetto", "message": {"role": "user", "content": "ciao dal jsonl"}})
    righe = _corri(_zip({"sessione.jsonl": (riga + "\n").encode()}))
    assert len(righe) == 2 and righe[0][0] == "u1" and righe[0][3] == "ciao dal jsonl"
    assert righe[1] == ai._Sighting("u1", "arch.zip!sessione.jsonl")   # la copia vista, col suo nome


def test_un_json_qualunque_entra_a_pezzi_da_quattromila():
    testo = "\n\n".join(["paragrafo " + "x" * 990] * 6)          # sei paragrafi da ~1000
    righe = _corri(_zip({"dati.json": testo.encode()}))
    assert _lapidi(righe) == []
    assert len(righe) == 2                                        # a 1500 sarebbero tre
    assert all(r[1] == "etichetta" and r[2] == TS for r in righe)


def test_un_documento_entra_col_suo_nome_in_testa():
    righe = _corri(_zip({"note.md": "àccenti e testo".encode()}))
    assert [r[3] for r in righe] == ["[arch.zip!note.md]\nàccenti e testo"]


def test_un_testo_senza_estensione_nota_entra_dichiarando_lo_sniff():
    righe = _corri(_zip({"LEGGIMI.sconosciuta": b"testo semplice, leggibile\n" * 3}))
    assert len(righe) == 1 and righe[0][3].startswith("[arch.zip!LEGGIMI.sconosciuta] [testo-sniffato]\n")


def test_un_binario_senza_estensione_nota_e_una_lapide():
    righe = _corri(_zip({"dati.sconosciuta": bytes(range(256)) * 4}))
    assert _lapidi(righe) == [("bundle-workfiles", "non-testo", "arch.zip!dati.sconosciuta")]
