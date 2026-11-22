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
                # Il motore ha finito senza dire com'è andata: non è un successo. Prima qui
                # si scriveva 0, e la UI mostrava «installazione riuscita».
                DEPLOY["lines"].append("✗ L'installazione si è fermata senza dichiarare un esito.")
                DEPLOY["lines"].append("__EXIT__1")
                DEPLOY["exit"] = 1
            DEPLOY["running"] = False
            DEPLOY["done"] = True

# paramiko è la sola dipendenza esterna. Se manca, la UI lo segnala.
_ERRORE_MOTORE = ""     # perché il motore non si è caricato, se non è «manca paramiko»
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
    except ModuleNotFoundError as e:
        engine = None  # type: ignore
        _PARAMIKO = False
        if e.name != "paramiko":
            _ERRORE_MOTORE = f"{type(e).__name__}: {e}"
    except Exception as e:  # noqa: BLE001 — un guasto del motore non è «manca paramiko»: si dice qual è
        engine = None  # type: ignore
        _PARAMIKO = False
        _ERRORE_MOTORE = f"{type(e).__name__}: {e}"

# Il corpo di una richiesta alla UI locale è un form: un megabyte è già cento volte troppo.
CORPO_MAX_BYTE = 1024 * 1024


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_a):
        pass

    def _da_qui(self) -> bool:
        """La richiesta arriva dalla NOSTRA pagina, su questo PC?

        Il server ascolta solo su 127.0.0.1, ma un browser ci arriva anche per conto di
        un'altra pagina web: una pagina qualunque può fare una POST a http://127.0.0.1:8777
        (avviare o chiudere un'installazione), e con un nome che cambia indirizzo a metà
        (DNS rebinding) può LEGGERE /api/stream, dove alla fine passano la password admin e
        il segreto del gateway (H98). Due controlli, tutti e due sull'intestazione che il
        browser scrive da sé e una pagina non può falsificare:
          · `Host` deve essere il nostro indirizzo locale (ferma il rebinding);
          · `Origin`, quando c'è, deve essere la nostra pagina (ferma le POST di altri siti).
        Un client che non è un browser (il rilancio dell'installer, curl) non manda Origin.
        """
        ammessi = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
        if (self.headers.get("Host") or "").strip().lower() not in ammessi:
            return False
        origine = (self.headers.get("Origin") or "").strip().lower()
        return not origine or origine in {f"http://{h}" for h in ammessi}

    def _rifiuta(self):
        self._send(403, b"richiesta non ammessa: questa pagina risponde solo a se stessa\n",
                   "text/plain; charset=utf-8")

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._da_qui():
            return self._rifiuta()
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send(200, (HERE / "ui.html").read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/env":
            self._send(200, json.dumps({"paramiko": _PARAMIKO, "errore": _ERRORE_MOTORE}).encode(), "application/json")
        elif path == "/__ping":
            # Firma per il rilancio: un nuovo installer la legge per sapere che chi
            # occupa la porta è un SUO predecessore (e non un servizio qualunque)
            # prima di chiedergli di uscire. Vedi _libera_porta().
            self._send(200, json.dumps({"vps1777_installer": True, "pid": os.getpid()}).encode(), "application/json")
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
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return {}
        if n < 0 or n > CORPO_MAX_BYTE:
            return {}
        raw = self.rfile.read(n) if n else b"{}"
        try:
            dati = json.loads(raw or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
        return dati if isinstance(dati, dict) else {}

    def do_POST(self):
        if not self._da_qui():
            return self._rifiuta()
        if self.path == "/__quit":
            # Un nuovo installer chiede a questo di uscire (porta occupata da un
            # run precedente mai chiuso — misurato 23/08: il browser non si apriva
            # e il motivo era il predecessore ancora vivo). Shutdown in un thread:
            # farlo nel handler bloccherebbe serve_forever su se stesso.
            self._send(200, json.dumps({"ok": True, "bye": os.getpid()}).encode(), "application/json")
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if not _PARAMIKO:
            errore = (f"il motore dell'installer non si è caricato ({_ERRORE_MOTORE})" if _ERRORE_MOTORE
                      else "paramiko non installato. Riavvia con launch.sh/launch.bat, oppure: pip install paramiko")
            self._send(200, json.dumps({"ok": False, "error": errore}).encode(), "application/json")
            return
        if self.path == "/api/check":
            p = self._read_json()
            res = engine.check(p.get("ip", ""), p.get("user", "root"), p.get("password", ""),
                               nuova_chiave_host=bool(p.get("nuova_chiave_host")))
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


def _e_un_nostro_installer(cmdline: str, proc: Path) -> bool:
    """Vero solo se quel processo è un Python che esegue QUESTO installer.py.

    Prima bastava che la riga di comando contenesse «installer.py»: un editor aperto su un
    file con quel nome, o l'installer di un altro programma, ricevevano il SIGTERM. Ora
    servono un interprete Python come primo argomento e un argomento che, risolto dalla
    cartella di lavoro di quel processo, sia proprio il nostro file.
    """
    argomenti = [a for a in cmdline.split("\0") if a]
    if not argomenti or not Path(argomenti[0]).name.lower().startswith("python"):
        return False
    nostro = (HERE / "installer.py").resolve()
    try:
        cwd = (proc / "cwd").resolve()
    except OSError:
        cwd = None
    for a in argomenti[1:]:
        if Path(a).name != "installer.py":
            continue
        candidato = Path(a) if Path(a).is_absolute() else (cwd / a if cwd else None)
        try:
            if candidato is not None and candidato.resolve() == nostro:
                return True
        except OSError:
            continue
    return False


def _libera_porta() -> None:
    """Se sulla porta c'è un NOSTRO installer di un run precedente, lo fa uscire.

    Il caso (23/08, primo collaudo su macchina vergine): il run 1 resta vivo col
    suo terminale, il run 2 muore sul bind PRIMA del webbrowser.open — per l'utente
    «non apre più il browser», senza una riga che dica perché. Tre passi:
      ① /__ping: se risponde la nostra firma → POST /__quit e attesa che esca;
      ② (solo Linux) un predecessore VECCHIO senza /__quit: si cerca in /proc il
         processo `installer.py` che non siamo noi e gli si manda SIGTERM;
      ③ se la porta resta occupata, main() stampa il rimedio invece del traceback.
    """
    import urllib.request
    base = f"http://{HOST}:{PORT}"
    try:
        with urllib.request.urlopen(base + "/__ping", timeout=2) as r:
            firma = json.loads(r.read().decode())
        if firma.get("vps1777_installer"):
            print(f"  ↻ un installer precedente è vivo (pid {firma.get('pid')}): lo riavvio")
            try:
                urllib.request.urlopen(urllib.request.Request(
                    base + "/__quit", method="POST"), timeout=2).read()
            except OSError:
                pass
            time.sleep(1.0)
            return
    except Exception:
        pass  # niente ping: o porta libera, o un predecessore vecchio → ②
    proc = Path("/proc")
    if proc.is_dir():
        for p in proc.iterdir():
            if not p.name.isdigit() or int(p.name) == os.getpid():
                continue
            try:
                cmd = (p / "cmdline").read_bytes().decode(errors="replace")
            except OSError:
                continue
            if _e_un_nostro_installer(cmd, p):
                print(f"  ↻ installer precedente (pid {p.name}, senza /__quit): SIGTERM")
                try:
                    os.kill(int(p.name), 15)
                except OSError:
                    pass
                time.sleep(1.0)


def main():
    try:
        srv = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError:
        _libera_porta()
        try:
            srv = ThreadingHTTPServer((HOST, PORT), Handler)
        except OSError:
            print(f"\n  ✗ la porta {PORT} resta occupata e chi la tiene non è un nostro"
                  f"\n    installer. Rimedi: chiudi quel processo, oppure rilancia con"
                  f"\n    VPS1777_INSTALLER_PORT=8778 (o un'altra porta libera).\n")
            raise SystemExit(1)
    url = f"http://{HOST}:{PORT}"
    print(f"\n  vps1777 installer → {url}")
    if not _PARAMIKO:
        print("  ⚠ paramiko non trovato — installalo: pip install paramiko")
    if _ERRORE_MOTORE:
        print(f"  ⚠ il motore dell'installer non si è caricato: {_ERRORE_MOTORE}")
    print("  (Ctrl+C per uscire)\n")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  Chiuso.\n")
        srv.shutdown()


if __name__ == "__main__":
    main()
