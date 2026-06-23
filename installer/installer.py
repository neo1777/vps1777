#!/usr/bin/env python3
"""
vps1777 installer — mini-server locale per l'installer web.

Gira sul TUO PC (non sulla VPS). Serve la UI (ui.html) su 127.0.0.1 e fa da
ponte verso deploy.sh: valida la connessione SSH live, lancia il deploy in
streaming, estrae i dati finali.

Zero dipendenze: solo stdlib. Avvialo con launch.sh / launch.bat (che apre
anche il browser), oppure:
    python3 installer/installer.py
poi apri http://127.0.0.1:8777

Vincoli: il browser non può fare SSH; questo server sì (chiama ssh/sshpass).
Tutto resta su 127.0.0.1, le credenziali non lasciano la tua macchina.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
HOST = "127.0.0.1"
PORT = int(os.environ.get("VPS1777_INSTALLER_PORT", "8777"))

IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")


def _ssh_base(ip: str, user: str, password: str) -> list[str]:
    """Costruisce il comando ssh (con sshpass se c'è una password)."""
    opts = [
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=10",
        "-o", "PreferredAuthentications=password,publickey",
    ]
    target = f"{user}@{ip}"
    if password:
        if not shutil.which("sshpass"):
            return []  # segnalato dal chiamante
        return ["sshpass", "-p", password, "ssh", *opts, target]
    return ["ssh", *opts, target]


def check_ssh(ip: str, user: str, password: str) -> dict:
    """Testa la connessione SSH e ritorna lo stato + info OS."""
    if not IP_RE.match(ip):
        return {"ok": False, "error": "IP non valido"}
    if password and not shutil.which("sshpass"):
        return {"ok": False, "error": "sshpass non installato sul PC (serve per auth password). In WSL: sudo apt install sshpass"}
    base = _ssh_base(ip, user, password)
    if not base:
        return {"ok": False, "error": "sshpass mancante"}
    # pulizia known_hosts stale (VPS riformattata)
    kh = Path.home() / ".ssh" / "known_hosts"
    if kh.exists():
        subprocess.run(["ssh-keygen", "-f", str(kh), "-R", ip],
                       capture_output=True, check=False)
    try:
        r = subprocess.run(
            [*base, ". /etc/os-release 2>/dev/null; echo \"$PRETTY_NAME ($(uname -m))\""],
            capture_output=True, text=True, timeout=20,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Timeout: la VPS non risponde su SSH (porta 22)"}
    if r.returncode != 0:
        msg = (r.stderr or "").strip().splitlines()
        last = msg[-1] if msg else "connessione fallita"
        return {"ok": False, "error": last}
    return {"ok": True, "os": r.stdout.strip()}


def run_deploy(params: dict):
    """
    Generator che lancia deploy.sh con le variabili d'ambiente raccolte e
    streama l'output riga per riga. NONINTERACTIVE=1 → nessun prompt.
    """
    env = os.environ.copy()
    env["NONINTERACTIVE"] = "1"
    env["VPS_IP"] = params.get("ip", "")
    env["VPS_USER"] = params.get("user", "root")
    env["VPS_PASS"] = params.get("password", "")
    env["ADMIN_EMAIL"] = params.get("admin_email", "")
    env["TG_OWNER_ID"] = params.get("telegram_owner_id", "")
    env["INGRESS_NUM"] = params.get("ingress_num", "1")
    env["TS_HOSTNAME"] = params.get("ts_hostname", "vps1777")
    env["TS_AUTHKEY"] = params.get("ts_authkey", "")
    env["TG_TOKEN"] = params.get("telegram_bot_token", "")
    env["CADDY_DOMAIN"] = params.get("caddy_domain", "")
    env["CADDY_EMAIL"] = params.get("caddy_email", "")
    env["CF_TOKEN"] = params.get("cf_token", "")
    env["GEN_PWD"] = "auto"  # l'installer genera sempre la password admin

    cmd = ["bash", str(REPO / "deploy.sh"), params.get("ip", "")]
    proc = subprocess.Popen(
        cmd, cwd=str(REPO), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        yield line.rstrip("\n")
    proc.wait()
    yield f"__EXIT__{proc.returncode}"


# ─────────────────────────────────────────── HTTP handler

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_a):  # silenzia il log di default
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            html = (HERE / "ui.html").read_bytes()
            self._send(200, html, "text/html; charset=utf-8")
        elif self.path == "/api/env":
            # info ambiente: sshpass presente?
            data = json.dumps({
                "sshpass": bool(shutil.which("sshpass")),
                "ssh": bool(shutil.which("ssh")),
            }).encode()
            self._send(200, data, "application/json")
        else:
            self._send(404, b"not found", "text/plain")

    def _read_json(self) -> dict:
        n = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(n) if n else b"{}"
        try:
            return json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return {}

    def do_POST(self):
        if self.path == "/api/check":
            params = self._read_json()
            res = check_ssh(params.get("ip", ""), params.get("user", "root"),
                            params.get("password", ""))
            self._send(200, json.dumps(res).encode(), "application/json")

        elif self.path == "/api/deploy":
            params = self._read_json()
            # streaming chunked: una riga JSON per evento
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            try:
                for line in run_deploy(params):
                    evt = json.dumps({"line": line}) + "\n"
                    self.wfile.write(evt.encode())
                    self.wfile.flush()
            except BrokenPipeError:
                pass
        else:
            self._send(404, b"not found", "text/plain")


def main():
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}"
    print(f"\n  vps1777 installer → {url}\n  (Ctrl+C per uscire)\n")
    # apri il browser dopo un attimo
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  Chiuso.\n")
        srv.shutdown()


if __name__ == "__main__":
    main()
