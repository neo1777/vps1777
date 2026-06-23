#!/usr/bin/env python3
"""
vps1777 installer — mini-server locale per l'installer web (cross-OS).

Gira sul TUO PC (Windows / Mac / Linux). Serve la UI (ui.html) su 127.0.0.1
e fa il deploy via SSH **in Python puro** (paramiko): nessun bash, nessun
sshpass, nessun WSL richiesto.

Avvio: launch.sh (Linux/Mac/WSL) o launch.bat (Windows) — installano paramiko
se manca e aprono il browser. Oppure manuale:
    pip install paramiko
    python installer/installer.py
poi apri http://127.0.0.1:8777

Tutto resta su 127.0.0.1: le credenziali non lasciano la tua macchina.
"""
from __future__ import annotations

import json
import os
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = int(os.environ.get("VPS1777_INSTALLER_PORT", "8777"))

# ── Stato del deploy (singleton) ───────────────────────────────────────────
# Il deploy gira in un THREAD sul server e scrive le righe in un buffer in
# memoria. La connessione HTTP della UI si limita a *rileggere* il buffer: se
# il browser viene aggiornato/chiuso, il deploy continua indisturbato e la UI,
# al ricaricamento, si riaggancia al buffer e riprende lo streaming da capo.
# Niente più deploy uccisi da un refresh.
DEPLOY: dict = {
    "running": False,   # un deploy è in corso?
    "done": False,      # un deploy è terminato (con successo o no)?
    "exit": None,       # exit code finale (0 = ok)
    "lines": [],        # tutte le righe emesse (replay completo a ogni attach)
    "started": None,    # time.monotonic() di inizio (per il timer della UI)
}
DEPLOY_LOCK = threading.Lock()


def _run_deploy(params: dict):
    """Esegue engine.run() in un thread, accumulando le righe nel buffer."""
    try:
        for line in engine.run(params):
            with DEPLOY_LOCK:
                DEPLOY["lines"].append(line)
            if line.startswith("__EXIT__"):
                try:
                    DEPLOY["exit"] = int(line[len("__EXIT__"):])
                except ValueError:
                    DEPLOY["exit"] = 1
    except Exception as e:  # noqa: BLE001 — non far morire il thread in silenzio
        with DEPLOY_LOCK:
            DEPLOY["lines"].append(f"✗ Errore interno installer: {e}")
            DEPLOY["lines"].append("__EXIT__1")
            DEPLOY["exit"] = 1
    finally:
        with DEPLOY_LOCK:
            if DEPLOY["exit"] is None:
                DEPLOY["exit"] = 0
            DEPLOY["running"] = False
            DEPLOY["done"] = True

# paramiko è la sola dipendenza esterna. Se manca, la UI lo segnala.
try:
    import paramiko  # noqa: F401
    from . import engine  # type: ignore
    _PARAMIKO = True
except Exception:
    try:
        import importlib.util
        import sys as _sys
        _spec = importlib.util.spec_from_file_location("engine", HERE / "engine.py")
        engine = importlib.util.module_from_spec(_spec)  # type: ignore
        _sys.modules["engine"] = engine
        _spec.loader.exec_module(engine)  # type: ignore
        _PARAMIKO = True
    except Exception:
        engine = None  # type: ignore
        _PARAMIKO = False


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_a):
        pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send(200, (HERE / "ui.html").read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/env":
            self._send(200, json.dumps({"paramiko": _PARAMIKO}).encode(), "application/json")
        elif path == "/api/status":
            # La UI lo interroga al caricamento: se c'è un deploy vivo/finito,
            # si riaggancia invece di ripartire dal form.
            with DEPLOY_LOCK:
                elapsed = (time.monotonic() - DEPLOY["started"]) if DEPLOY["started"] else 0
                st = {
                    "running": DEPLOY["running"],
                    "done": DEPLOY["done"],
                    "exit": DEPLOY["exit"],
                    "count": len(DEPLOY["lines"]),
                    "elapsed": int(elapsed),
                }
            self._send(200, json.dumps(st).encode(), "application/json")
        elif path == "/api/stream":
            self._stream_deploy()
        else:
            self._send(404, b"not found", "text/plain")

    def _stream_deploy(self):
        """Streaming ndjson del buffer di deploy: replay da ?from=N + tail live.

        Riconnettersi (refresh) riapre questo stream da capo (from=0) e rivede
        tutta la console + il seguito, perché il buffer vive nel server.
        """
        q = parse_qs(urlparse(self.path).query)
        try:
            idx = int(q.get("from", ["0"])[0])
        except ValueError:
            idx = 0
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            while True:
                with DEPLOY_LOCK:
                    n = len(DEPLOY["lines"])
                    batch = DEPLOY["lines"][idx:n]
                    done = DEPLOY["done"]
                for line in batch:
                    self.wfile.write((json.dumps({"line": line}) + "\n").encode())
                if batch:
                    self.wfile.flush()
                    idx = n
                if done and idx >= n:
                    break
                if not batch:
                    time.sleep(0.3)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _read_json(self):
        n = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(n) if n else b"{}"
        try:
            return json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return {}

    def do_POST(self):
        if not _PARAMIKO:
            self._send(200, json.dumps({"ok": False, "error": "paramiko non installato. Riavvia con launch.sh/launch.bat, oppure: pip install paramiko"}).encode(), "application/json")
            return
        if self.path == "/api/check":
            p = self._read_json()
            res = engine.check(p.get("ip", ""), p.get("user", "root"), p.get("password", ""))
            self._send(200, json.dumps(res).encode(), "application/json")
        elif self.path == "/api/check-telegram":
            p = self._read_json()
            res = engine.check_telegram(p.get("token", ""))
            self._send(200, json.dumps(res).encode(), "application/json")
        elif self.path == "/api/deploy":
            p = self._read_json()
            # Avvia il deploy in un thread. Se ne gira già uno, NON lo rilancia
            # (un refresh che ri-POSTasse non deve duplicare il deploy).
            with DEPLOY_LOCK:
                if DEPLOY["running"]:
                    self._send(200, json.dumps({"started": False, "running": True}).encode(), "application/json")
                    return
                DEPLOY["running"] = True
                DEPLOY["done"] = False
                DEPLOY["exit"] = None
                DEPLOY["lines"] = []
                DEPLOY["started"] = time.monotonic()
            threading.Thread(target=_run_deploy, args=(p,), daemon=True).start()
            self._send(200, json.dumps({"started": True}).encode(), "application/json")
        else:
            self._send(404, b"not found", "text/plain")


def main():
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}"
    print(f"\n  vps1777 installer → {url}")
    if not _PARAMIKO:
        print("  ⚠ paramiko non trovato — installalo: pip install paramiko")
    print("  (Ctrl+C per uscire)\n")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  Chiuso.\n")
        srv.shutdown()


if __name__ == "__main__":
    main()
