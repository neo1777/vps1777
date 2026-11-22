"""Gli installatori (deploy.sh, setup.sh, installer/) dopo la rilettura col catalogo di requisiti.

Due rilievi di sicurezza veri, più i loro vicini:
  H97 — i valori che `deploy.sh --apply` legge da `pending.json` (lo scrive un servizio
        esposto) erano controllati con `echo | grep`, che un a-capo aggira, e l'URL pubblico
        ammetteva qualunque carattere dopo la prima «/»: finivano nel testo di uno script
        eseguito sulla VPS.
  H98 — l'installer locale rispondeva a qualunque pagina web (niente controllo di Host e
        Origin): avviare o chiudere un'installazione, e con un DNS che cambia indirizzo
        leggere il risultato, password admin compresa.
`paramiko` è finto come negli altri test dell'installer: in CI non c'è.
"""
from __future__ import annotations

import http.client
import importlib.util
import os
import re
import socket
import subprocess
import sys
import threading
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = (ROOT / "deploy.sh").read_text(encoding="utf-8")

sys.modules.setdefault("paramiko", types.ModuleType("paramiko"))


def _carica(nome: str, file: Path):
    spec = importlib.util.spec_from_file_location(nome, file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


eng = _carica("installer_engine_a08", ROOT / "installer" / "engine.py")


# Finto, e costruito per pezzi: il gate anti-leak non deve vedere la forma di un token vero.
TOKEN_FINTO = "123456" + ":" + "x" * 35


# ── H97: la forma dei valori che entrano in uno script remoto ──────────────────

def _blocco_forma() -> str:
    i = DEPLOY.index("RE_EMAIL=")
    j = DEPLOY.index("# set_kv remoto:")
    return DEPLOY[i:j]


def _forma_valida(valore: str, regex: str) -> bool:
    script = _blocco_forma() + f'\nforma_valida "$1" "${regex}"\n'
    return subprocess.run(["bash", "-c", script, "_", valore], check=False).returncode == 0


@pytest.mark.parametrize("valore,regex", [
    ("tskey-auth-abc123-DEF", "RE_TS_KEY"),
    (TOKEN_FINTO, "RE_TG_TOKEN"),
    ("https://vps.example.invalid", "RE_URL_HTTPS"),
    ("https://vps.example.invalid:8443/base/", "RE_URL_HTTPS"),
    ("", "RE_URL_HTTPS"),
    ("nome@example.invalid", "RE_EMAIL"),
    ("vps1777", "RE_NOME_HOST"),
])
def test_i_valori_in_regola_passano(valore: str, regex: str) -> None:
    assert _forma_valida(valore, regex)


@pytest.mark.parametrize("valore,regex", [
    ("tskey-buona\n'; touch /tmp/x; '", "RE_TS_KEY"),            # l'a-capo che grep lasciava passare
    (TOKEN_FINTO + "\n$(id)", "RE_TG_TOKEN"),
    ("https://vps.example.invalid/'; touch /tmp/x; '", "RE_URL_HTTPS"),   # l'apice dopo la «/»
    ("https://vps.example.invalid/a b", "RE_URL_HTTPS"),
    ("https://vps.example.invalid/$(id)", "RE_URL_HTTPS"),
    ("http://vps.example.invalid", "RE_URL_HTTPS"),
    ("nome@example.invalid\"; id; \"", "RE_EMAIL"),
    ("host;id", "RE_NOME_HOST"),
    ("12 34", "RE_NUMERO"),
])
def test_i_valori_che_porterebbero_un_comando_sono_rifiutati(valore: str, regex: str) -> None:
    assert not _forma_valida(valore, regex)


def test_pending_json_non_si_valida_piu_riga_per_riga() -> None:
    apply = DEPLOY[DEPLOY.index('if [ "$APPLY_MODE" = "1" ]; then'):DEPLOY.index("# ═══════════════════════════════════════════ 2. CONFIG")]
    assert not re.search(r'echo "\$(TS_KEY|TG_TOKEN|TG_OWNER|PUB)"\s*\|\s*grep', apply), \
        "un valore di pending.json è ancora validato con echo|grep: un a-capo lo aggira (H97)"
    for nome in ("TS_KEY", "TG_TOKEN", "TG_OWNER", "PUB"):
        assert f'forma_valida "${nome}"' in apply, f"{nome} non passa da forma_valida"


def test_nessun_valore_variabile_entra_in_un_sed_remoto() -> None:
    assert "PUBLIC_BASE=$PUB|" not in DEPLOY and "PUBLIC_BASE=$TS_URL|" not in DEPLOY
    assert "--hostname=${TS_HOSTNAME" not in DEPLOY, "il nome host va fra apici e validato"


def test_set_kv_remoto_e_atomico_e_lascia_il_file_a_600(tmp_path: Path) -> None:
    casa = tmp_path / "vps1777"
    casa.mkdir()
    (casa / ".env").write_text("A=1\nB=2\n", encoding="utf-8")
    i = DEPLOY.index("SET_KV_REMOTO=$(cat <<'RS'\n") + len("SET_KV_REMOTO=$(cat <<'RS'\n")
    j = DEPLOY.index("\nRS\n", i)
    script = DEPLOY[i:j] + "\nset_kv B 'due parole'\nset_kv C 3\n"
    r = subprocess.run(["bash", "-c", script], env={**os.environ, "HOME": str(tmp_path)}, check=False,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert (casa / ".env").read_text("utf-8").splitlines() == ["A=1", "B=due parole", "C=3"]
    assert oct((casa / ".env").stat().st_mode & 0o777) == "0o600"
    assert not (casa / ".env.tmp").exists()


# ── il Funnel si conferma da fuori in TUTTI e tre i percorsi ───────────────────

def test_il_percorso_principale_di_deploy_conferma_il_funnel_da_fuori() -> None:
    definizione = DEPLOY.index("funnel_confermato_da_qui() {")
    apply = DEPLOY.index('if [ "$APPLY_MODE" = "1" ]; then')
    assert definizione < apply, "la funzione deve esistere anche fuori dal ramo --apply"
    principale = DEPLOY[DEPLOY.index("# ═══════════════════════════════════════════ 2. CONFIG"):]
    assert 'funnel_confermato_da_qui "$TS_URL"' in principale
    assert 'ok "Funnel HTTPS attivo: $TS_URL"' not in DEPLOY, "il verde senza conferma è tornato"
    assert "set_kv GATEWAY_BIND 0.0.0.0" in principale, "senza fallback il rosso lascia l'utente fuori"


# ── engine.py ──────────────────────────────────────────────────────────────────

def test_una_chiave_age_esistente_non_viene_mai_sovrascritta(tmp_path: Path, monkeypatch) -> None:
    cartella = tmp_path / "vps1777"
    cartella.mkdir()
    chiave = cartella / "age-key.txt"
    chiave.write_text("AGE-SECRET-KEY-1FINTAFINTAFINTA\n", encoding="utf-8")   # niente riga «# public key:»
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("PATH", str(tmp_path))           # nessun age-keygen
    with pytest.raises(eng.DeployError):
        eng.age_ensure_keypair_on_pc()
    assert chiave.read_text("utf-8") == "AGE-SECRET-KEY-1FINTAFINTAFINTA\n", "la chiave dei backup è stata toccata"


def test_l_ingresso_fuori_elenco_e_un_errore_non_tailscale() -> None:
    assert eng.ingresso_da("") == "tailscale" and eng.ingresso_da("3") == "cloudflared"
    with pytest.raises(eng.DeployError):
        eng.ingresso_da("9")


class _Canale:
    """Un canale SSH finto: non ha mai dati e non finisce mai (o solleva ciò che gli si dice)."""

    def __init__(self, errore: Exception | None = None):
        self.errore = errore
        self.chiuso = False

    def set_combine_stderr(self, _v): pass
    def exec_command(self, _c): pass
    def settimeout(self, _t): pass
    def exit_status_ready(self): return False
    def close(self): self.chiuso = True

    def recv(self, _n):
        raise self.errore or socket.timeout()


class _Trasporto:
    def __init__(self, canale): self.canale = canale
    def open_session(self): return self.canale


class _Client:
    def __init__(self, canale): self.canale = canale
    def get_transport(self): return _Trasporto(self.canale)


def test_un_comando_remoto_che_non_finisce_viene_fermato(monkeypatch) -> None:
    monkeypatch.setattr(eng, "CMD_TIMEOUT_S", 0)
    d = eng.Deployer("192.0.2.10", "root", "")
    canale = _Canale()
    d.client = _Client(canale)
    with pytest.raises(eng.DeployError, match="non ha concluso"):
        list(d._stream("sleep infinity", "prova"))
    assert canale.chiuso


def test_un_errore_vero_del_canale_non_viene_inghiottito() -> None:
    d = eng.Deployer("192.0.2.10", "root", "")
    d.client = _Client(_Canale(OSError("connessione caduta")))
    with pytest.raises(OSError):
        list(d._stream("true"))


def test_senza_connessione_l_errore_si_legge() -> None:
    d = eng.Deployer("192.0.2.10", "root", "")
    with pytest.raises(eng.DeployError, match="connessione SSH non aperta"):
        d._run_capture("true")


class _Sftp:
    def __init__(self): self.chiuso = False
    def open(self, *_a):
        import io
        class F(io.BytesIO):
            def __exit__(s, *a): return False
        return F()
    def close(self): self.chiuso = True


def test_il_pacchetto_arrivato_si_rilegge_prima_di_estrarlo(monkeypatch) -> None:
    monkeypatch.setattr(eng, "_make_repo_tar", lambda: b"contenuto del pacchetto")
    sftp = _Sftp()

    class C:
        def open_sftp(self): return sftp

    class D(eng.Deployer):
        def _run_capture(self, cmd: str) -> str:
            return "0" * 64            # un'impronta che non è quella del pacchetto

    d = D("192.0.2.10", "root", "")
    d.client = C()
    with pytest.raises(eng.DeployError, match="non è quello partito"):
        list(d.step_upload())
    assert sftp.chiuso


def test_il_fallback_dice_se_non_e_riuscito() -> None:
    class D(eng.Deployer):
        def _sudo(self, inner): return inner
        def _compose_cmd(self, *a, **k): return "docker compose"
        def _run_capture(self, cmd): return "127.0.0.1\n"       # .env riletto: il valore NON è cambiato

    righe = list(D("192.0.2.10", "root", "")._apri_fallback("tailscale"))
    assert any("NON sono riuscito" in r for r in righe), righe


# ── H98: la pagina locale risponde solo a se stessa ────────────────────────────

@pytest.fixture()
def installer(monkeypatch):
    mod = _carica("installer_a08", ROOT / "installer" / "installer.py")
    srv = mod.ThreadingHTTPServer(("127.0.0.1", 0), mod.Handler)
    porta = srv.server_address[1]
    monkeypatch.setattr(mod, "PORT", porta)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield mod, porta
    srv.shutdown()
    srv.server_close()


def _chiedi(porta: int, metodo: str, percorso: str, intestazioni: dict[str, str]) -> int:
    c = http.client.HTTPConnection("127.0.0.1", porta, timeout=5)
    c.putrequest(metodo, percorso, skip_host=True)
    for k, v in intestazioni.items():
        c.putheader(k, v)
    if metodo == "POST":
        c.putheader("Content-Length", "2")
    c.endheaders(b"{}" if metodo == "POST" else None)
    stato = c.getresponse().status
    c.close()
    return stato


def test_la_pagina_risponde_a_se_stessa(installer) -> None:
    _mod, porta = installer
    assert _chiedi(porta, "GET", "/api/status", {"Host": f"127.0.0.1:{porta}"}) == 200
    assert _chiedi(porta, "GET", "/api/status", {"Host": f"localhost:{porta}",
                                                 "Origin": f"http://localhost:{porta}"}) == 200


def test_un_nome_che_non_e_il_nostro_non_legge_niente(installer) -> None:
    """DNS rebinding: il browser crede di parlare con un altro sito, e lo scrive in Host."""
    _mod, porta = installer
    assert _chiedi(porta, "GET", "/api/stream", {"Host": f"sito.example.invalid:{porta}"}) == 403
    assert _chiedi(porta, "GET", "/api/status", {}) == 403


def test_un_altro_sito_non_puo_avviare_ne_chiudere_l_installazione(installer) -> None:
    mod, porta = installer
    intest = {"Host": f"127.0.0.1:{porta}", "Origin": "https://sito.example.invalid"}
    assert _chiedi(porta, "POST", "/__quit", intest) == 403
    assert _chiedi(porta, "POST", "/api/deploy", intest) == 403
    assert mod.DEPLOY["running"] is False
    assert _chiedi(porta, "GET", "/api/status", {"Host": f"127.0.0.1:{porta}"}) == 200, "il server è stato chiuso"


def test_un_motore_che_finisce_senza_esito_non_e_un_successo(installer) -> None:
    mod, _porta = installer
    mod.DEPLOY.update(running=True, done=False, exit=None, lines=[])
    mod.engine = types.SimpleNamespace(run=lambda _p: iter(["una riga", "un'altra"]))
    mod._run_deploy({})
    assert mod.DEPLOY["exit"] == 1 and mod.DEPLOY["done"] is True
    assert "__EXIT__1" in mod.DEPLOY["lines"]


def test_il_sigterm_va_solo_a_un_nostro_installer(installer, tmp_path: Path) -> None:
    mod, _porta = installer
    nostro = str((ROOT / "installer" / "installer.py").resolve())
    proc = tmp_path / "4242"
    proc.mkdir()
    (proc / "cwd").symlink_to(ROOT / "installer")
    assert mod._e_un_nostro_installer(f"/usr/bin/python3\0{nostro}\0", proc)
    assert mod._e_un_nostro_installer("python3\0installer.py\0", proc)
    assert not mod._e_un_nostro_installer(f"/usr/bin/vim\0{nostro}\0", proc), "un editor non è un installer"
    assert not mod._e_un_nostro_installer("python3\0/opt/altro/installer.py\0", proc)
    assert not mod._e_un_nostro_installer("bash\0-c\0echo installer.py\0", proc)


def test_il_corpo_di_una_richiesta_ha_un_tetto(installer) -> None:
    mod, _porta = installer
    finto = types.SimpleNamespace(headers={"Content-Length": str(mod.CORPO_MAX_BYTE + 1)}, rfile=None)
    assert mod.Handler._read_json(finto) == {}
    import io
    finto = types.SimpleNamespace(headers={"Content-Length": "7"}, rfile=io.BytesIO(b"[1,2,3]"))
    assert mod.Handler._read_json(finto) == {}, "un JSON che non è un oggetto non è una richiesta"
