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
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Iterator

import paramiko

REPO = Path(__file__).resolve().parent.parent
COMPOSE_VERSION = "v2.32.4"
OPERATOR_USER = "vps1777"
REMOTE_DIR = f"/home/{OPERATOR_USER}/vps1777"

# Tag usato per il nodo VPS nel tailnet. Deve combaciare col tag assegnato
# all'OAuth client in fase di creazione (vedi checklist nella UI). Il nodeAttr
# "funnel" viene concesso a questo tag nell'ACL → il Funnel HTTPS si attiva.
TS_TAG = "tag:vps1777"
TS_API = "https://api.tailscale.com/api/v2"

# Repo GitHub delle release (immagini ghcr + runtime bundle)
GITHUB_REPO = "neo1777/vps1777"


def latest_release_version(prerelease: bool = False) -> str:
    """Ultima release pubblicata (dal PC dell'installer). '' se nessuna.

    L'installer produzione installa SEMPRE una release taggata (modello pull,
    mai build sulla VPS 4GB). prerelease=True serve solo ai test rc.
    """
    try:
        if prerelease:
            url = f"https://api.github.com/repos/{GITHUB_REPO}/releases?per_page=1"
            obj, _ = _http_json(url, headers={"User-Agent": "vps1777-installer"})
            return obj[0]["tag_name"].lstrip("v") if obj else ""
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        obj, _ = _http_json(url, headers={"User-Agent": "vps1777-installer"})
        return str(obj.get("tag_name", "")).lstrip("v")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, KeyError,
            json.JSONDecodeError):
        return ""


# ── Provisioning Tailscale via OAuth client (gira sul PC, non sulla VPS) ────
# Il client-secret OAuth resta in locale: lo usiamo per (1) ottenere un token,
# (2) scrivere il nodeAttr funnel nell'ACL, (3) generare una auth-key taggata
# single-use. Solo quella key viene poi scritta in .env sulla VPS.

def _http_json(url: str, *, token: str = "", data: bytes | None = None,
               headers: dict | None = None, method: str = "GET", timeout: int = 30):
    """Chiamata HTTP JSON minimale (stdlib). Ritorna (obj, etag)."""
    h = {"Accept": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
        etag = r.headers.get("ETag", "")
        obj = json.loads(body) if body.strip() else {}
        return obj, etag


def _httperr(e: Exception) -> str:
    """Estrae un messaggio leggibile da una HTTPError (corpo JSON o testo)."""
    if isinstance(e, urllib.error.HTTPError):
        try:
            detail = e.read().decode("utf-8", "replace")
        except Exception:
            detail = ""
        msg = detail.strip()
        try:
            j = json.loads(detail)
            msg = j.get("message") or j.get("error") or detail
        except Exception:
            pass
        return f"HTTP {e.code}: {msg[:200]}"
    return str(e)


def _ts_oauth_token(client_id: str, client_secret: str) -> str:
    data = urllib.parse.urlencode({"client_id": client_id, "client_secret": client_secret}).encode()
    obj, _ = _http_json(f"{TS_API}/oauth/token", data=data, method="POST",
                        headers={"Content-Type": "application/x-www-form-urlencoded"})
    tok = obj.get("access_token", "")
    if not tok:
        raise RuntimeError("token OAuth assente nella risposta")
    return tok


def _ts_ensure_funnel_attr(policy: dict, tag: str) -> bool:
    """Aggiunge il nodeAttr funnel per `tag` se manca. Ritorna True se modifica."""
    attrs = policy.setdefault("nodeAttrs", [])
    for a in attrs:
        if tag in (a.get("target") or []) and "funnel" in (a.get("attr") or []):
            return False
    attrs.append({"target": [tag], "attr": ["funnel"]})
    # tagOwners: di norma già creato dalla console quando si fa l'OAuth client.
    owners = policy.setdefault("tagOwners", {})
    owners.setdefault(tag, ["autogroup:admin"])
    return True


def _ts_create_authkey(token: str, tag: str) -> str:
    payload = {
        "capabilities": {"devices": {"create": {
            "reusable": False, "ephemeral": False, "preauthorized": True, "tags": [tag],
        }}},
        "expirySeconds": 86400,  # finestra per il primo login (key single-use)
        "description": "vps1777 installer",
    }
    obj, _ = _http_json(f"{TS_API}/tailnet/-/keys", token=token,
                        data=json.dumps(payload).encode(), method="POST",
                        headers={"Content-Type": "application/json"})
    key = obj.get("key", "")
    if not key:
        raise RuntimeError("auth-key assente nella risposta")
    return key

# Cartelle/file da NON includere nel tar caricato sulla VPS
# (var/ e releases/ sono runtime del canale self-update: esistono solo sulla VPS)
TAR_EXCLUDE = {
    ".git", "__pycache__", ".venv", "node_modules", "backups",
    "onboarding", "var", "releases", ".pytest_cache", ".ruff_cache", ".mypy_cache",
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
        # NIENTE pty: con un tty BuildKit/apt producono progress-bar ANSI che
        # si auto-refreshano → fiume di sequenze di escape che intasano la UI.
        # Senza tty l'output è "plain" (una riga per evento), pulito da streammare.
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
        yield "── Installo Docker + Compose v2 + hardening + utente operatore…"
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
dpkg -s unattended-upgrades >/dev/null 2>&1 || NEED="$NEED unattended-upgrades"
dpkg -s fail2ban >/dev/null 2>&1 || NEED="$NEED fail2ban"
if [ -n "$NEED" ]; then apt-get update -q && apt-get install -y -q $NEED ca-certificates; fi
systemctl enable --now docker
# Hardening SICURO (compatibile con auth password: NON tocchiamo sshd_config,
# altrimenti il deploy via password e la riconnessione post-reboot fallirebbero):
#  - unattended-upgrades: patch di sicurezza automatiche
#  - fail2ban: blocca i brute-force SSH (non banna chi si autentica bene)
printf 'APT::Periodic::Update-Package-Lists "1";\\nAPT::Periodic::Unattended-Upgrade "1";\\n' \
  > /etc/apt/apt.conf.d/20auto-upgrades
systemctl enable --now unattended-upgrades 2>/dev/null || true
systemctl enable --now fail2ban 2>/dev/null || true
if ! docker compose version >/dev/null 2>&1; then
  case "$(uname -m)" in x86_64) A=x86_64;; aarch64|arm64) A=aarch64;; *) A=x86_64;; esac
  mkdir -p /usr/local/lib/docker/cli-plugins
  curl -fsSL "https://github.com/docker/compose/releases/download/{COMPOSE_VERSION}/docker-compose-linux-$A" \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
  chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
fi
# uid 1000 = STESSO uid dei container (tutti "app" uid 1000): così i bind-mount
# (onboarding/) e i file di scambio del canale update non hanno mismatch di
# ownership host↔container. Se 1000 è già preso, ripiego sul default.
if ! id {OPERATOR_USER} >/dev/null 2>&1; then
  if getent passwd 1000 >/dev/null; then
    useradd -m -s /bin/bash {OPERATOR_USER}
  else
    useradd -m -u 1000 -s /bin/bash {OPERATOR_USER}
  fi
fi
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
        yield "✓ Docker + Compose + utente pronti (hardening: unattended-upgrades + fail2ban)"

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

    def step_ts_provision(self, p: dict) -> Iterator[str]:
        """OAuth client → nodeAttr funnel in ACL + auth-key taggata single-use.

        Gira dal PC (urllib): il client-secret NON tocca la VPS. Il risultato
        (la auth-key) viene messo in p['ts_authkey'] così che step_config la
        scriva in .env come prima.
        """
        cid = (p.get("ts_oauth_client_id") or "").strip()
        csec = (p.get("ts_oauth_client_secret") or "").strip()
        # retrocompat: se l'utente ha ancora dato una auth-key diretta, la teniamo
        if p.get("ts_authkey"):
            yield "── Tailscale: uso la auth-key fornita (no OAuth provisioning)."
            return
        if not (cid and csec):
            yield "! Tailscale: nessun OAuth client né auth-key — il Funnel non sarà attivo."
            return
        yield "── Tailscale: provisioning via OAuth client (dal PC)…"
        # 1) Token OAuth — FATALE se fallisce (tutto l'ingress Tailscale ne dipende)
        try:
            token = _ts_oauth_token(cid, csec)
            yield "  ✓ token OAuth ottenuto"
        except Exception as e:  # noqa: BLE001
            raise DeployError(
                f"OAuth Tailscale: token fallito ({_httperr(e)}). "
                "Controlla Client ID e Client Secret dell'OAuth client."
            )
        # 2) ACL: nodeAttr funnel per il tag — NON fatale (potrebbe già esserci)
        try:
            policy, etag = _http_json(f"{TS_API}/tailnet/-/acl", token=token)
            if _ts_ensure_funnel_attr(policy, TS_TAG):
                hdrs = {"Content-Type": "application/json"}
                if etag:
                    hdrs["If-Match"] = etag
                _http_json(f"{TS_API}/tailnet/-/acl", token=token,
                           data=json.dumps(policy).encode(), method="POST", headers=hdrs)
                yield f"  ✓ ACL aggiornata: nodeAttr funnel concesso a {TS_TAG}"
            else:
                yield f"  ✓ ACL già a posto (nodeAttr funnel per {TS_TAG})"
        except Exception as e:  # noqa: BLE001
            yield (f"! ACL non aggiornata: {_httperr(e)} — serve lo scope 'policy_file' (write). "
                   "Proseguo: l'attributo potrebbe già esserci.")
        # 3) auth-key taggata — FATALE se fallisce (senza key il nodo non entra)
        try:
            key = _ts_create_authkey(token, TS_TAG)
            p["ts_authkey"] = key
            yield "  ✓ auth-key taggata generata (single-use)"
        except Exception as e:  # noqa: BLE001
            msg = _httperr(e)
            low = msg.lower()
            if "tag" in low and ("not permitted" in low or "invalid" in low):
                # Caso tipico: l'OAuth client non possiede il tag richiesto.
                raise DeployError(
                    f"OAuth Tailscale: l'OAuth client NON è autorizzato al tag {TS_TAG} ({msg}). "
                    f"FIX: nella admin Tailscale (Settings → OAuth clients) ricrea il client e, "
                    f"nello scope 'auth_keys', ASSEGNAGLI il tag {TS_TAG} (selezionandolo dalla "
                    "lista; dev'essere già in tagOwners). Evita di crearne uno nuovo a mano. Poi rilancia."
                )
            raise DeployError(
                f"OAuth Tailscale: creazione auth-key fallita ({msg}). "
                f"Servono lo scope 'auth_keys' e il tag {TS_TAG} assegnato all'OAuth client."
            )

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
# runtime dir create ORA come operatore: se le creasse Docker (bind mount)
# sarebbero root-owned e gateway/CLI non potrebbero scriverci
mkdir -p secrets onboarding var backups releases
chmod 700 var
gen() {{ python3 -c "import secrets;print(secrets.token_urlsafe($1))"; }}
genpwd() {{ python3 -c "import secrets,string;print(''.join(secrets.choice(string.ascii_letters+string.digits) for _ in range(24)))"; }}
# gateway_secret e oauth_signing restano stabili (il primo è negli URL connector):
# non li rigeneriamo se già presenti.
[ -s secrets/gateway_secret.txt ]       || gen 24 > secrets/gateway_secret.txt
[ -s secrets/oauth_signing_secret.txt ] || gen 48 > secrets/oauth_signing_secret.txt
chmod 600 secrets/gateway_secret.txt secrets/oauth_signing_secret.txt
# La password admin è una credenziale per-installazione: la (ri)generiamo SEMPRE
# fresca e la mostriamo alla fine. Dopo il reboot di STEP 7 il gateway rilegge
# il bcrypt aggiornato, quindi la password mostrata è quella valida.
PW="$(genpwd)"; echo "GENERATED_ADMIN_PWD=$PW"
python3 -c "import bcrypt,sys;print(bcrypt.hashpw(sys.argv[1].encode(),bcrypt.gensalt(12)).decode())" "$PW" > secrets/admin_password_bcrypt.txt
chmod 600 secrets/admin_password_bcrypt.txt
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
set_kv VPS1777_TAG {shlex.quote(p.get('_vps1777_version') or 'dev')}
set_kv VPS1777_IMAGE_BASE {shlex.quote(p.get('_image_base') or 'ghcr.io/neo1777')}
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

    def _compose_cmd(self, ingress: str, onboarding: bool = True,
                     build: bool = False) -> str:
        files = f"-f compose.yaml -f compose.ingress.{ingress}.yaml"
        # compose.yaml è pull-only (immagini ghcr): l'overlay di build si
        # aggiunge SOLO nell'escape hatch dev (mai in produzione — VPS 4GB).
        if build:
            files += " -f compose.build.yaml"
        # Per tailscale (host-mode) l'esposizione la gestisce GATEWAY_BIND, non
        # l'override onboarding (che pubblicherebbe una 2ª porta in conflitto).
        if onboarding and ingress != "tailscale":
            files += " -f compose.onboarding.yaml"
        return f"docker compose {files} --profile ingress.{ingress}"

    def step_pull(self, ingress: str, version: str) -> Iterator[str]:
        """Path produzione: pull delle immagini pubblicate (MAI build sulla VPS)."""
        yield f"── Pull immagini v{version} da ghcr + avvio…"
        cmd = self._compose_cmd(ingress, onboarding=True)
        env = "COMPOSE_ANSI=never DOCKER_CLI_HINTS=false"
        for line in self._stream(
                self._sudo(f"cd {REMOTE_DIR} && {env} {cmd} pull && {env} {cmd} up -d"),
                "pull"):
            yield line
        yield "✓ Stack avviato (immagini pullate, niente build in produzione)"

    def step_build(self, ingress: str) -> Iterator[str]:
        """Escape hatch dev (--dev-build) o fallback pre-prima-release."""
        yield "── Build LOCALE immagini + avvio (dev/fallback — non produzione)…"
        cmd = self._compose_cmd(ingress, onboarding=True, build=True)
        # progress plain + niente ANSI: output pulito per lo streaming web
        env = "BUILDKIT_PROGRESS=plain COMPOSE_ANSI=never DOCKER_CLI_HINTS=false"
        for line in self._stream(self._sudo(f"cd {REMOTE_DIR} && {env} {cmd} up -d --build"), "build"):
            yield line
        yield "✓ Stack avviato (build locale)"

    def step_selfupdate_setup(self) -> Iterator[str]:
        """Installa il canale update: CLI vps1777 + unit systemd. Idempotente."""
        yield "── Installo il canale di aggiornamento (CLI + timer)…"
        script = f"""
set -e
install -m 755 {REMOTE_DIR}/tools/vps1777.py /usr/local/bin/vps1777
for u in {REMOTE_DIR}/systemd/vps1777-*; do
  case "$u" in *.service|*.timer|*.path) install -m 644 "$u" /etc/systemd/system/;; esac
done
systemctl daemon-reload
systemctl enable --now vps1777-check-update.timer vps1777-update.path
echo SELFUPDATE_OK
"""
        okf = False
        for line in self._stream(script, "selfupdate-setup"):
            if "SELFUPDATE_OK" in line:
                okf = True
            else:
                yield line
        if not okf:
            raise DeployError("installazione canale update fallita")
        # primo check (come operatore): popola update_status.json per la card admin
        self._run_capture(self._sudo(f"cd {REMOTE_DIR} && /usr/local/bin/vps1777 check || true"))
        yield "✓ Canale update attivo: `vps1777 update` + pulsante admin + check giornaliero"

    # ───── helper Tailscale (gira SULL'HOST, come root via SSH) ─────

    def _ts_node_url(self) -> str:
        """URL https://<host>.ts.net del nodo (vuoto se non ancora loggato)."""
        return self._run_capture(
            "tailscale status --json 2>/dev/null | "
            "python3 -c \"import sys,json;d=json.load(sys.stdin);n=d.get('Self',{}).get('DNSName','').rstrip('.');print('https://'+n if n else '')\" 2>/dev/null"
        ).strip()

    def _ts_funnel_ok(self) -> bool:
        f = self._run_capture("tailscale funnel status 2>/dev/null || true")
        return ":443" in f or "funnel on" in f.lower()

    def _warm_ts_cert(self, url: str) -> None:
        """Pre-provisiona il cert del Funnel (LE via Tailscale): senza, la PRIMA
        richiesta pubblica deve emettere il cert live e va spesso in timeout."""
        host = url.replace("https://", "").replace("http://", "").rstrip("/")
        if host:
            self._run_capture(f"tailscale cert {shlex.quote(host)} >/dev/null 2>&1 || true")

    def _set_gateway_bind(self, ingress: str, bind: str) -> None:
        """Cambia l'esposizione del gateway (GATEWAY_BIND) e lo ricrea.
        127.0.0.1 = solo loopback (produzione) · 0.0.0.0 = fallback pubblico."""
        cmd = self._compose_cmd(ingress, onboarding=False)
        self._run_capture(self._sudo(
            f"cd {REMOTE_DIR} && (grep -q ^GATEWAY_BIND= .env && sed -i 's|^GATEWAY_BIND=.*|GATEWAY_BIND={bind}|' .env || echo GATEWAY_BIND={bind} >> .env) && {cmd} up -d gateway"
        ))

    def step_tailscale_host(self, p: dict, ingress: str) -> Iterator[str]:
        """Tailscale SULL'HOST: install + up + serve + funnel + cert.
        Niente container/sidecar → niente bug containerboot, niente netns."""
        self.production = False
        if ingress != "tailscale" or not p.get("ts_authkey"):
            return
        key = p["ts_authkey"]
        hostname = (p.get("ts_hostname") or "vps1777").strip()
        yield "── Installo Tailscale sull'host…"
        for line in self._stream("curl -fsSL https://tailscale.com/install.sh | sh", "ts-install"):
            yield line
        self._run_capture("systemctl enable --now tailscaled 2>/dev/null || true")
        yield "── Login Tailscale (auth-key) + Funnel…"
        up = self._run_capture(
            f"tailscale up --authkey={shlex.quote(key)} --hostname={shlex.quote(hostname)} "
            "--accept-dns=false --reset 2>&1"
        )
        # ricavo l'URL .ts.net del nodo
        url = ""
        for _ in range(18):  # 90s
            time.sleep(5)
            url = self._ts_node_url()
            if url.endswith(".ts.net"):
                break
            yield "  ."
        if not url.endswith(".ts.net"):
            yield "! Login Tailscale non completato. Dettaglio: " + (up.strip().replace("\n", " ")[:200] or "controlla la auth-key.")
            yield "  → Lascio la porta 8080 (HTTP) come fallback."
            self._set_gateway_bind(ingress, "0.0.0.0")
            return
        self.result["URL"] = url
        yield f"✓ Nodo Tailscale: {url}"
        # Funnel HTTPS:443 → gateway (loopback). UN SOLO comando combinato:
        # `tailscale serve --https=443 <t>` + `tailscale funnel 443` separati
        # fanno interpretare "443" come TARGET (proxy a :443) e sovrascrivono
        # il mapping → 502. La forma combinata imposta mapping+pubblicazione insieme.
        self._run_capture("tailscale serve reset >/dev/null 2>&1 || true")
        fout = self._run_capture("tailscale funnel --bg --https=443 http://127.0.0.1:8080 2>&1")
        self._warm_ts_cert(url)
        # PUBLIC_BASE in .env + ricrea il gateway (resta su 127.0.0.1:8080)
        cmd = self._compose_cmd(ingress, onboarding=False)
        self._run_capture(self._sudo(
            f"cd {REMOTE_DIR} && (grep -q ^PUBLIC_BASE= .env && sed -i 's|^PUBLIC_BASE=.*|PUBLIC_BASE={url}|' .env || echo PUBLIC_BASE={url} >> .env) && {cmd} up -d gateway"
        ))
        time.sleep(4)
        if self._ts_funnel_ok():
            self.production = True
            yield "✓ Funnel HTTPS attivo su :443 (cert pre-provisionato)"
        else:
            low = (fout + " " + up).lower()
            if "funnel" in low and ("attribute" in low or "not permitted" in low or "denied" in low):
                yield "! Funnel non attivo: manca il nodeAttr 'funnel' nell'ACL (o HTTPS Certificates spento)."
            else:
                yield "! Funnel non confermato. Dettaglio: " + (fout.strip().replace("\n", " ")[:200] or "verifica i prerequisiti account.")
            yield "  → Checklist: login.tailscale.com/admin/dns (MagicDNS + HTTPS) e Access Controls (nodeAttr funnel)."
            yield "  → Apro la porta 8080 (HTTP) come fallback."
            self._set_gateway_bind(ingress, "0.0.0.0")

    def step_finalize(self, ingress: str) -> Iterator[str]:
        """Chiude la porta 8080 in chiaro quando il Funnel HTTPS è attivo."""
        if ingress == "tailscale":
            # host-mode: l'esposizione la gestisce GATEWAY_BIND già in
            # step_tailscale_host (127.0.0.1 in production, 0.0.0.0 in fallback).
            if getattr(self, "production", False):
                yield "✓ Gateway su 127.0.0.1:8080 (solo Funnel HTTPS); porta pubblica chiusa"
            else:
                yield "── Funnel non attivo: porta 8080 aperta come fallback"
            return
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
        time.sleep(20)
        cmd = self._compose_cmd(ingress, onboarding=not production)
        ps = self._run_capture(self._sudo(f"cd {REMOTE_DIR} && {cmd} ps"))
        for line in ps.splitlines():
            yield line
        # host-mode: tailscaled (systemd) riparte da solo col serve/funnel
        # persistito. Ri-derivo l'URL se manca e verifico l'HTTPS a regime.
        if ingress == "tailscale":
            if not self.result.get("URL", "").endswith(".ts.net"):
                yield "── Ricavo l'URL Tailscale a regime…"
                for _ in range(18):  # 90s
                    time.sleep(5)
                    u = self._ts_node_url()
                    if u.endswith(".ts.net"):
                        self.result["URL"] = u
                        self._run_capture(self._sudo(
                            f"cd {REMOTE_DIR} && (grep -q ^PUBLIC_BASE= .env && sed -i 's|^PUBLIC_BASE=.*|PUBLIC_BASE={u}|' .env || echo PUBLIC_BASE={u} >> .env) && {cmd} up -d gateway"
                        ))
                        yield f"✓ URL pubblico: {u}"
                        break
                    yield "  ."
            url = self.result.get("URL", "")
            if url.endswith(".ts.net"):
                self._warm_ts_cert(url)
                yield "── Verifico HTTPS pubblico…"
                time.sleep(8)
                # dall'host: curl verso il proprio Funnel (TLS pubblico)
                health = self._run_capture(
                    f"curl -fsS -m 12 {shlex.quote(url)}/health 2>/dev/null || true"
                ).lower()
                if '"ok"' in health or "service" in health:
                    yield f"✓ HTTPS pubblico risponde: {url}/health"
                    self.result["HTTPS_OK"] = "1"
                else:
                    yield "! HTTPS non ancora confermato (cert/propagazione, 1-2 min). Riprova dal browser: " + url + "/health"

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
    import os as _os
    d = Deployer(params.get("ip", ""), params.get("user", "root") or "root",
                 params.get("password", ""))
    ingress = {"1": "tailscale", "2": "caddy", "3": "cloudflared"}.get(params.get("ingress_num", "1"), "tailscale")
    try:
        yield "▶ Connessione alla VPS…"
        d.connect()
        yield f"✓ Connesso: {d.detect_os()}"

        # Versione da installare: esplicita (test/rc) > ultima release stable.
        # dev_build=True (o nessuna release pubblicata) → build locale (dev).
        dev_build = bool(params.get("dev_build")) or _os.environ.get("VPS1777_DEV_BUILD") == "1"
        version = ""
        if not dev_build:
            version = (params.get("vps1777_version")
                       or _os.environ.get("VPS1777_INSTALL_VERSION")
                       or latest_release_version(
                           prerelease=_os.environ.get("VPS1777_RELEASE_CHANNEL") == "prerelease"))
            if version:
                yield f"✓ Installerò la release v{version} (immagini ghcr, nessuna build)"
            else:
                yield "! Nessuna release pubblicata trovata → fallback: build locale (dev)"
                dev_build = True
        params["_vps1777_version"] = "" if dev_build else version
        params["_image_base"] = params.get("image_base", "")

        yield "═ STEP 1/8 — Preparazione VPS"
        yield from d.step_prepare()
        yield "═ STEP 2/8 — Trasferimento repo"
        yield from d.step_upload()
        yield "═ STEP 3/8 — Config + secrets"
        if ingress == "tailscale":
            yield from d.step_ts_provision(params)
        yield from d.step_config(params)
        yield "═ STEP 4/8 — Immagini + avvio"
        if dev_build:
            yield from d.step_build(ingress)
        else:
            yield from d.step_pull(ingress, version)
        yield "═ STEP 5/8 — Tailscale (host) + Funnel"
        yield from d.step_tailscale_host(params, ingress)
        yield "═ STEP 6/8 — Canale di aggiornamento"
        yield from d.step_selfupdate_setup()
        yield "═ STEP 7/8 — Finalizzazione (production)"
        yield from d.step_finalize(ingress)
        yield "═ STEP 8/8 — Reboot test + verifica HTTPS"
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


def check_telegram(token: str) -> dict:
    """Verifica REALE del bot token via l'API Telegram getMe."""
    token = (token or "").strip()
    if not token:
        return {"ok": False, "error": "token vuoto"}
    import json as _j
    import urllib.request
    try:
        url = f"https://api.telegram.org/bot{token}/getMe"
        with urllib.request.urlopen(url, timeout=10) as r:
            d = _j.loads(r.read().decode("utf-8"))
        if d.get("ok"):
            res = d.get("result", {})
            return {"ok": True, "username": res.get("username", "?"), "name": res.get("first_name", "")}
        return {"ok": False, "error": "token rifiutato da Telegram"}
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return {"ok": False, "error": "token non valido (401)"}
        return {"ok": False, "error": f"HTTP {e.code}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
