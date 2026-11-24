"""Un nb1777-mcp FINTO per le schermate: risponde a ciò che la Mini App e il pannello chiedono, con dati inventati."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

NOTEBOOK = [
    {"id": "nb-001", "title": "Viaggio in Giappone, aprile", "source_count": 12, "updated_at": "2026-11-20T09:12:00Z"},
    {"id": "nb-002", "title": "Pompe di calore: preventivi a confronto", "source_count": 7, "updated_at": "2026-11-18T17:40:00Z"},
    {"id": "nb-003", "title": "Corso di fotografia, appunti", "source_count": 23, "updated_at": "2026-11-15T21:05:00Z"},
    {"id": "nb-004", "title": "Manuali di casa (lavatrice, caldaia, router)", "source_count": 5, "updated_at": "2026-11-02T08:30:00Z"},
    {"id": "nb-005", "title": "Letture: storia della tipografia", "source_count": 9, "updated_at": "2026-10-28T19:22:00Z"},
]


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, corpo, codice=200):
        b = json.dumps(corpo).encode()
        self.send_response(codice)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/internal/nlm/status"):
            return self._json({"ok": True, "has_cookies": True, "pending": False})
        if self.path.startswith("/internal/nlm/artifacts"):
            return self._json({"artifacts": []})
        if self.path.startswith("/internal/notifications"):
            return self._json({"items": []})
        if self.path.startswith("/health"):
            return self._json({"status": "ok"})
        self._json({}, 404)

    def do_POST(self):
        n = int(self.headers.get("content-length", "0") or 0)
        try:
            rpc = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            rpc = {}
        nome = (rpc.get("params") or {}).get("name", "")
        print("tool:", nome, (rpc.get("params") or {}).get("arguments"), flush=True)
        if nome == "nb_list":
            testo = json.dumps(NOTEBOOK)
        elif nome == "usage_get":
            testo = json.dumps({"windows": [{"window": "rolling", "percent_used": 4, "percent_remaining": 96},
                                            {"window": "weekly", "percent_used": 11, "percent_remaining": 89}]})
        else:
            testo = json.dumps([])
        self._json({"jsonrpc": "2.0", "id": rpc.get("id", 1), "result": {"content": [{"type": "text", "text": testo}]}})


ThreadingHTTPServer(("127.0.0.1", 18003), H).serve_forever()
