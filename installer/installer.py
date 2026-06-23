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
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = int(os.environ.get("VPS1777_INSTALLER_PORT", "8777"))

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
        if self.path in ("/", "/index.html"):
            self._send(200, (HERE / "ui.html").read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/api/env":
            self._send(200, json.dumps({"paramiko": _PARAMIKO}).encode(), "application/json")
        else:
            self._send(404, b"not found", "text/plain")

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
        elif self.path == "/api/deploy":
            p = self._read_json()
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            try:
                for line in engine.run(p):
                    self.wfile.write((json.dumps({"line": line}) + "\n").encode())
                    self.wfile.flush()
            except BrokenPipeError:
                pass
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
