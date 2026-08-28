"""Il servizio ocr: la logica pura, provata coi subprocess finti (stdlib-only).

Qui il subprocess è IL MESTIERE — è il gateway che non deve averlo (presidio
test_gateway_non_tocca_docker, che ha bocciato la prima stesura del B5). Questo
file prova i tre esiti del contratto povero: testo → 200, immagine muta → 200
vuoto, tesseract rotto/assente → 502 con un motivo in una riga.
"""
from __future__ import annotations

import types
from pathlib import Path

# import per PATH DI FILE con nome univoco: il pacchetto si chiama `app` come
# quello di ogni fratello, e in una run pytest condivisa `sys.modules["app"]`
# sarebbe una monetina — chi importa per primo vince (visto in collection).
import importlib.util  # noqa: E402

_SRC = Path(__file__).resolve().parents[2] / "services" / "ocr" / "app" / "__main__.py"
_spec = importlib.util.spec_from_file_location("ocr_servizio_main", _SRC)
ocr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ocr)


def test_testo_esce_200(monkeypatch) -> None:
    def finto(cmd, input=b"", capture_output=True, timeout=0):
        assert cmd[:3] == ["tesseract", "stdin", "stdout"], "ricetta cambiata di nascosto"
        return types.SimpleNamespace(stdout=b" testo letto ", stderr=b"", returncode=0)
    monkeypatch.setattr(ocr.subprocess, "run", finto)
    assert ocr.ocr_bytes(b"\x89PNGfinta") == (200, b"testo letto")


def test_immagine_muta_esce_200_vuoto(monkeypatch) -> None:
    monkeypatch.setattr(ocr.subprocess, "run", lambda *a, **k: types.SimpleNamespace(
        stdout=b"", stderr=b"", returncode=0))
    assert ocr.ocr_bytes(b"\x89PNGfinta") == (200, b"")


def test_tesseract_rotto_esce_502_col_motivo(monkeypatch) -> None:
    monkeypatch.setattr(ocr.subprocess, "run", lambda *a, **k: types.SimpleNamespace(
        stdout=b"", stderr=b"riga1\nError: cattivo file", returncode=1))
    status, body = ocr.ocr_bytes(b"finta")
    assert status == 502 and b"cattivo file" in body


def test_tesseract_assente_esce_502(monkeypatch) -> None:
    def esplode(*a, **k):
        raise FileNotFoundError("tesseract")
    monkeypatch.setattr(ocr.subprocess, "run", esplode)
    status, body = ocr.ocr_bytes(b"finta")
    assert status == 502 and b"non installato" in body


def test_i_tetti_del_body() -> None:
    assert ocr.ocr_bytes(b"")[0] == 400
    assert ocr.ocr_bytes(b"x" * (ocr.MAX_BODY + 1))[0] == 413
