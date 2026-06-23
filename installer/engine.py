"""
engine.py — motore di deploy cross-OS via SSH (paramiko).

Esegue gli stessi step di deploy.sh ma **direttamente sulla VPS via SSH**,
orchestrati da Python. Il PC esegue solo Python: niente bash, niente sshpass.
Gira identico su Windows / Mac / Linux.

La VPS è Linux e riceve comandi shell standard; l'upload del repo avviene
via SFTP (tar in memoria).

Usato da installer.py. Richiede paramiko.
"""
from __future__ import annotations

import io
import json
import shlex
import tarfile
import time
from pathlib import Path
from typing import Iterator

import paramiko

REPO = Path(__file__).resolve().parent.parent
COMPOSE_VERSION = "v2.32.4"
OPERATOR_USER = "vps1777"
REMOTE_DIR = f"/home/{OPERATOR_USER}/vps1777"

# Cartelle/file da NON includere nel tar caricato sulla VPS
TAR_EXCLUDE = {
    ".git", "__pycache__", ".venv", "node_modules", "backups",
    "onboarding", ".pytest_cache", ".ruff_cache", ".mypy_cache",
}


def _excluded(name: str) -> bool:
    parts = Path(name).parts
    if any(p in TAR_EXCLUDE for p in parts):
        return True
    if name.endswith((".pyc", ".pyo")):
        return True
    # secret in chiaro: non li carichiamo (vengono generati sulla VPS)
    if "secrets" in parts and name.endswith(".txt"):
        return True
    return False


def _make_repo_tar() -> bytes:
    """Crea in memoria un tar.gz del repo, escludendo ciò che non serve."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path in sorted(REPO.rglob("*")):
            rel = path.relative_to(REPO).as_posix()
            if _excluded(rel):
                continue
            if path.is_file() or path.is_dir():
                tar.add(str(path), arcname=rel, recursive=False)
    return buf.getvalue()


class DeployError(Exception):
    pass


class Deployer:
    """Connessione SSH + step di deploy con output streaming."""

    def __init__(self, ip: str, user: str, password: str):
        self.ip = ip
        self.user = user
        self.password = password
        self.client: paramiko.SSHClient | None = None
        self.result: dict[str, str] = {}
        self.production = False

    # ───── connessione ─────

    def connect(self) -> None:
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kwargs: dict = dict(hostname=self.ip, username=self.user, timeout=20,
                            allow_agent=True, look_for_keys=True)
        if self.password:
            kwargs["password"] = self.password
            kwargs["look_for_keys"] = False
            kwargs["allow_agent"] = False
        c.connect(**kwargs)
        self.client = c

    def close(self) -> None:
        if self.client:
            self.client.close()

    def detect_os(self) -> str:
        out = self._run_capture(". /etc/os-release 2>/dev/null; echo \"$PRETTY_NAME ($(uname -m))\"")
        return out.strip()

    # ───── exec helpers ─────

    def _run_capture(self, cmd: str) -> str:
        assert self.client
        _in, out, err = self.client.exec_command(cmd, timeout=60)
        rc = out.channel.recv_exit_status()
        data = out.read().decode("utf-8", "replace")
        if rc != 0:
            data += err.read().decode("utf-8", "replace")
        return data

    def _stream(self, cmd: str, label: str = "") -> Iterator[str]:
        """
        Esegue cmd via SSH, yield righe appena arrivano (lettura a chunk,
        non bufferizzata per riga → output più reattivo attraverso WSL2).
        """
        assert self.client
        chan = self.client.get_transport().open_session()  # type: ignore[union-attr]
        chan.get_pty()
        chan.set_combine_stderr(True)
        chan.settimeout(0.0)  # non-bloccante
        chan.exec_command(cmd)
        buf = b""
        while True:
            got = False
            try:
                data = chan.recv(8192)
                if data:
                    got = True
                    buf += data
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        yield line.decode("utf-8", "replace").rstrip("\r")
            except Exception:
                pass
            if chan.exit_status_ready() and not got:
                # svuota il resto
                try:
                    while True:
                        data = chan.recv(8192)
                        if not data:
                            break
                        buf += data
                except Exception:
                    pass
                if buf:
                    for ln in buf.decode("utf-8", "replace").splitlines():
                        yield ln.rstrip("\r")
                break
            if not got:
                time.sleep(0.08)
        rc = chan.recv_exit_status()
        if rc != 0:
            raise DeployError(f"{label or 'comando'} fallito (exit {rc})")

    def _sudo(self, inner: str) -> str:
        """Esegue come operator (o diretto se siamo già root via sudo)."""
        return f"sudo -u {OPERATOR_USER} bash -lc {shlex.quote(inner)}"

    # ───── step ─────

    def step_prepare(self) -> Iterator[str]:
        yield "── Installo Docker + Compose v2 + utente operatore…"
        script = f"""
set -e
export DEBIAN_FRONTEND=noninteractive
NEED=""
command -v docker >/dev/null 2>&1 || NEED="$NEED docker.io"
command -v git    >/dev/null 2>&1 || NEED="$NEED git"
command -v curl   >/dev/null 2>&1 || NEED="$NEED curl"
command -v age    >/dev/null 2>&1 || NEED="$NEED age"
command -v python3 >/dev/null 2>&1 || NEED="$NEED python3"
python3 -c "import bcrypt" 2>/dev/null || NEED="$NEED python3-bcrypt"
if [ -n "$NEED" ]; then apt-get update -q && apt-get install -y -q $NEED ca-certificates; fi
systemctl enable --now docker
if ! docker compose version >/dev/null 2>&1; then
  case "$(uname -m)" in x86_64) A=x86_64;; aarch64|arm64) A=aarch64;; *) A=x86_64;; esac
  mkdir -p /usr/local/lib/docker/cli-plugins
  curl -fsSL "https://github.com/docker/compose/releases/download/{COMPOSE_VERSION}/docker-compose-linux-$A" \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
  chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
fi
id {OPERATOR_USER} >/dev/null 2>&1 || useradd -m -s /bin/bash {OPERATOR_USER}
usermod -aG docker {OPERATOR_USER}
getent group sudo >/dev/null && usermod -aG sudo {OPERATOR_USER} || true
echo "{OPERATOR_USER} ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/90-{OPERATOR_USER}
chmod 0440 /etc/sudoers.d/90-{OPERATOR_USER}
docker compose version >/dev/null 2>&1 && echo "COMPOSE_OK" || echo "COMPOSE_MISSING"
"""
        ok = False
        for line in self._stream(script, "prepare"):
            if "COMPOSE_OK" in line:
                ok = True
            yield line
        if not ok:
            raise DeployError("docker compose v2 non disponibile dopo l'install del plugin")
        yield "✓ Docker + Compose + utente pronti"

    def step_upload(self) -> Iterator[str]:
        assert self.client
        yield "── Trasferisco il repo (SFTP)…"
        data = _make_repo_tar()
        sftp = self.client.open_sftp()
        with sftp.open("/tmp/vps1777.tar.gz", "wb") as f:
            f.write(data)
        sftp.close()
        yield f"  caricati {len(data)//1024} KB"
        mv = f"""
set -e
install -d -o {OPERATOR_USER} -g {OPERATOR_USER} {REMOTE_DIR}
tar -xzf /tmp/vps1777.tar.gz -C {REMOTE_DIR}
chown -R {OPERATOR_USER}:{OPERATOR_USER} {REMOTE_DIR}
rm -f /tmp/vps1777.tar.gz
"""
        for line in self._stream(mv, "upload"):
            yield line
        yield "✓ Repo in posizione"

    def step_config(self, p: dict) -> Iterator[str]:
        yield "── Genero .env + secrets…"
        ingress = {"1": "tailscale", "2": "caddy", "3": "cloudflared"}.get(p.get("ingress_num", "1"), "tailscale")
        public_base = p.get("public_base", "")
        if ingress == "caddy" and p.get("caddy_domain"):
            public_base = f"https://{p['caddy_domain']}"
        # script remoto eseguito come operator
        gen = f"""
set -e
cd {REMOTE_DIR}
mkdir -p secrets
gen() {{ python3 -c "import secrets;print(secrets.token_urlsafe($1))"; }}
genpwd() {{ python3 -c "import secrets,string;print(''.join(secrets.choice(string.ascii_letters+string.digits) for _ in range(24)))"; }}
[ -s secrets/gateway_secret.txt ]       || gen 24 > secrets/gateway_secret.txt
[ -s secrets/oauth_signing_secret.txt ] || gen 48 > secrets/oauth_signing_secret.txt
chmod 600 secrets/gateway_secret.txt secrets/oauth_signing_secret.txt
if [ ! -s secrets/admin_password_bcrypt.txt ]; then
  PW="$(genpwd)"; echo "GENERATED_ADMIN_PWD=$PW"
  python3 -c "import bcrypt,sys;print(bcrypt.hashpw(sys.argv[1].encode(),bcrypt.gensalt(12)).decode())" "$PW" > secrets/admin_password_bcrypt.txt
  chmod 600 secrets/admin_password_bcrypt.txt
fi
printf %s {shlex.quote(p.get('telegram_bot_token', ''))} > secrets/telegram_bot_token.txt; chmod 600 secrets/telegram_bot_token.txt
{("printf %s " + shlex.quote(p.get('cf_token',''))) + " > secrets/cloudflared_token.txt; chmod 600 secrets/cloudflared_token.txt" if p.get('cf_token') else "true"}
cp -n .env.example .env 2>/dev/null || true
set_kv() {{ grep -q "^$1=" .env && sed -i "s|^$1=.*|$1=$2|" .env || echo "$1=$2" >> .env; }}
set_kv ADMIN_EMAIL {shlex.quote(p.get('admin_email',''))}
set_kv TELEGRAM_OWNER_ID {shlex.quote(p.get('telegram_owner_id',''))}
set_kv PUBLIC_BASE {shlex.quote(public_base)}
set_kv INGRESS_PROFILE ingress.{ingress}
set_kv TS_HOSTNAME {shlex.quote(p.get('ts_hostname','vps1777'))}
set_kv TS_AUTHKEY {shlex.quote(p.get('ts_authkey',''))}
set_kv CADDY_DOMAIN {shlex.quote(p.get('caddy_domain',''))}
set_kv CADDY_EMAIL {shlex.quote(p.get('caddy_email',''))}
echo CONFIG_OK
"""
        for line in self._stream(self._sudo(gen), "config"):
            if line.startswith("GENERATED_ADMIN_PWD="):
                self.result["ADMIN_PWD"] = line.split("=", 1)[1].strip()
                yield "  password admin generata (mostrata alla fine)"
            elif "CONFIG_OK" in line:
                pass
            else:
                yield line
        self.result["INGRESS"] = ingress
        self.result["ADMIN_EMAIL"] = p.get("admin_email", "")
        yield "✓ .env + secrets pronti"

    def _compose_cmd(self, ingress: str, onboarding: bool = True) -> str:
        files = f"-f compose.yaml -f compose.ingress.{ingress}.yaml"
        if onboarding:
            files += " -f compose.onboarding.yaml"
        return f"docker compose {files} --profile ingress.{ingress}"

    def step_build(self, ingress: str) -> Iterator[str]:
        yield "── Build immagini + avvio (può richiedere alcuni minuti)…"
        cmd = self._compose_cmd(ingress, onboarding=True)
        for line in self._stream(self._sudo(f"cd {REMOTE_DIR} && {cmd} up -d --build"), "build"):
            yield line
        yield "✓ Stack avviato"

    def step_tailscale_url(self, p: dict, ingress: str) -> Iterator[str]:
        # production: True se possiamo chiudere la porta 8080 (Funnel HTTPS ok)
        self.production = False
        if ingress != "tailscale" or not p.get("ts_authkey"):
            return
        yield "── Attendo login Tailscale + Funnel…"
        # il sidecar (containerboot) fa up + serve config; diamo tempo
        url = ""
        for _ in range(12):
            time.sleep(5)
            url = self._run_capture(
                "docker exec vps1777-tailscale tailscale status --json 2>/dev/null | "
                "python3 -c \"import sys,json;d=json.load(sys.stdin);print('https://'+d.get('Self',{}).get('DNSName','').rstrip('.'))\" 2>/dev/null"
            ).strip()
            if url.endswith(".ts.net"):
                break
            yield "  ."
        if not url.endswith(".ts.net"):
            yield "! URL Tailscale non ricavato — controlla la key e l'account. Lascio la porta 8080 aperta come fallback."
            return
        self.result["URL"] = url
        # imposta PUBLIC_BASE e riavvia gateway
        cmd = self._compose_cmd(ingress, onboarding=True)
        self._run_capture(self._sudo(
            f"cd {REMOTE_DIR} && (grep -q ^PUBLIC_BASE= .env && sed -i 's|^PUBLIC_BASE=.*|PUBLIC_BASE={url}|' .env || echo PUBLIC_BASE={url} >> .env) && {cmd} up -d gateway"
        ))
        yield f"✓ URL pubblico: {url}"
        # verifica Funnel attivo su :443
        fstat = self._run_capture("docker exec vps1777-tailscale tailscale funnel status 2>/dev/null || true")
        if ":443" in fstat or "https" in fstat.lower():
            self.production = True
            yield "✓ Funnel HTTPS attivo su :443"
        else:
            yield "! Funnel non ancora confermato — verifica che sia abilitato nell'account Tailscale (Access Controls → nodeAttrs funnel)."

    def step_finalize(self, ingress: str) -> Iterator[str]:
        """Se production (Funnel ok), riavvia SENZA onboarding → chiude :8080."""
        if not getattr(self, "production", False):
            yield "── Lascio la porta 8080 aperta (pannello setup raggiungibile via IP)"
            return
        yield "── Modalità production: chiudo la porta 8080 (solo HTTPS via Funnel)…"
        cmd = self._compose_cmd(ingress, onboarding=False)
        # --force-recreate sul gateway per applicare la rimozione del port mapping
        for line in self._stream(self._sudo(f"cd {REMOTE_DIR} && {cmd} up -d --force-recreate gateway"), "finalize"):
            yield line
        yield "✓ Porta 8080 chiusa — raggiungibile solo via HTTPS"

    def step_reboot(self, ingress: str) -> Iterator[str]:
        production = getattr(self, "production", False)
        yield "── Riavvio la VPS (test auto-start)…"
        try:
            self._run_capture("nohup reboot >/dev/null 2>&1 &")
        except Exception:
            pass
        self.close()
        time.sleep(8)
        yield "  attendo che la VPS torni online…"
        back = False
        for _ in range(30):
            time.sleep(5)
            try:
                self.connect()
                self._run_capture("echo up")
                back = True
                break
            except Exception:
                yield "  ."
        if not back:
            yield "! VPS non ancora raggiungibile — controlla manualmente"
            return
        yield "✓ VPS tornata online, attendo i container…"
        time.sleep(15)
        cmd = self._compose_cmd(ingress, onboarding=not production)
        ps = self._run_capture(self._sudo(f"cd {REMOTE_DIR} && {cmd} ps"))
        for line in ps.splitlines():
            yield line
        # verifica finale HTTPS se production
        if production:
            url = self.result.get("URL", "")
            yield "── Verifico HTTPS pubblico…"
            time.sleep(8)
            health = self._run_capture(
                f"docker exec vps1777-tailscale sh -c 'wget -qO- --no-check-certificate {url}/health 2>/dev/null' || true"
            )
            if '"ok"' in health or "ok" in health.lower():
                yield f"✓ HTTPS pubblico risponde: {url}/health"
                self.result["HTTPS_OK"] = "1"
            else:
                yield "! HTTPS non ancora confermato (può richiedere 1-2 min per il cert). Riprova: " + url + "/health"

    def collect_result(self) -> Iterator[str]:
        sec = self._run_capture(self._sudo(f"cat {REMOTE_DIR}/secrets/gateway_secret.txt")).strip()
        self.result["SECRET"] = sec
        url = self.result.get("URL", "") or f"http://{self.ip}:8080"
        self.result.setdefault("URL", url)
        self.result["SETUP_URL"] = f"{url}/admin/setup"
        # emetti RESULT_* per la UI
        for k, v in self.result.items():
            yield f"RESULT_{k}={v}"


def run(params: dict) -> Iterator[str]:
    """Generator completo: esegue tutti gli step, yield righe di log."""
    d = Deployer(params.get("ip", ""), params.get("user", "root") or "root",
                 params.get("password", ""))
    ingress = {"1": "tailscale", "2": "caddy", "3": "cloudflared"}.get(params.get("ingress_num", "1"), "tailscale")
    try:
        yield "▶ Connessione alla VPS…"
        d.connect()
        yield f"✓ Connesso: {d.detect_os()}"
        yield "═ STEP 1/6 — Preparazione VPS"
        yield from d.step_prepare()
        yield "═ STEP 2/6 — Trasferimento repo"
        yield from d.step_upload()
        yield "═ STEP 3/6 — Config + secrets"
        yield from d.step_config(params)
        yield "═ STEP 4/6 — Build + avvio"
        yield from d.step_build(ingress)
        yield "═ STEP 5/7 — Tailscale URL + Funnel"
        yield from d.step_tailscale_url(params, ingress)
        yield "═ STEP 6/7 — Finalizzazione (production)"
        yield from d.step_finalize(ingress)
        yield "═ STEP 7/7 — Reboot test + verifica HTTPS"
        yield from d.step_reboot(ingress)
        yield from d.collect_result()
        yield "__EXIT__0"
    except paramiko.AuthenticationException:
        yield "✗ Autenticazione SSH fallita (password/utente errati)"
        yield "__EXIT__1"
    except DeployError as e:
        yield f"✗ {e}"
        yield "__EXIT__1"
    except Exception as e:  # noqa: BLE001
        yield f"✗ Errore: {e}"
        yield "__EXIT__1"
    finally:
        d.close()


def check(ip: str, user: str, password: str) -> dict:
    """Test connessione SSH (per il semaforo VPS)."""
    import re
    if not re.match(r"^\d{1,3}(\.\d{1,3}){3}$", ip):
        return {"ok": False, "error": "IP non valido"}
    d = Deployer(ip, user or "root", password)
    try:
        d.connect()
        os_info = d.detect_os()
        d.close()
        return {"ok": True, "os": os_info}
    except paramiko.AuthenticationException:
        return {"ok": False, "error": "Autenticazione fallita (password/utente errati)"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
