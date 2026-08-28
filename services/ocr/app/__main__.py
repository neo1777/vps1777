"""ocr — il servizio interno che presta gli occhi all'ingest (B5, 28/08/2026).

PERCHÉ UN SERVIZIO A SÉ e non tesseract nel gateway: il presidio
`test_gateway_non_tocca_docker` custodisce l'invariante «il gateway non esegue
processi — scrive un intent, non agisce», e ha bocciato (giustamente) la prima
versione che importava `subprocess` lì. Qui il subprocess è il MESTIERE, e il
perimetro lo contiene: nessuna porta pubblicata (solo la rete interna
`backend`), nessun volume, nessun segreto, un solo binario invocato con
argomenti FISSI su bytes che arrivano nel body. Un'immagine malevola può al
più rompere QUESTO container, che non custodisce niente.

Protocollo, deliberatamente povero:
  POST /ocr   body = bytes dell'immagine → 200 con il testo estratto (UTF-8);
              immagine senza testo → 200 con body vuoto (il chiamante decide);
              tesseract fallisce → 502 col motivo in una riga.
  GET  /health → 200 «ok» (per il healthcheck del compose).

La ricetta tesseract (`-l ita+eng`, timeout) è quella provata su _chat/ocr1777
(21-22/07/2026: 562/562 immagini, 0 errori).
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LINGUE = os.environ.get("OCR_LINGUE", "ita+eng")
TIMEOUT_S = int(os.environ.get("OCR_TIMEOUT_S", "120"))
MAX_BODY = int(os.environ.get("OCR_MAX_BODY", str(16 * 1024 * 1024)))

log = logging.getLogger("ocr")


def ocr_bytes(raw: bytes) -> tuple[int, bytes]:
    """(status, body) per un'immagine. Logica pura-ish: testabile senza il server."""
    if not raw:
        return 400, b"body vuoto: mandami i bytes dell'immagine"
    if len(raw) > MAX_BODY:
        return 413, f"immagine oltre il tetto di {MAX_BODY} byte".encode()
    try:
        r = subprocess.run(["tesseract", "stdin", "stdout", "-l", LINGUE],
                           input=raw, capture_output=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return 502, b"tesseract oltre il timeout"
    except FileNotFoundError:
        return 502, b"tesseract non installato nell'immagine (build rotta)"
    if r.returncode != 0:
        # una riga di motivo, mai lo stderr intero (può contenere path/rumore)
        riga = (r.stderr or b"").decode("utf-8", errors="replace").splitlines()
        return 502, f"tesseract rc={r.returncode}: {riga[-1][:200] if riga else ''}".encode()
    return 200, r.stdout.strip()


class _H(BaseHTTPRequestHandler):
    def _rispondi(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:                                  # noqa: N802
        if self.path == "/health":
            self._rispondi(200, b"ok")
        else:
            self._rispondi(404, b"solo POST /ocr e GET /health")

    def do_POST(self) -> None:                                 # noqa: N802
        if self.path != "/ocr":
            self._rispondi(404, b"solo POST /ocr e GET /health")
            return
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            self._rispondi(413, b"Content-Length oltre il tetto")
            return
        raw = self.rfile.read(n)
        status, body = ocr_bytes(raw)
        self._rispondi(status, body)

    def log_message(self, fmt: str, *args) -> None:            # noqa: A003
        log.info("%s " + fmt, self.address_string(), *args)


def main() -> None:
    logging.basicConfig(level="INFO", stream=sys.stdout,
                        format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    host = os.environ.get("OCR_HOST", "0.0.0.0")
    port = int(os.environ.get("OCR_PORT", "8004"))
    log.info("vps1777-ocr starting · %s:%s · lingue=%s", host, port, LINGUE)
    ThreadingHTTPServer((host, port), _H).serve_forever()


if __name__ == "__main__":
    main()
