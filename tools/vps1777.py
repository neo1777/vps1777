#!/usr/bin/env python3
"""vps1777 — canale di aggiornamento controllato per le installazioni vps1777.

Motore unico host-side (solo stdlib): il pulsante admin, il timer di check e
il terminale sono trigger sottili verso questa CLI. Modello registry-pull:
niente build in produzione (VPS 4GB), immagini pullate da ghcr e verificate
contro il lockfile di digest (images.lock) del runtime bundle di release.

Sottocomandi:
  check      controlla l'ultima release GitHub (con --notify avvisa su Telegram)
  update     aggiorna: backup → pull+verify → migrazioni → health-gate → esito
             (auto-rollback oltre il punto di non ritorno)
  rollback   torna alla versione precedente (--with-data per i volumi)
  status     stato corrente (--json, --probe)
  version    versioni: tag deployato + VPS1777_VERSION dei container
  migrate    runner migrazioni (--pending | --run)
  bootstrap  cutover one-shot di un'installazione legacy (build locale → pull)

Design: docs/SELF_UPDATE_PLAN.md. Contratto migrazioni: migrations/README.md.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import pwd
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ─────────────────────────────────────────── costanti

GITHUB_REPO = os.environ.get("VPS1777_GITHUB_REPO", "neo1777/vps1777")
API_BASE = f"https://api.github.com/repos/{GITHUB_REPO}"
USER_AGENT = "vps1777-updater"

SERVICES = ["gateway", "archive-mcp", "nb1777-mcp", "nb1777-bot"]
# Volumi dati (nomi corti compose). Prefisso progetto: vps1777_
NLM_AUTH_VOLUME = "nlm-auth"
DATA_VOLUMES = ["gateway-data", "archive-data", NLM_AUTH_VOLUME]
# Path canonico di mount di ogni volume nei container one-off delle migrazioni.
VOLUME_MOUNTS = {
    "gateway-data": "/var/lib/gateway",
    "archive-data": "/var/lib/archive",
    "nlm-auth": "/var/lib/nlm",
}

# ── H14 — cosa NON finisce nello snapshot pre-update ─────────────────────────
# Lo snapshot pre-update (backups/pre-update/) è NON CIFRATO per costruzione:
# serve all'auto-rollback, che gira sulla VPS e non può dipendere dalla chiave
# age (la privata vive sul PC dell'owner, e deve restarci). Quindi tutto ciò che
# ci mettiamo dentro sta IN CHIARO sul disco dell'host.
#
# `nlm-auth` contiene i cookie di sessione Google di NotebookLM
# (profiles/default/cookies.json). La v0.30.0 li ha tolti al gateway — l'unico
# servizio esposto — perché nessuno tranne nb1777-mcp li vedesse (H6): copiarli
# in chiaro in backups/ a ogni update erode esattamente quel lavoro (un dump
# della cartella li restituisce tutti).
#
# Perché escluderlo NON rompe l'auto-rollback (verificato, non assunto):
#  1. lo snapshot viene usato SOLO da _rollback_routine() e solo quando una
#     migrazione data_mutating ha (forse) toccato i dati; serve a salvare i DATI
#     (archivio, audit, stato gateway), non una sessione;
#  2. l'auth NotebookLM non è un dato: è una sessione che si ricarica in un
#     minuto da /admin/nlm (e comunque i cookie scadono da soli);
#  3. il rollback non legge mai nlm-auth: ripristina file gestiti, tag immagine,
#     volumi, poi health-gate (che non prova l'auth Google);
#  4. il backup age (tools/backup.sh, eseguito allo step 7 subito PRIMA dello
#     snapshot) include comunque nlm-auth, ma CIFRATO → niente perdita
#     irreversibile, solo un restore in più a carico dell'owner;
#  5. tools/restore.sh itera sui .tar PRESENTI nello snapshot e salta quelli non
#     elencati (restore.sh:148-153) → un nlm-auth.tar assente non è un errore.
SNAPSHOT_EXCLUDED_VOLUMES = [NLM_AUTH_VOLUME]
SNAPSHOT_VOLUMES = [v for v in DATA_VOLUMES if v not in SNAPSHOT_EXCLUDED_VOLUMES]
SNAPSHOT_EXCLUDED_REASON = (
    "cookie di sessione Google (H6/H14): lo snapshot pre-update non è cifrato — "
    "il profilo NotebookLM si ricarica da /admin/nlm, ed è nel backup age"
)
# Path (relativi al repo) che il sync dei file gestiti NON tocca MAI.
PROTECTED_PREFIXES = (
    ".env", "secrets/", "onboarding/", "backups/", "var/", "releases/",
    "tools/age-recipients.txt",
)

SEMVER_RE = re.compile(r"^v?\d+\.\d+\.\d+(-[A-Za-z0-9.]+)?$")
INTENT_TTL_S = 600
HEALTH_WINDOW_S = 180
HEALTH_POLL_S = 5
HEALTH_CONSECUTIVE = 2

INSTALLED_CLI = "/usr/local/bin/vps1777"

# ─────────────────────────────────────────── UI

_TTY = sys.stdout.isatty()


def _c(code: str) -> str:
    return f"\033[{code}m" if _TTY else ""


def log(msg: str) -> None:
    print(f"{_c('34')}[*]{_c('0')} {msg}", flush=True)


def ok(msg: str) -> None:
    print(f"{_c('32')}[✓]{_c('0')} {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"{_c('33')}[!]{_c('0')} {msg}", flush=True)


def die(msg: str, code: int = 1) -> None:
    print(f"{_c('31')}[✗]{_c('0')} {msg}", file=sys.stderr, flush=True)
    sys.exit(code)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ─────────────────────────────────────────── subprocess

def run(cmd: list[str], *, env: dict | None = None, check: bool = True,
        capture: bool = False, cwd: str | Path | None = None,
        timeout: int | None = None) -> subprocess.CompletedProcess:
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    return subprocess.run(
        cmd, env=full_env, check=check, cwd=str(cwd) if cwd else None,
        capture_output=capture, text=True, timeout=timeout,
    )


def sudo(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    # -n: mai prompt interattivo (l'utente operatore ha NOPASSWD; se non ce
    # l'ha meglio fallire subito che restare appesi in una unit systemd).
    return run(["sudo", "-n", *cmd], **kw)


# ─────────────────────────────────────────── proprietà degli artefatti

def reclaim_ownership(path: Path, repo: Path) -> None:
    """
    Ciò che l'update crea sotto il repo resta dell'OPERATOR, sempre.

    Perché esiste: `vps1777 update` è pensato per girare come operator (che ha
    sudo NOPASSWD), ma capita di lanciarlo da una shell root. In quel caso le
    cartelle create — `releases/vX.Y.Z/` — restavano di proprietà di root, e
    l'update SUCCESSIVO, lanciato dall'operator com'è giusto, non riusciva più a
    creare la sua cartella di rollback lì dentro: moriva con un PermissionError
    grezzo, a metà (dopo il pull, prima del punto di non ritorno).

    Qui la proprietà si riallinea da sé, nei due versi: se giriamo da root
    chowniamo a chi possiede il repo; se giriamo da operator e troviamo roba
    altrui, ce la riprendiamo con sudo. Nessun intervento manuale.
    """
    if not path.exists():
        return
    try:
        uid, gid = repo.stat().st_uid, repo.stat().st_gid
    except OSError:
        return
    if uid == 0:                       # repo di root: non c'è nulla da riallineare
        return
    try:
        if os.geteuid() == 0:
            for p in (path, *path.rglob("*")):
                os.chown(p, uid, gid)
        elif path.stat().st_uid != os.geteuid():
            sudo(["chown", "-R", f"{uid}:{gid}", str(path)])
    except (OSError, subprocess.CalledProcessError) as exc:
        warn(f"proprietà di {path} non riallineata ({exc})")


# ─────────────────────────────────────────── repo & file .env

def find_repo(explicit: str | None) -> Path:
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    if os.environ.get("VPS1777_HOME"):
        candidates.append(Path(os.environ["VPS1777_HOME"]))
    candidates.append(Path("/home/vps1777/vps1777"))
    candidates.append(Path.cwd())
    for c in candidates:
        if (c / "compose.yaml").is_file():
            return c.resolve()
    die("repo vps1777 non trovato (compose.yaml assente). Usa --home o VPS1777_HOME.")
    raise SystemExit  # unreachable


def env_read(repo: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    envf = repo / ".env"
    if not envf.is_file():
        return out
    for line in envf.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.split("#", 1)[0].strip() if " #" in v else v.strip()
    return out


def env_set(repo: Path, key: str, value: str) -> None:
    envf = repo / ".env"
    lines = envf.read_text().splitlines() if envf.is_file() else []
    prefix = f"{key}="
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    envf.write_text("\n".join(lines) + "\n")


# ─────────────────────────────────────────── state.json

def state_path(repo: Path) -> Path:
    return repo / "var" / "state.json"


def state_load(repo: Path) -> dict:
    p = state_path(repo)
    if p.is_file():
        try:
            return json.loads(p.read_text())
        except json.JSONDecodeError:
            warn(f"state.json corrotto, riparto pulito ({p})")
    return {"schema": 1, "current": None, "previous": None,
            "previous_images": {}, "history": [], "last_check": None,
            "last_notified_version": None, "update_in_progress": None,
            "intent_nonces": []}


def state_save(repo: Path, st: dict) -> None:
    var = repo / "var"
    var.mkdir(mode=0o700, exist_ok=True)
    tmp = var / ".state.json.tmp"
    tmp.write_text(json.dumps(st, indent=2, sort_keys=True) + "\n")
    tmp.replace(state_path(repo))


# ─────────────────────────────────────────── progress & status (letti dal gateway)

def onboarding_dir(repo: Path) -> Path:
    d = repo / "onboarding"
    d.mkdir(exist_ok=True)
    return d


def progress_write(repo: Path, target: str, step: int, name: str,
                   status: str, detail: str = "") -> None:
    p = onboarding_dir(repo) / "update_progress.json"
    p.write_text(json.dumps({
        "target": target, "step": step, "step_name": name,
        "status": status, "detail": detail, "updated_at": now_iso(),
    }, indent=2) + "\n")


def status_write(repo: Path, **fields) -> None:
    p = onboarding_dir(repo) / "update_status.json"
    data: dict = {}
    if p.is_file():
        try:
            data = json.loads(p.read_text())
        except json.JSONDecodeError:
            data = {}
    data.update(fields)
    data["checked_at"] = now_iso()
    p.write_text(json.dumps(data, indent=2) + "\n")


# ─────────────────────────────────────────── Telegram (notifica, mai fatale)

def telegram_notify(repo: Path, text: str) -> None:
    token_file = repo / "secrets" / "telegram_bot_token.txt"
    envd = env_read(repo)
    owner = envd.get("TELEGRAM_OWNER_ID", "")
    if not token_file.is_file() or not owner:
        log("telegram: token/owner assenti, notifica saltata")
        return
    token = token_file.read_text().strip()
    if not token:
        return
    payload = urllib.parse.urlencode({"chat_id": owner, "text": text}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10):
            pass
    except (urllib.error.URLError, OSError) as exc:
        warn(f"telegram: notifica fallita ({exc}) — proseguo")


# ─────────────────────────────────────────── GitHub API

def github_json(path: str) -> dict | list:
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp)


def release_channel(repo: Path) -> str:
    return (os.environ.get("VPS1777_RELEASE_CHANNEL")
            or env_read(repo).get("VPS1777_RELEASE_CHANNEL", "stable"))


def latest_release(repo: Path) -> dict | None:
    """Ultima release del canale: stable → /releases/latest (esclude prerelease);
    prerelease → prima voce di /releases (solo test)."""
    try:
        if release_channel(repo) == "prerelease":
            rels = github_json("/releases?per_page=5")
            return rels[0] if rels else None
        return github_json("/releases/latest")  # type: ignore[return-value]
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None  # nessuna release pubblicata
        raise


def release_by_tag(tag: str) -> dict:
    return github_json(f"/releases/tags/{tag}")  # type: ignore[return-value]


def download(url: str, dest: Path, timeout: int = 120) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as fh:
        shutil.copyfileobj(resp, fh)


# ─────────────────────────────────────────── versioni & semver

def norm_ver(v: str) -> str:
    return v.lstrip("v").strip()


def valid_semver(v: str) -> bool:
    return bool(SEMVER_RE.match(v.strip()))


def version_key(v: str) -> tuple:
    """Chiave d'ordinamento SemVer: una prerelease (X.Y.Z-rc) < della stable X.Y.Z."""
    v = norm_ver(v)
    core, _, pre = v.partition("-")
    parts = tuple(int(x) if x.isdigit() else 0 for x in core.split("."))
    while len(parts) < 3:
        parts += (0,)
    # senza suffisso pre → (…, 1); con suffisso → (…, 0, pre) così ordina prima
    return (parts, 1, ()) if not pre else (parts, 0, tuple(pre.split(".")))


def current_version(repo: Path) -> str:
    return env_read(repo).get("VPS1777_TAG", "dev")


# ─────────────────────────────────────────── compose

def ingress_profile(repo: Path) -> str:
    return env_read(repo).get("INGRESS_PROFILE", "ingress.tailscale")


# Feature opzionali DICHIARATE in .env (VPS1777_FEATURES). Sono lo "stato voluto":
# leggerle QUI — dove si costruisce OGNI comando compose (up/down/ps/health-gate) —
# fa sì che install, update e rollback riproducano SEMPRE le stesse feature. È il fix
# del difetto per cui un reinstall O un update lasciava cadere gli opt-in in silenzio
# (backup notturno sparito senza un errore). Mappa: feature dichiarata → profilo
# compose. `autoupdate` NON è qui: è un timer systemd (vps1777-auto-update), non un
# container. `watchtower` è l'auto-update CRUDO (declassato), alternativa INSICURA ad
# `autoupdate` — supportato solo se dichiarato esplicitamente, e in conflitto con esso.
# feature dichiarata → (suffisso del FILE compose, nome del PROFILO). Per watchtower
# i due DIFFERISCONO: il file è compose.ops.watchtower.yaml ma il profilo è
# ops.autoupdate — derivare il file dal profilo darebbe compose.ops.autoupdate.yaml
# (inesistente). Backup/portainer: file e profilo coincidono.
OPS_COMPOSE_FEATURES = {
    "backup": ("ops.backup", "ops.backup"),
    "portainer": ("ops.portainer", "ops.portainer"),
    "watchtower": ("ops.watchtower", "ops.autoupdate"),
}
DEFAULT_FEATURES = {"backup", "autoupdate"}   # backup + auto-update SICURO accesi di default


def enabled_features(repo: Path) -> set[str]:
    """Le feature opzionali dichiarate in .env (VPS1777_FEATURES). Vuoto/assente → i
    default. Un valore esplicito (anche 'none') vince: così si può anche spegnere tutto."""
    val = env_read(repo).get("VPS1777_FEATURES")
    if val is None:
        return set(DEFAULT_FEATURES)
    return {f.strip() for f in val.split(",") if f.strip() and f.strip() != "none"}


def compose_cmd(repo: Path, *, files: list[Path] | None = None) -> list[str]:
    profile = ingress_profile(repo)
    cmd = ["docker", "compose", "--project-directory", str(repo)]
    extra_profiles: list[str] = []
    if files is None:
        files = [repo / "compose.yaml", repo / f"compose.{profile}.yaml"]
        feats = enabled_features(repo)
        for feat, (file_sfx, prof) in OPS_COMPOSE_FEATURES.items():
            if feat in feats:
                files.append(repo / f"compose.{file_sfx}.yaml")
                extra_profiles.append(prof)
    for f in files:
        cmd += ["-f", str(f)]
    cmd += ["--profile", profile]
    for p in extra_profiles:
        cmd += ["--profile", p]
    return cmd


def compose_ps(repo: Path, env: dict | None = None,
               all_states: bool = False) -> list[dict]:
    # --all include i container exited/created: senza, un servizio CRASHATO
    # sparisce da `ps` e il health-gate non lo vede (falso verde).
    cmd = [*compose_cmd(repo), "ps", "--format", "json"]
    if all_states:
        cmd.append("--all")
    res = run(cmd, capture=True, check=False, env=env)
    if res.returncode != 0:
        return []
    text = res.stdout.strip()
    if not text:
        return []
    # compose v2: un JSON per riga (o, in versioni vecchie, un array unico)
    if text.startswith("["):
        return json.loads(text)
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def stack_running(repo: Path) -> bool:
    return any(p.get("State") == "running" for p in compose_ps(repo))


# ─────────────────────────────────────────── health-gate

def deep_health_ok(repo: Path, env: dict | None = None) -> bool:
    probe = ("import urllib.request,sys;"
             "r=urllib.request.urlopen('http://127.0.0.1:8080/health?deep=1',timeout=5);"
             "sys.exit(0 if r.status==200 else 1)")
    res = run([*compose_cmd(repo), "exec", "-T", "gateway", "python", "-c", probe],
              check=False, capture=True, env=env)
    return res.returncode == 0


def restart_counts(repo: Path) -> dict[str, int]:
    res = run([*compose_cmd(repo), "ps", "-q"], capture=True, check=False)
    counts: dict[str, int] = {}
    for cid in res.stdout.split():
        insp = run(["docker", "inspect", "--format",
                    "{{.Name}} {{.RestartCount}}", cid], capture=True, check=False)
        if insp.returncode == 0 and insp.stdout.strip():
            name, _, cnt = insp.stdout.strip().rpartition(" ")
            counts[name] = int(cnt)
    return counts


def health_gate(repo: Path, env: dict | None = None,
                window_s: int = HEALTH_WINDOW_S) -> tuple[bool, str]:
    """True se tutti i servizi compose sono running+healthy E /health?deep=1
    risponde 200, per HEALTH_CONSECUTIVE poll consecutivi entro la finestra."""
    deadline = time.monotonic() + window_s
    consecutive = 0
    baseline = restart_counts(repo)
    reason = "timeout finestra health"
    while time.monotonic() < deadline:
        # --all: un container exited DEVE contare come non-green, non sparire
        services = compose_ps(repo, env=env, all_states=True)
        green = bool(services)
        for svc in services:
            state = svc.get("State", "")
            health = svc.get("Health", "") or ""
            if state != "running" or health not in ("", "healthy"):
                green = False
                reason = f"{svc.get('Service', svc.get('Name', '?'))}: state={state} health={health or '-'}"
                break
        # restart-loop: un container che riparte in continuazione non diventerà mai sano
        for name, cnt in restart_counts(repo).items():
            if cnt > baseline.get(name, 0) + 2:
                return False, f"restart-loop: {name} (restart {cnt})"
        if green and not deep_health_ok(repo, env=env):
            green = False
            reason = "gateway /health?deep=1 non risponde 200"
        if green:
            consecutive += 1
            if consecutive >= HEALTH_CONSECUTIVE:
                return True, "ok"
        else:
            consecutive = 0
        time.sleep(HEALTH_POLL_S)
    return False, reason


# ─────────────────────────────────────────── registro migrazioni (nel volume)

REGISTRY_VOLUME = "vps1777_gateway-data"
REGISTRY_PATH = "state/migrations.json"  # dentro il volume


def registry_read() -> dict:
    res = run(["docker", "run", "--rm", "-v", f"{REGISTRY_VOLUME}:/state:ro",
               "--entrypoint", "sh", "busybox:latest",
               "-c", f"cat /state/{REGISTRY_PATH} 2>/dev/null || echo '{{}}'"],
              capture=True, check=False)
    try:
        data = json.loads(res.stdout.strip() or "{}")
    except json.JSONDecodeError:
        data = {}
    if "applied" not in data:
        data = {"schema": 1, "applied": []}
    return data


def _registry_write(data: dict) -> None:
    payload = json.dumps(data, indent=2, sort_keys=True)
    subprocess.run(
        ["docker", "run", "--rm", "-i", "-v", f"{REGISTRY_VOLUME}:/state",
         "--entrypoint", "sh", "busybox:latest",
         "-c", f"mkdir -p /state/$(dirname {REGISTRY_PATH}) && cat > /state/{REGISTRY_PATH}"],
        input=payload, text=True, check=True)


class MigrationError(RuntimeError):
    """Fallimento del runner con l'informazione che serve al rollback:
    i dati sono (potenzialmente) stati mutati prima/durante il fallimento?"""

    def __init__(self, msg: str, mutated: bool):
        super().__init__(msg)
        self.mutated = mutated


def migrations_pending(repo: Path) -> list[Path]:
    migdir = repo / "migrations"
    if not migdir.is_dir():
        return []
    applied = {e["id"] for e in registry_read()["applied"]}
    pending = []
    for d in sorted(migdir.iterdir()):
        if d.is_dir() and (d / "migration.json").is_file():
            meta = json.loads((d / "migration.json").read_text())
            if meta["id"] not in applied:
                pending.append(d)
    return pending


def run_migrations(repo: Path, images: dict[str, str],
                   target_version: str) -> tuple[list[dict], bool]:
    """Applica le migrazioni pendenti, in ordine. images: svc→ref (digest-pinned).
    Ritorna (metadati eseguiti, almeno-una-data-mutating). Solleva su fallimento."""
    executed: list[dict] = []
    any_mutating = False
    for d in migrations_pending(repo):
        meta = json.loads((d / "migration.json").read_text())
        mid = meta["id"]
        svc = meta["service"]
        # se la migrazione che fallisce è data_mutating, i suoi write parziali
        # contano come mutazione → il rollback deve ripristinare lo snapshot
        would_mutate = any_mutating or bool(meta.get("data_mutating"))
        image = images.get(svc)
        if not image:
            raise MigrationError(f"migrazione {mid}: service sconosciuto '{svc}'",
                                 any_mutating)
        log(f"migrazione {mid} ({meta.get('description', '')}) su {svc}…")
        cmd = ["docker", "run", "--rm", "--network", "none",
               "-v", f"{d.resolve()}:/migration:ro"]
        for vol in meta.get("volumes", []):
            mount = VOLUME_MOUNTS.get(vol)
            if not mount:
                raise MigrationError(f"migrazione {mid}: volume sconosciuto '{vol}'",
                                     any_mutating)
            # H14: i volumi esclusi non stanno nello snapshot → se una migrazione
            # data_mutating li tocca, l'auto-rollback NON li ripristina. Non è
            # fatale (l'auth nlm si ricarica da /admin/nlm, ed è nel backup age),
            # ma chi scrive la migrazione deve saperlo prima di scoprirlo dopo.
            if meta.get("data_mutating") and vol in SNAPSHOT_EXCLUDED_VOLUMES:
                warn(f"migrazione {mid}: data_mutating su '{vol}', volume ESCLUSO "
                     f"dallo snapshot pre-update → un rollback non lo ripristina "
                     f"(ricarica il profilo da /admin/nlm, o restore dal backup age)")
            cmd += ["-v", f"vps1777_{vol}:{mount}"]
        cmd += ["--entrypoint", "python", image, "/migration/run.py"]
        res = run(cmd, check=False, capture=True)
        if res.returncode != 0:
            raise MigrationError(
                f"migrazione {mid} fallita (exit {res.returncode}):\n{res.stdout}\n{res.stderr}",
                would_mutate)
        checksum = hashlib.sha256((d / "run.py").read_bytes()).hexdigest()
        reg = registry_read()
        reg["applied"].append({"id": mid, "version": target_version,
                               "applied_at": now_iso(), "checksum": checksum})
        _registry_write(reg)
        executed.append(meta)
        if meta.get("data_mutating"):
            any_mutating = True
        ok(f"migrazione {mid} applicata")
    return executed, any_mutating


# ─────────────────────────────────────────── bundle: fetch, verifica, sync

_COSIGN_VERSION = "v2.4.1"
_COSIGN_URL = (f"https://github.com/sigstore/cosign/releases/download/"
               f"{_COSIGN_VERSION}/cosign-linux-amd64")


def _ensure_cosign(repo: Path) -> str | None:
    """Path di cosign; se manca, prova a installarlo (binario pinnato) in
    /usr/local/bin. Ritorna None se non riesce. Rende la verifica firma
    obbligatoria-di-default sostenibile anche su installazioni che non hanno
    cosign, senza dipendere dal deploy iniziale."""
    c = shutil.which("cosign")
    if c:
        return c
    try:
        tmp = repo / ".cosign-dl"
        download(_COSIGN_URL, tmp)
        sudo(["install", "-m", "755", str(tmp), "/usr/local/bin/cosign"])
        tmp.unlink(missing_ok=True)
        got = shutil.which("cosign")
        if got:
            ok(f"cosign installato ({_COSIGN_VERSION})")
        return got
    except (OSError, subprocess.CalledProcessError, urllib.error.URLError) as exc:
        warn(f"auto-install di cosign fallito: {exc}")
        return None


def staging_dir(repo: Path, version: str) -> Path:
    return repo / "releases" / f"v{norm_ver(version)}"


def fetch_bundle(repo: Path, release: dict, require_cosign: bool) -> Path:
    """Scarica e verifica il runtime bundle della release. Ritorna la dir bundle/."""
    version = norm_ver(release["tag_name"])
    stage = staging_dir(repo, version)
    stage.mkdir(parents=True, exist_ok=True)
    assets = {a["name"]: a["browser_download_url"] for a in release.get("assets", [])}
    tarball = f"vps1777-runtime-v{version}.tar.gz"
    for required in (tarball, "SHA256SUMS"):
        if required not in assets:
            raise RuntimeError(f"asset '{required}' assente dalla release v{version}")
    log(f"scarico {tarball}…")
    download(assets[tarball], stage / tarball)
    download(assets["SHA256SUMS"], stage / "SHA256SUMS")
    for optional in ("SHA256SUMS.sig", "SHA256SUMS.pem"):
        if optional in assets:
            download(assets[optional], stage / optional)

    # verifica sha256
    want = ""
    for line in (stage / "SHA256SUMS").read_text().splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == tarball:
            want = parts[0]
    got = hashlib.sha256((stage / tarball).read_bytes()).hexdigest()
    if not want or got != want:
        raise RuntimeError(f"sha256 mismatch sul bundle: atteso {want or '?'} ottenuto {got}")
    ok("sha256 del bundle verificato")

    # cosign: obbligatorio di default. Se manca ma è richiesto, prova a
    # installarlo (fail-closed: se non ci riesce, la verifica non si salta).
    cosign = shutil.which("cosign")
    if require_cosign and not cosign:
        cosign = _ensure_cosign(repo)
        if not cosign:
            raise RuntimeError(
                "verifica firma richiesta ma cosign è assente e non installabile. "
                "Installalo (github.com/sigstore/cosign), oppure — via d'emergenza "
                "CONSAPEVOLE — imposta VPS1777_REQUIRE_COSIGN=0 nel .env.")
    if cosign and (stage / "SHA256SUMS.sig").is_file() and (stage / "SHA256SUMS.pem").is_file():
        identity = rf"^https://github\.com/{re.escape(GITHUB_REPO)}/\.github/workflows/release\.yml@.*$"
        res = run([cosign, "verify-blob",
                   "--certificate-identity-regexp", identity,
                   "--certificate-oidc-issuer", "https://token.actions.githubusercontent.com",
                   "--signature", str(stage / "SHA256SUMS.sig"),
                   "--certificate", str(stage / "SHA256SUMS.pem"),
                   str(stage / "SHA256SUMS")], check=False, capture=True)
        if res.returncode != 0:
            raise RuntimeError(f"cosign verify-blob fallita:\n{res.stderr}")
        ok("firma cosign verificata")
    elif require_cosign:
        raise RuntimeError("--require-cosign ma la release non ha firma .sig/.pem")

    # estrai (path traversal guard)
    bundle = stage / "bundle"
    if bundle.exists():
        shutil.rmtree(bundle)
    bundle.mkdir()
    bundle_root = str(bundle.resolve())
    with tarfile.open(stage / tarball, "r:gz") as tar:
        for m in tar.getmembers():
            dest = (bundle / m.name).resolve()
            # confronto con separatore: senza, /bundle-evil passerebbe il
            # prefix-check di /bundle. E rifiuta link/hardlink fuori radice.
            if dest != bundle.resolve() and not str(dest).startswith(bundle_root + os.sep):
                raise RuntimeError(f"bundle malformato (path traversal): {m.name}")
        try:
            # Python ≥3.11.4: blocca anche symlink/device/permessi anomali
            tar.extractall(bundle, filter="data")
        except TypeError:
            tar.extractall(bundle)

    # Se questo update gira da root, ciò che ha appena creato deve restare
    # dell'operator: altrimenti il PROSSIMO update (lanciato da lui, com'è
    # giusto) non potrebbe scrivere qui dentro.
    reclaim_ownership(stage, repo)
    return bundle


def load_manifest(path: Path) -> dict:
    return json.loads(path.read_text()) if path.is_file() else {"files": {}}


def is_protected(rel: str) -> bool:
    return any(rel == p.rstrip("/") or rel.startswith(p) for p in PROTECTED_PREFIXES)


def sync_managed_files(repo: Path, bundle: Path) -> None:
    """Applica i file gestiti dal bundle al repo; rimuove i gestiti obsoleti
    (presenti nel vecchio manifest, assenti dal nuovo). Mai i PROTECTED."""
    new_manifest = load_manifest(bundle / "bundle-manifest.json")
    old_manifest = load_manifest(repo / "bundle-manifest.json")
    for rel in sorted(new_manifest["files"]):
        if is_protected(rel):
            continue
        src, dst = bundle / rel, repo / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    shutil.copy2(bundle / "bundle-manifest.json", repo / "bundle-manifest.json")
    for rel in sorted(set(old_manifest["files"]) - set(new_manifest["files"])):
        if is_protected(rel):
            continue
        target = repo / rel
        if target.is_file():
            target.unlink()
            log(f"file gestito obsoleto rimosso: {rel}")


def save_rollback_files(repo: Path, version: str, bundle: Path) -> Path:
    """Copia lo stato corrente dei file gestiti in releases/<current>/rollback-files."""
    stage = staging_dir(repo, version)
    # La dir della versione CORRENTE può essere stata creata da un update
    # lanciato come root: senza riallineare la proprietà non potremmo scriverci
    # dentro la cartella di rollback (ed è proprio dove si moriva).
    reclaim_ownership(stage, repo)
    dest = stage / "rollback-files"
    if dest.exists():
        shutil.rmtree(dest)
    try:
        dest.mkdir(parents=True)
    except PermissionError as exc:
        die(f"non riesco a creare {dest} ({exc}).\n"
            f"È una deriva di proprietà: qualcosa sotto {repo / 'releases'} non è tuo.\n"
            f"Rimedio: sudo chown -R $(id -u):$(id -g) {repo / 'releases'}")
    rels = set(load_manifest(bundle / "bundle-manifest.json")["files"]) | \
        set(load_manifest(repo / "bundle-manifest.json")["files"])
    for rel in sorted(rels):
        src = repo / rel
        if src.is_file() and not is_protected(rel):
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / rel)
    if (repo / "bundle-manifest.json").is_file():
        shutil.copy2(repo / "bundle-manifest.json", dest / "bundle-manifest.json")
    return dest


def restore_rollback_files(repo: Path, rollback_dir: Path, bundle: Path) -> None:
    """Ripristina i file gestiti salvati; rimuove quelli introdotti dal nuovo bundle."""
    new_manifest = load_manifest(bundle / "bundle-manifest.json")
    saved = {str(p.relative_to(rollback_dir))
             for p in rollback_dir.rglob("*") if p.is_file()}
    for rel in sorted(set(new_manifest["files"]) - saved):
        if is_protected(rel):
            continue
        target = repo / rel
        if target.is_file():
            target.unlink()
    for rel in sorted(saved):
        src, dst = rollback_dir / rel, repo / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


# ─────────────────────────────────────────── immagini

def image_base(repo: Path) -> str:
    return env_read(repo).get("VPS1777_IMAGE_BASE", "ghcr.io/neo1777")


def image_ref(repo: Path, svc: str, version: str) -> str:
    return f"{image_base(repo)}/vps1777-{svc}:{norm_ver(version)}"


def verify_digests(repo: Path, lock: dict[str, str], version: str) -> None:
    for svc in SERVICES:
        ref = image_ref(repo, svc, version)
        locked = lock.get(svc, "")
        res = run(["docker", "image", "inspect", "--format",
                   "{{json .RepoDigests}}", ref], capture=True, check=False)
        if res.returncode != 0:
            raise RuntimeError(f"immagine non presente dopo il pull: {ref}")
        digests = json.loads(res.stdout.strip())
        if locked not in digests:
            raise RuntimeError(
                f"digest mismatch per {svc}: lock={locked} locale={digests}")
    ok("digest verificati contro images.lock")


def capture_current_images(repo: Path, version: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for svc in SERVICES:
        ref = image_ref(repo, svc, version)
        res = run(["docker", "image", "inspect", "--format",
                   "{{json .RepoDigests}}", ref], capture=True, check=False)
        if res.returncode == 0:
            digests = json.loads(res.stdout.strip())
            if digests:
                out[svc] = digests[0]
    return out


def prune_old_images(repo: Path, keep_versions: set[str], history: list[dict]) -> None:
    # le versioni viste stanno nei campi from/to della history
    seen: set[str] = set()
    for h in history:
        for k in ("from", "to"):
            v = norm_ver(str(h.get(k) or ""))
            if v:
                seen.add(v)
    seen -= {norm_ver(v) for v in keep_versions if v}
    for ver in seen:
        if not ver or ver == "dev":
            continue
        for svc in SERVICES:
            run(["docker", "image", "rm", image_ref(repo, svc, ver)],
                check=False, capture=True)
    # le immagini dev (build locali pre-bootstrap) restano finché non le si
    # rimuove a mano: sono il paracadute del bootstrap.


# ─────────────────────────────────────────── snapshot volumi (pre-update)

def snapshot_stale_excluded(base: Path) -> list[Path]:
    """I .tar di volumi ESCLUSI rimasti negli snapshot già sul disco.

    Logica pura (testabile): gli snapshot creati da una CLI precedente a questo
    fix contengono `nlm-auth.tar` in chiaro. Aggiornare la CLI non basta: quel
    residuo va rimosso, o il segreto resta lì fino al prune (72h) — o per sempre,
    se l'ultimo snapshot è quello tenuto come `keep`."""
    if not base.is_dir():
        return []
    stale = []
    for snap in sorted(d for d in base.iterdir() if d.is_dir()):
        for vol in SNAPSHOT_EXCLUDED_VOLUMES:
            tar = snap / f"{vol}.tar"
            if tar.is_file():
                stale.append(tar)
    return stale


def snapshot_purge_excluded(repo: Path) -> int:
    """Cancella i .tar esclusi lasciati dagli snapshot vecchi. Mai fatale."""
    removed = 0
    for tar in snapshot_stale_excluded(repo / "backups" / "pre-update"):
        try:
            tar.unlink()
            removed += 1
        except OSError as exc:
            warn(f"non rimuovo il residuo {tar.name}: {exc}")
    if removed:
        ok(f"rimossi {removed} .tar di volumi esclusi da snapshot precedenti "
           f"({', '.join(SNAPSHOT_EXCLUDED_VOLUMES)} — {SNAPSHOT_EXCLUDED_REASON})")
    return removed


def snapshot_create(repo: Path, from_version: str, to_version: str) -> Path:
    # prima di crearne uno nuovo, ripulisci il chiaro lasciato dalle CLI vecchie
    snapshot_purge_excluded(repo)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    snap = repo / "backups" / "pre-update" / f"{norm_ver(to_version)}-{ts}"
    snap.mkdir(parents=True, exist_ok=True)
    snap.chmod(0o700)
    # SNAPSHOT_VOLUMES, non DATA_VOLUMES: vedi il commento su H14 in testa al
    # file — lo snapshot è in chiaro, i cookie Google non ci entrano.
    for vol in SNAPSHOT_VOLUMES:
        log(f"snapshot volume {vol}…")
        run(["docker", "run", "--rm",
             "-v", f"vps1777_{vol}:/src:ro", "-v", f"{snap}:/dst",
             "--entrypoint", "sh", "busybox:latest",
             "-c", f"cd /src && tar cf /dst/{vol}.tar ."], check=True)
    for vol in SNAPSHOT_EXCLUDED_VOLUMES:
        log(f"snapshot volume {vol}: ESCLUSO — {SNAPSHOT_EXCLUDED_REASON}")
    (snap / "meta.json").write_text(json.dumps({
        "from_version": from_version, "to_version": to_version,
        "created_at": now_iso(), "volumes": SNAPSHOT_VOLUMES,
        "excluded_volumes": SNAPSHOT_EXCLUDED_VOLUMES,
        "excluded_reason": SNAPSHOT_EXCLUDED_REASON}, indent=2) + "\n")
    ok(f"snapshot locale: {snap}")
    return snap


def snapshot_restore(repo: Path, snap: Path) -> None:
    # si chiede a restore.sh esattamente ciò che lo snapshot contiene: i volumi
    # esclusi non sono lì e non vanno toccati (il volume vivo resta com'è).
    run(["bash", str(repo / "tools" / "restore.sh"), "--yes",
         "--volumes-only", ",".join(SNAPSHOT_VOLUMES), str(snap)], check=True)


def snapshot_latest(repo: Path) -> Path | None:
    base = repo / "backups" / "pre-update"
    if not base.is_dir():
        return None
    # per mtime, non per nome: i nomi iniziano con la versione (0.10.0 < 0.9.0
    # lessicograficamente) → l'ordinamento per stringa sceglierebbe il più vecchio
    snaps = sorted((d for d in base.iterdir() if d.is_dir()),
                   key=lambda d: d.stat().st_mtime, reverse=True)
    return snaps[0] if snaps else None


def snapshot_prune(repo: Path, keep: Path | None) -> None:
    base = repo / "backups" / "pre-update"
    if not base.is_dir():
        return
    # pota al successivo update riuscito E dopo 72h — il più tardivo dei due:
    # uno snapshot recente resta anche se un nuovo update è già riuscito.
    cutoff = time.time() - 72 * 3600
    for d in sorted(d for d in base.iterdir() if d.is_dir()):
        if keep and d == keep:
            continue
        if d.stat().st_mtime < cutoff:
            shutil.rmtree(d, ignore_errors=True)


def releases_prune(repo: Path, keep_versions: set[str]) -> None:
    base = repo / "releases"
    if not base.is_dir():
        return
    keep_names = {f"v{norm_ver(v)}" for v in keep_versions if v} | {"pre-bootstrap"}
    for d in base.iterdir():
        if d.is_dir() and d.name not in keep_names:
            shutil.rmtree(d, ignore_errors=True)


# ─────────────────────────────────────────── systemd units

def render_unit(text: str, repo: Path) -> str:
    """Sostituisce i placeholder @…@ delle unit con l'utente/home REALI.

    H43: le unit sono installate verbatim ma il deploy è parametrico su
    OPERATOR_USER. Chi esegue l'update è l'operatore stesso (l'updater gira
    come lui): i suoi dati bastano a rendere le unit corrette per QUESTA
    installazione, senza indovinare. Il repo path canonico è il --home con cui
    la CLI è invocata (VPS1777_HOME nelle unit), non un /home/<user>/vps1777
    presunto — così vale anche per un repo fuori dalla home.

    Logica pura (testabile): text in, text out."""
    try:
        pw = pwd.getpwuid(os.getuid())
        user, home = pw.pw_name, pw.pw_dir
    except KeyError:  # uid senza voce passwd: non azzardare, lascia i default
        user, home = "vps1777", "/home/vps1777"
    return (text
            .replace("@OPERATOR_USER@", user)
            .replace("@OPERATOR_HOME@", home)
            .replace("@REPO@", str(repo)))


def install_systemd_units(repo: Path, *, enable: bool) -> None:
    src = repo / "systemd"
    if not src.is_dir():
        return
    changed = False
    for unit in sorted(src.glob("vps1777-*")):
        if unit.suffix not in (".service", ".timer", ".path"):
            continue
        # .timer/.path non hanno [Service] → nessun placeholder, ma render è
        # idempotente su testo senza @…@, così il passaggio è uniforme.
        rendered = render_unit(unit.read_text(), repo).encode()
        installed = Path("/etc/systemd/system") / unit.name
        if not installed.is_file() or installed.read_bytes() != rendered:
            tmp = repo / "var" / f".{unit.name}.rendered"
            tmp.parent.mkdir(mode=0o700, exist_ok=True)
            tmp.write_bytes(rendered)
            try:
                sudo(["install", "-m", "644", str(tmp), str(installed)])
            finally:
                tmp.unlink(missing_ok=True)
            changed = True
    if changed:
        sudo(["systemctl", "daemon-reload"])
    if enable:
        units = ["vps1777-check-update.timer", "vps1777-update.path",
                 "vps1777-secrets-check.timer"]
        # auto-update SICURO: acceso solo se dichiarato in VPS1777_FEATURES (default sì).
        # Stato dichiarato AUTORITATIVO: se non è voluto, il timer va spento — una feature
        # tolta dallo stato non deve restare accesa da un install precedente (è il difetto
        # opposto della perdita silenziosa: una feature che resta accesa non richiesta).
        auto = "autoupdate" in enabled_features(repo)
        if auto:
            units.append("vps1777-auto-update.timer")
        sudo(["systemctl", "enable", "--now", *units], check=False)
        if not auto:
            sudo(["systemctl", "disable", "--now",
                  "vps1777-auto-update.timer"], check=False)


# ─────────────────────────────────────────── lock

def acquire_lock(repo: Path):
    var = repo / "var"
    var.mkdir(mode=0o700, exist_ok=True)
    fh = open(var / "update.lock", "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return None
    fh.write(f"{os.getpid()} {now_iso()}\n")
    fh.flush()
    return fh


# ─────────────────────────────────────────── intent (pulsante admin)

def consume_intent(repo: Path, path: Path, st: dict) -> str:
    """Valida e CONSUMA (cancella) l'intent del pulsante. Ritorna il target."""
    try:
        intent = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        path.unlink(missing_ok=True)
        raise RuntimeError(f"intent illeggibile: {exc}") from exc
    path.unlink(missing_ok=True)  # consume-before-act: mai due esecuzioni
    target = str(intent.get("target_version", ""))
    requested_at = intent.get("requested_at", 0)
    nonce = str(intent.get("nonce", ""))
    if not valid_semver(target):
        raise RuntimeError(f"intent: target_version non semver: '{target}'")
    try:
        age = time.time() - float(requested_at)
    except (TypeError, ValueError):
        raise RuntimeError("intent: requested_at mancante o invalido") from None
    if age > INTENT_TTL_S or age < -60:
        raise RuntimeError(f"intent scaduto ({int(age)}s > {INTENT_TTL_S}s)")
    nonces = st.setdefault("intent_nonces", [])
    if nonce and nonce in nonces:
        raise RuntimeError("intent: nonce già consumato (replay?)")
    if nonce:
        nonces.append(nonce)
        del nonces[:-50]
    # il pulsante può chiedere solo la latest nota (niente downgrade via web)
    status_file = onboarding_dir(repo) / "update_status.json"
    known_latest = ""
    if status_file.is_file():
        try:
            known_latest = json.loads(status_file.read_text()).get("latest", "")
        except json.JSONDecodeError:
            known_latest = ""
    if known_latest and norm_ver(target) != norm_ver(known_latest):
        raise RuntimeError(
            f"intent: target {target} ≠ latest nota {known_latest} — rifiutato")
    return target


# ═══════════════════════════════════════════ sottocomandi

def cmd_check(repo: Path, args) -> int:
    st = state_load(repo)
    cur = current_version(repo)
    try:
        rel = latest_release(repo)
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        warn(f"check fallito: {exc}")
        status_write(repo, error=str(exc))
        st["last_check"] = now_iso()
        state_save(repo, st)
        return 0  # mai rumore quando GitHub è irraggiungibile
    if rel is None:
        log("nessuna release pubblicata")
        status_write(repo, current=cur, latest=None, error=None)
        st["last_check"] = now_iso()
        state_save(repo, st)
        return 0
    latest = norm_ver(rel["tag_name"])
    # /releases/latest può servire risposte STANTIE dalla cache di GitHub
    # (visto dal vivo: 2 minuti dopo la publish della v0.18.0 rispondeva
    # v0.16.1, più vecchia anche della v0.17.0 di 4 ore prima). Il campo
    # `latest` per i consumatori (pagina admin, Mini App) significa "la più
    # nuova NOTA": non deve mai regredire, o la UI propone un downgrade.
    prev = ""
    sf = onboarding_dir(repo) / "update_status.json"
    if sf.is_file():
        try:
            prev = norm_ver(str(json.loads(sf.read_text()).get("latest") or ""))
        except (OSError, json.JSONDecodeError):
            prev = ""
    if (prev and valid_semver(prev) and valid_semver(latest)
            and version_key(latest) < version_key(prev)):
        log(f"GitHub riporta v{latest} ma la latest nota è v{prev}: "
            "risposta stantia della cache — tengo la nota")
        status_write(repo, current=cur, error=None)  # solo current + checked_at
        st["last_check"] = now_iso()
        state_save(repo, st)
        return 0
    excerpt = (rel.get("body") or "")[:800]
    status_write(repo, current=cur, latest=latest,
                 changelog_excerpt=excerpt, error=None,
                 html_url=rel.get("html_url", ""))
    st["last_check"] = now_iso()
    # notifica solo un VERO upgrade (mai un downgrade da risposta stantia)
    if valid_semver(latest) and valid_semver(norm_ver(cur)):
        newer = version_key(latest) > version_key(cur)
    else:
        newer = norm_ver(cur) != latest  # dev/tag non-semver: comportamento storico
    if newer:
        log(f"aggiornamento disponibile: {cur} → {latest}")
        if args.notify and st.get("last_notified_version") != latest:
            telegram_notify(
                repo,
                f"📦 vps1777 v{latest} disponibile (sei alla {cur}).\n\n"
                f"{excerpt[:500]}\n\n"
                f"Aggiorna con `vps1777 update` o dal pannello admin.")
            st["last_notified_version"] = latest
    else:
        log(f"già alla versione più recente ({cur})")
    state_save(repo, st)
    return 0


def _rollback_routine(repo: Path, st: dict, target: str, previous: str,
                      bundle: Path, snap: Path | None, need_data_restore: bool,
                      reason: str) -> int:
    warn(f"AUTO-ROLLBACK: {reason}")
    progress_write(repo, target, 90, "rollback", "running", reason)
    env = {"VPS1777_TAG": norm_ver(previous)}
    run([*compose_cmd(repo), "down"], check=False, env=env)
    rollback_dir = staging_dir(repo, previous) / "rollback-files"
    if rollback_dir.is_dir():
        restore_rollback_files(repo, rollback_dir, bundle)
    env_set(repo, "VPS1777_TAG", norm_ver(previous))
    if need_data_restore:
        if snap is None:
            warn("nessuno snapshot per il restore dati — proseguo senza")
        else:
            log("migrazione data-mutating eseguita → restore volumi dallo snapshot")
            snapshot_restore(repo, snap)
    install_systemd_units(repo, enable=False)
    run([*compose_cmd(repo), "up", "-d"], check=False, env=env)
    healthy, why = health_gate(repo, env=env)
    if healthy:
        st["update_in_progress"] = None
        st["history"].append({"event": "rolled_back", "from": target,
                              "to": previous, "at": now_iso(), "reason": reason})
        state_save(repo, st)
        progress_write(repo, target, 91, "rollback", "rolled_back", reason)
        sync_state_card(repo, previous)  # la card riflette la versione ripristinata
        telegram_notify(repo, f"❌ vps1777: update a v{norm_ver(target)} fallito "
                              f"({reason}). Rollback a v{norm_ver(previous)} riuscito.")
        ok(f"rollback a v{norm_ver(previous)} riuscito")
        return 1
    st["update_in_progress"] = None
    state_save(repo, st)
    progress_write(repo, target, 92, "rollback", "failed", why)
    backups = sorted((repo / "backups").glob("vps1777-*.tar.age"), reverse=True)
    last_age = backups[0].name if backups else "nessuno"
    telegram_notify(repo, "🆘 vps1777: update fallito E il rollback non è tornato "
                          f"healthy ({why}). Serve intervento manuale. "
                          f"Backup age disponibile: {last_age}")
    die(f"rollback non healthy ({why}) — intervento manuale richiesto", 2)
    return 2


def sync_state_card(repo: Path, version: str) -> None:
    """Best-effort: upsert della state card vps1777 su un notebook NotebookLM.

    Attiva SOLO se `.env` definisce `VPS1777_STATECARD_NB` (id notebook) —
    vuoto di default, così per gli altri utenti la feature è spenta. Scrive via
    l'entrypoint `app.statecard` nel container nb1777-mcp (che ha l'auth nlm +
    il wrapper coi fix source). NON solleva MAI: l'update è già riuscito, la
    card è un di-più; un fallimento (auth assente, MCP giù, notebook rimosso)
    si logga e si prosegue. Single-writer: solo questo flusso la scrive.
    """
    nb = env_read(repo).get("VPS1777_STATECARD_NB", "").strip()
    if not nb:
        return  # feature spenta (default): nessun notebook configurato
    try:
        cmd = [*compose_cmd(repo), "exec", "-T", "nb1777-mcp",
               "python", "-m", "app.statecard",
               "--notebook", nb, "--version", norm_ver(version)]
        res = run(cmd, capture=True, check=False, timeout=120)
        if res.returncode == 0:
            ok("state card NotebookLM aggiornata")
        else:
            detail = (res.stderr or res.stdout or "").strip()[:200]
            warn(f"state card non aggiornata (best-effort): {detail}")
    except Exception as exc:
        warn(f"state card non aggiornata (best-effort): {exc}")


# La NATURA di un segreto, che decide se il rimedio può suggerire di generarlo.
# ⚠️ Non è una comodità: è la differenza fra un rimedio e un guasto peggiore. Un
# `openssl rand` applicato a un token di BotFather produce un file **pieno e sbagliato**
# ⇒ il pre-flight torna VERDE, lo stack parte, il servizio tace — e a quel punto nessun
# controllo può più accorgersene, perché il file c'è e non è vuoto. Su
# `admin_password_bcrypt` è peggio ancora: te ne accorgi al primo login admin.
# (Isolato da setaccio leggendo setup.sh r.185-225, non dedotto.)
#
# ⚠️ E una lista scritta a mano è esattamente ciò che questa release sta togliendo di
# mezzo altrove. Qui resta, ma **non può invecchiare in silenzio**: un test in
# `tools/tests/` confronta questi nomi con i segreti realmente dichiarati nei compose e
# fallisce se ne compare uno non classificato. La lista può invecchiare — deve
# invecchiare RUMOROSAMENTE. È lo stesso patto del ledger `features.yaml`: non
# «ricordarsi di aggiornare», ma non poter dimenticare in silenzio.
SEGRETI_NON_GENERABILI = {
    "telegram_bot_token": "token rilasciato da BotFather (Telegram)",
    "cloudflared_token": "token del tunnel, dalla dashboard Cloudflare",
    "admin_password_bcrypt": "hash bcrypt di una password SCELTA (vedi secrets/README.md)",
}
SEGRETI_GENERABILI = {"gateway_secret", "archive_desc_secret", "oauth_signing_secret"}


def _compose_sorgenti(root: Path, repo: Path) -> list[Path]:
    """I compose che lo stack monta davvero, cercati sotto `root`.

    ⚠️ **Perché non si scrive la lista a mano.** Il 20/07 abbiamo trovato TRE difetti
    della stessa forma in tre punti diversi: *un posto sa che i file sono N, un altro
    ne guarda M*. Il pre-flight ne guardava uno solo mentre lo stack ne monta due
    (`compose.ingress.cloudflared.yaml` dichiara segreti); lo step 8 ne passa due
    mentre `compose_cmd` ne monta anche uno per ogni feature attiva — e `backup` è
    acceso di DEFAULT. Ogni lista scritta a mano è una copia che invecchia da sola,
    in silenzio, e il silenzio è il punto: nessuna di esse *fallisce*, tutte dicono
    di sì. Quindi la lista si deriva, invece di scriverla.

    ⚠️ MA NON È L'UNICA DERIVAZIONE, e dirlo qui è metà del suo valore. La stessa
    regola è applicata una seconda volta da `compose_cmd` (r.415-421) per costruire il
    comando docker. Le due **non sono unificate** e non sono interscambiabili:
    `compose_cmd` produce anche `extra_profiles` e NON filtra i file assenti, questa
    li filtra e non ha profili — farle chiamare l'una dall'altra cambierebbe il
    comportamento di docker, che è un secondo fix travestito da refactor. Chi tocca
    una **deve toccare l'altra**. (Trovato da b82df434 su questa docstring, che nella
    prima stesura prometteva «da qui, una volta»: un invariante che il codice non
    stabilisce. È la stessa forma del difetto (e) — una dichiarazione più larga della
    sua implementazione — comparsa nella funzione scritta per spiegarla. Non è ironia:
    è la misura di quanto la classe sia difficile da vedere dall'interno.)

    `root` è dove stanno i FILE (il repo installato, oppure il bundle di una release
    che si sta per installare); `repo` è dove sta la CONFIGURAZIONE che decide quali
    file contano (`.env`: profilo di ingress + feature attive). Sono due cose diverse
    e vanno tenute separate: il `.env` è preservato attraverso l'update, il compose no.

    ⚠️ Il `compose.yaml` base è OBBLIGATORIO e la sua assenza si SOLLEVA, non si salta.
    Gli overlay no: una release può non avere l'overlay di una feature attiva, e quello
    è un file che non c'è, non un problema. La differenza è il difetto (d) trovato su
    banco da b82df434 — sulla base, un `compose.yaml` assente restituiva `[]`, cioè
    **verde silenzioso**. Oggi quel ramo non scatta mai perché `repo/compose.yaml`
    esiste sempre; puntando ai path di un BUNDLE, un fetch parziale o un path sbagliato
    lo rende raggiungibile. **Il fix introdurrebbe un nuovo modo di avere lo stesso
    falso verde che sta riparando.** «Non ho trovato il file» non è «non c'è niente da
    segnalare»: è la distinzione che il ramo «formato illeggibile» fa già per il
    contenuto, estesa all'esistenza invece che reinventata.
    """
    base = root / "compose.yaml"
    if not base.is_file():
        raise FileNotFoundError(
            f"compose.yaml assente in {root} — il pre-flight dei segreti non può "
            f"dire né sì né no. Bundle incompleto o path errato: NON è un verde.")
    files = [base, root / f"compose.{ingress_profile(repo)}.yaml"]
    feats = enabled_features(repo)
    for feat, (file_sfx, _prof) in OPS_COMPOSE_FEATURES.items():
        if feat in feats:
            files.append(root / f"compose.{file_sfx}.yaml")
    return [f for f in files if f.is_file()]


def _secrets_mancanti(compose_paths: list[Path], secrets_root: Path) -> list[str]:
    """I segreti che i compose PRETENDONO e che sotto `secrets_root` mancano o sono vuoti.

    ⚠️ **I due argomenti sono separati apposta, e la firma è metà del fix.** Prima
    questa funzione prendeva un solo `repo` e lo usava per DUE scopi che allora
    coincidevano: dove leggere la dichiarazione, e dove cercare i file. Coincidevano
    finché il compose da controllare era quello installato. Nel momento in cui si
    controlla il compose di un *bundle*, passare il bundle come unico argomento
    cercherebbe i segreti in `bundle/secrets/` — che non esiste — e direbbe che
    mancano **tutti**: un rosso totale, credibilissimo, su una funzione nata per
    essere creduta. (Trappola vista da setaccio sul codice, prima che la scrivessi.)
    La dichiarazione viene dallo staging; i file stanno SEMPRE nel repo, perché
    `secrets/` è preservato di proposito attraverso l'update.

    Legge il compose invece di una lista scritta a mano: una lista andrebbe
    aggiornata a ogni segreto nuovo, e **il difetto che questa funzione previene è
    esattamente quello di essersene dimenticati**.

    Un file VUOTO conta come mancante: con un segreto vuoto lo stack parte e il
    canale resta fail-closed — più difficile da diagnosticare di un mancato avvio,
    perché sembra un bug della feature invece di un file da riempire.

    ⚠️ L'indentazione dei figli si MISURA, non si assume (b82df434, collaudo dei
    negativi): la prima versione pretendeva esattamente due spazi. Con quattro —
    YAML altrettanto valido — non vedeva nessun segreto e restituiva «tutto a
    posto». **Non falliva: diceva di sì.** Questa funzione esiste per proteggere
    da un cambiamento futuro che nessuno ricorderà, e un riformattatore YAML o una
    mano diversa l'avrebbero disattivata IN SILENZIO, riportando il bug che deve
    impedire. Una guardia che smette di guardare senza dirlo è peggio di nessuna
    guardia: dà un verde a chi ha imparato a fidarsene.
    """
    fuori: list[str] = []
    visti: set[tuple[str, str]] = set()
    for compose in compose_paths:
        for voce in _secrets_mancanti_in(compose, secrets_root, visti):
            if voce not in fuori:
                fuori.append(voce)
    return fuori


def _secrets_mancanti_in(compose: Path, secrets_root: Path,
                         visti: set[tuple[str, str]]) -> list[str]:
    """Un compose solo. `visti` de-duplica fra overlay: lo stesso segreto dichiarato
    in due file è un segreto solo, e va detto una volta."""
    if not compose.is_file():
        return []
    righe = compose.read_text(encoding="utf-8", errors="replace").splitlines()
    try:
        start = next(n for n, r in enumerate(righe) if r.rstrip() == "secrets:")
    except StopIteration:
        return []

    # il blocco: tutto ciò che è indentato sotto `secrets:` a livello 0
    blocco = []
    for r in righe[start + 1:]:
        if r.strip() and not r[:1].isspace():
            break                                   # tornati a colonna 0: sezione finita
        blocco.append(r)

    # l'indentazione dei figli è quella della PRIMA riga non vuota e non-commento:
    # si misura sul file reale invece di pretenderne una.
    passo = next((len(r) - len(r.lstrip()) for r in blocco
                  if r.strip() and not r.lstrip().startswith("#")), 0)
    if not passo:
        return []

    nomi: list[tuple[str, str]] = []
    corrente = ""
    for r in blocco:
        spoglia = r.strip()
        if not spoglia or spoglia.startswith("#"):
            continue
        ind = len(r) - len(r.lstrip())
        if ind == passo and spoglia.endswith(":"):
            corrente = spoglia[:-1]
        elif ind > passo and corrente and spoglia.startswith("file:"):
            nomi.append((corrente, spoglia.split(":", 1)[1].strip()))

    # ⚠️ Distinguere «nessun segreto dichiarato» da «non ho saputo leggere»:
    # la sezione c'è ed è piena, ma non ne abbiamo estratto nemmeno uno ⇒ il
    # formato è cambiato sotto di noi. Restituire [] qui sarebbe il falso verde
    # in un'altra forma, quindi si SEGNALA invece di tacere.
    if not nomi and any(r.strip() and not r.lstrip().startswith("#") for r in blocco):
        return [f"(pre-flight non ha saputo leggere la sezione `secrets:` di "
                f"{compose.name} — formato inatteso: verificare a mano prima di procedere)"]

    fuori = []
    for nome, percorso in nomi:
        if (nome, percorso) in visti:
            continue                                # già segnalato da un altro compose
        visti.add((nome, percorso))
        p = secrets_root / percorso.lstrip("./")
        # ⚠️ VUOTO = vuoto DOPO strip, non `st_size == 0` — difetto (e), riprodotto su
        # banco da b82df434: un file con solo «\n» (1 byte) o con spazi passava per
        # PIENO. Non è un caso di laboratorio: chi riempie un segreto a mano con un
        # editor lascia il newline, e `echo "" > f` scrive un byte. Lo stack parte, il
        # canale resta fail-closed, e il sintomo sembra un bug della feature — cioè
        # **esattamente il fallimento che la docstring qui sopra dichiara di prevenire.**
        # La docstring prometteva più del codice: la promessa è vecchia di oggi, il
        # codice non l'aveva mai mantenuta.
        try:
            vuoto = not p.is_file() or not p.read_text(
                encoding="utf-8", errors="replace").strip()
        except OSError:
            vuoto = True
        if vuoto:
            fuori.append(f"{nome} → {percorso}   [dichiarato in {compose.name}]")
    return fuori

def cmd_update(repo: Path, args) -> int:
    # 0 — lock
    lock = acquire_lock(repo)
    if lock is None:
        if args.from_intent:
            Path(args.from_intent).unlink(missing_ok=True)
        die("update già in corso (lock attivo)")
    st = state_load(repo)

    target_req = args.version
    if args.from_intent:
        try:
            target_req = consume_intent(repo, Path(args.from_intent), st)
            state_save(repo, st)
        except RuntimeError as exc:
            progress_write(repo, target_req or "?", 0, "intent", "failed", str(exc))
            die(f"intent rifiutato: {exc}")

    cur = current_version(repo)

    # 1 — preflight
    if run(["docker", "info"], check=False, capture=True).returncode != 0:
        die("docker non attivo")
    if norm_ver(cur) == "dev":
        die("installazione in modalità dev (immagini locali): l'update gestito "
            "richiede prima il cutover con `vps1777 bootstrap`")
    if not stack_running(repo):
        warn("lo stack non risulta in esecuzione — l'update lo avvierà comunque")
    if run(["docker", "ps", "--filter", "name=vps1777-watchtower",
            "--format", "{{.Names}}"], capture=True, check=False).stdout.strip():
        warn("profilo ops.autoupdate (Watchtower) attivo: NON supportato insieme "
             "al canale gestito — valuta di disattivarlo")
    free = shutil.disk_usage(str(repo)).free
    if free < 5 * 1024**3:
        die(f"spazio disco insufficiente ({free / 1024**3:.1f} GiB liberi, servono ≥5)")

    # 2 — risolvi target
    try:
        rel = release_by_tag(f"v{norm_ver(target_req)}") if target_req else latest_release(repo)
    except (urllib.error.URLError, OSError) as exc:
        die(f"GitHub irraggiungibile: {exc}")
    if rel is None:
        log("nessuna release pubblicata — niente da fare")
        return 0
    target = norm_ver(rel["tag_name"])
    if norm_ver(cur) == target:
        ok(f"già aggiornato (v{target})")
        return 0
    # Version-floor anti-downgrade sul canale NON interattivo (pulsante admin
    # via --from-intent): un gateway compromesso potrebbe forgiare un intent
    # verso una release più vecchia con vuln note. Il guard su update_status.json
    # non basta (è nel bind-mount scrivibile dal gateway). Il downgrade resta
    # possibile SOLO da terminale con --version esplicito (chi ha la shell può
    # già tutto).
    if args.from_intent and version_key(target) < version_key(cur):
        progress_write(repo, target, 0, "intent", "failed", "downgrade rifiutato")
        die(f"downgrade rifiutato via pulsante: v{target} < v{cur} "
            "(usa `vps1777 update --version` da terminale se intenzionale)")
    # `latest` naturale più vecchia della corrente = cache GitHub stantia
    # (/releases/latest NON è monotona, visto dal vivo): no-op, mai un
    # downgrade implicito. Con --version esplicito si passa comunque.
    if not target_req and version_key(target) < version_key(cur):
        ok(f"la release più recente nota a GitHub (v{target}) è più vecchia "
           f"della v{cur} in esecuzione — risposta stantia, niente da fare")
        return 0
    log(f"update: {cur} → {target}")

    # 3 — changelog
    body = rel.get("body") or "(nessun changelog)"
    print("\n─── Changelog ───\n" + body[:2000] + "\n─────────────────\n")

    # 4 — conferma
    if not args.yes and not args.from_intent:
        ack = input(f"Aggiorno a v{target}? [s/N]: ").strip().lower()
        if ack not in ("s", "si", "y", "yes"):
            die("annullato")

    def step(n: int, name: str, status: str = "running", detail: str = "") -> None:
        progress_write(repo, target, n, name, status, detail)

    # 4-bis — RETE DI ROLLBACK: i segreti della configurazione ATTUALE (mai fatale).
    #
    # ⚠️ QUESTO CONTROLLO NON È PIÙ QUELLO CHE PROTEGGE L'UPDATE — quello è il 6-bis.
    # Il testo che stava qui prometteva di guardare «cosa il compose PRETENDE, PRIMA di
    # toccare qualunque cosa»: vero alla lettera, e per questo nessuno ha visto che il
    # compose che pretende qualcosa di nuovo **non è ancora sul disco quando questo gira**.
    # Un commento che descrive con precisione una riga può nascondere che la riga è nel
    # posto sbagliato. Chi lo leggerà dopo di noi deve trovare scritta la DIVISIONE DEI
    # COMPITI, non solo il funzionamento: qui = il passato (rollback), 6-bis = il futuro
    # (la release che stai installando). Il `die` sta solo di là.
    #
    # `setup.sh` genera i segreti solo all'INSTALLAZIONE DA ZERO. L'update di una
    # macchina viva non lo esegue mai, e `secrets/` è fra i path preservati: quindi
    # una release che introduce un segreto NUOVO trova la cartella senza quel file.
    # E un file VUOTO è peggio di uno assente: lo stack parte e il canale resta
    # fail-closed, cioè un difetto di provisioning travestito da bug della feature.
    #
    # Non è ridondante col 6-bis, e non è «verde per costruzione» come sembra: i segreti
    # `file:` sono letti all'AVVIO del container. Se il file viene cancellato a stack
    # acceso, i container proseguono col valore già montato e il disco è vuoto — lo stack
    # è su, il verde è falso, e non ripartirebbe al primo `up`. Questo è l'unico controllo
    # che becca «il file è sparito dopo l'ultimo avvio». (Controesempio di b82df434 a
    # setaccio: due argomenti indipendenti che convergono valgono più di uno ripetuto.)
    # ⚠️ QUESTO CONTROLLO NON PUÒ FERMARE L'UPDATE — e il perché è la parte che conta.
    # Guarda i compose ATTUALI, cioè il passato. Il suo valore non è impedire di andare
    # avanti: è dire che **la rete di rollback è bucata** — se l'update fallisce e si
    # torna indietro, il compose vecchio pretende un segreto che non c'è più. È il
    # momento in cui la rete ti serve ed è proprio quello in cui scopri che non c'è.
    # Se invece facesse `die` sarebbe un LOCK-OUT: segreto X cancellato dal disco a
    # stack acceso (i container l'hanno già montato, nessuno se ne accorge) + release
    # che RIMUOVE X dal compose ⇒ l'unica release che elimina il problema diventa
    # l'unica che non puoi installare. **Un controllo che decide sul passato non deve
    # poter bloccare il futuro.** (Forma trovata da setaccio; è la stessa che ci ha
    # fatto scegliere la posizione del controllo fatale — vedi step 6-bis.)
    #
    # ⚠️ NON scrive uno status nuovo nel progress, e non è pignoleria: `update_progress.json`
    # è letto da DUE pannelli (`admin.py:988` e `miniapp.py:981-987`) che hanno una whitelist
    # implicita — conoscono solo running/failed/ok/rolled_back. Uno status `warn` in
    # admin.py cade nel ramo `else` → **pallino rosso** su un update che sta andando bene,
    # e fa mancare la condizione `p.status === 'running'` che tiene vivo il polling →
    # **il pannello si congela** mentre l'update prosegue. Un avviso scritto per informare
    # avrebbe raccontato un guasto e poi smesso di parlare. Chi scrive il produttore di un
    # file vede il campo, non la whitelist che sta dall'altra parte.
    step(4, "preflight-secrets")
    try:
        rollback_bucato = _secrets_mancanti(_compose_sorgenti(repo, repo), repo)
    except FileNotFoundError as exc:
        # Qui il compose base è quello INSTALLATO: se manca, la macchina ha un problema
        # più grande di questo update — ma non è questo controllo a doverlo decidere,
        # perché è il ramo non-fatale. Si dice e si prosegue: sarà lo stage-check a
        # fermarsi, con più contesto di quanto ne abbia il pre-flight.
        warn(f"pre-flight rollback non eseguibile: {exc}")
        rollback_bucato = []
    if rollback_bucato:
        warn("la rete di ROLLBACK è bucata — segreti che la configurazione ATTUALE "
             "pretende e che mancano o sono vuoti in secrets/:\n"
             + "".join(f"  · {m}\n" for m in rollback_bucato)
             + "L'update prosegue (questo non è un motivo per non andare avanti), ma se "
               "fallisse, il ritorno alla versione precedente troverebbe questi buchi.")

    # 5 — fetch + verifica bundle
    step(5, "fetch")
    # cosign è OBBLIGATORIO di default (fail-closed): le release sono sempre
    # firmate (release.yml) e il CLI installa cosign da sé se manca. Via
    # d'emergenza CONSAPEVOLE per sbloccarsi: VPS1777_REQUIRE_COSIGN=0 nel .env,
    # o --no-require-cosign. (systemd non carica .env → va letto qui.)
    _cosign_env = env_read(repo).get("VPS1777_REQUIRE_COSIGN", "").strip()
    require_cosign = not (getattr(args, "no_require_cosign", False) or _cosign_env == "0")
    try:
        bundle = fetch_bundle(repo, rel, require_cosign)
        lockfile = json.loads((bundle / "images.lock").read_text())
    except (RuntimeError, OSError, json.JSONDecodeError, urllib.error.URLError) as exc:
        step(5, "fetch", "failed", str(exc))
        die(f"fetch/verifica bundle fallita: {exc}")

    # 6 — self-update della CLI (poi re-exec)
    if not args.skip_self_update:
        new_cli = bundle / "tools" / "vps1777.py"
        me = Path(sys.argv[0]).resolve()
        if (new_cli.is_file() and me == Path(INSTALLED_CLI)
                and hashlib.sha256(new_cli.read_bytes()).hexdigest()
                != hashlib.sha256(me.read_bytes()).hexdigest()):
            log("CLI aggiornata nel bundle → self-update + re-exec")
            sudo(["install", "-m", "755", str(new_cli), INSTALLED_CLI])
            lock.close()
            # argv ricostruiti da zero: NIENTE --from-intent (l'intent è già
            # stato consumato/cancellato — ripassarlo farebbe morire il
            # re-exec su "intent illeggibile"); target pinnato con --version.
            new_argv = [INSTALLED_CLI, "--home", str(repo), "update",
                        "--version", target, "--yes", "--skip-self-update"]
            # propaga la via d'emergenza (il default resta obbligatorio)
            if getattr(args, "no_require_cosign", False):
                new_argv.append("--no-require-cosign")
            os.execv(INSTALLED_CLI, new_argv)

    # 6-bis — PRE-FLIGHT DEI SEGRETI SUL COMPOSE CHE SI STA INSTALLANDO (fatale).
    #
    # PERCHÉ ESISTE: il 20/07 l'update alla 0.40.0 è fallito perché la release
    # introduceva un segreto nuovo e nessun controllo se n'è accorto — lo stack non
    # è partito, health-gate rosso, rollback riuscito. Il controllo dei segreti
    # c'era già (step 4), ma legge i compose ATTUALI: **quando gira, il file che
    # dovrebbe controllare non è ancora sul disco.** Non guardava la riga sbagliata,
    # stava nel posto sbagliato — ed è per questo che, letto da solo, sembrava corretto.
    #
    # PERCHÉ QUI E NON PRIMA DEL SELF-UPDATE (la scelta costata tre giri fra noi):
    # non perché «altrimenti girerebbe la logica vecchia» — **quello è falso**, il
    # re-exec rientra in cmd_update dallo step 1 e il controllo nuovo girerebbe
    # comunque. La ragione vera è il LOCK-OUT DA FORMATO: prima del re-exec sarebbe
    # il parser della release N a leggere il compose della N+1; se la N+1 cambia il
    # formato del blocco `secrets:`, il parser vecchio cade nel ramo «non ho saputo
    # leggere» e fa die ⇒ **non puoi più installare la release che contiene il parser
    # che lo capirebbe**, e se ne esce solo a mano. Qui invece parser e compose sono
    # sempre della stessa epoca. Il prezzo è restare con CLI nuova + stack vecchio se
    # questo controllo muore — ma quello stato **si auto-guarisce** (rilanci l'update:
    # la CLI nuova col controllo nuovo ti dice cosa creare) ed è già l'esito normale
    # di ogni rollback riuscito, perché _rollback_routine non tocca la CLI.
    # ⇒ Il criterio non è «quale sbaglia meno spesso» ma «quale sbaglia in modo
    #    recuperabile»: un difetto che si ripara da solo batte uno che richiede l'uomo.
    #
    # ⚠️ FUORI dal blocco `if not args.skip_self_update`: al 6-bis si arriva per TRE
    # rami — con --skip-self-update (cioè il secondo passaggio dopo il re-exec, il
    # caso NORMALE), con la CLI del bundle identica a quella installata, e quando la
    # CLI gira da un path diverso da INSTALLED_CLI. Indentare queste righe di un
    # livello le renderebbe morte proprio nel ramo che conta.
    # Limite DICHIARATO: nel terzo ramo (uso da sviluppatore, `python3 repo/tools/…`)
    # il codice che esegue può essere di un'epoca diversa dal bundle. Non è coperto e
    # non va coperto — ma va detto qui, o qualcuno lo scoprirà come se fosse un bug.
    step(6, "preflight-secrets-bundle")
    # `_compose_sorgenti` SOLLEVA se il compose base manca nel bundle (difetto (d): un
    # bundle incompleto non deve diventare un verde). Va catturata qui, o l'eccezione
    # uscirebbe come stack trace **senza scrivere lo step `failed`**: il pannello
    # resterebbe appeso su «running» per sempre, e chi guarda da lì vedrebbe un update
    # in corso che non esiste più. Un errore che non sa raccontarsi è mezzo errore in più.
    try:
        sorgenti = _compose_sorgenti(bundle, repo)
    except FileNotFoundError as exc:
        step(6, "preflight-secrets-bundle", "failed", str(exc))
        die(f"bundle v{target} incompleto: {exc}\n"
            "Niente è stato toccato. Rilancia l'update: il bundle viene riscaricato.")
    mancanti = _secrets_mancanti(sorgenti, repo)
    if mancanti:
        step(6, "preflight-secrets-bundle", "failed", ", ".join(mancanti))
        # ⚠️ IL RIMEDIO PUÒ FABBRICARE UN GUASTO PEGGIORE DI QUELLO CHE CURA (setaccio,
        # misurato su setup.sh). I segreti NON hanno tutti la stessa natura: alcuni sono
        # valori casuali (gateway_secret, archive_desc_secret, oauth_signing_secret),
        # uno è derivato da una password scelta (admin_password_bcrypt), altri sono
        # rilasciati da un servizio esterno e **nessun valore generato è valido**
        # (telegram_bot_token, cloudflared_token). Un messaggio che desse un solo comando
        # «genera 32 byte casuali» applicato a un token produrrebbe un file pieno e
        # sbagliato: **il pre-flight tornerebbe VERDE, lo stack partirebbe, e il servizio
        # non risponderebbe** — con la differenza che a quel punto nessun controllo può
        # più accorgersene, perché il file c'è e non è vuoto. Il difetto ② non si chiude
        # togliendo `setup.sh`: si chiude non dando un comando che l'utente possa
        # applicare al segreto sbagliato. Quindi la domanda viene PRIMA del comando, e il
        # comando è esplicitamente condizionato. Non si tiene qui una tabella nome→natura:
        # sarebbe l'ennesima lista scritta a mano che invecchia in silenzio — la natura
        # sta in `secrets/README.md`, accanto al segreto che descrive.
        righe = []
        for m in mancanti:
            nome = m.split(" → ")[0].strip()
            perche = SEGRETI_NON_GENERABILI.get(nome)
            if perche:
                # ⚠️ per questi NON si stampa nessun comando: chi legge alle 23 con lo
                # stack fermo copia la riga sotto il proprio nome, non la nota in coda.
                righe.append(f"  · {m}\n      ⛔ NON generarlo con un valore casuale: è un "
                             f"{perche}.\n         Un valore casuale qui dà un file pieno e "
                             f"SBAGLIATO: lo stack parte,\n         questo controllo torna verde, "
                             f"e il guasto si vede solo all'uso.\n")
            elif nome in SEGRETI_GENERABILI:
                percorso = m.split(" → ")[1].split("   [")[0].lstrip("./")
                righe.append(f"  · {m}\n      → valore casuale, generalo:\n"
                             f"         (umask 077; openssl rand -hex 32 > {percorso})\n")
            else:
                # segreto che nessuna delle due liste conosce: si DICE che non si sa,
                # invece di indovinare. Il test che tiene sincronizzate le liste col
                # compose dovrebbe impedirlo — questo ramo è la rete sotto quel test.
                righe.append(f"  · {m}\n      ⚠️ natura non classificata: NON generarlo a caso, "
                             f"vedi secrets/README.md.\n")
        die(f"la release v{target} dichiara segreti che in secrets/ mancano o sono VUOTI:\n"
            + "".join(righe)
            + "\nLo stack NON partirebbe. L'update si ferma qui: niente è stato toccato\n"
            + "(nessun backup, nessuna immagine scaricata, stack e dati intatti).\n"
            + "L'update non genera i segreti da sé: `secrets/` è preservato di proposito.\n"
            + "Un file creato con un valore della natura sbagliata NON viene intercettato\n"
            + "da questo controllo: qui si verifica che il file ci sia e non sia vuoto,\n"
            + "non che contenga quella cosa lì.\n"
            + "\nPoi rilancia l'update: `vps1777 update`. Nessun valore passa dalla rete.\n"
            + "⛔ NON lanciare `setup.sh` per questo: è l'installatore completo e su una\n"
            + "   macchina viva fa molto più che creare un file.")
    ok(f"segreti richiesti da v{target}: tutti presenti")

    # 7 — backup (age) + snapshot locale
    step(7, "backup")
    try:
        run(["bash", str(repo / "tools" / "backup.sh")], cwd=repo)
        snap = snapshot_create(repo, cur, target)
    except (subprocess.CalledProcessError, OSError) as exc:
        step(7, "backup", "failed", str(exc))
        die(f"backup fallito — stack intatto, update annullato: {exc}")

    # 8 — stage-check sui file del bundle
    step(8, "stage-check")
    profile = ingress_profile(repo)
    staged = [bundle / "compose.yaml", bundle / f"compose.{profile}.yaml"]
    env_new = {"VPS1777_TAG": target}
    res = run([*compose_cmd(repo, files=staged), "config", "-q"],
              check=False, capture=True, env=env_new)
    if res.returncode != 0:
        step(8, "stage-check", "failed", res.stderr[:500])
        die(f"compose config sul bundle fallita:\n{res.stderr}")

    # 9 — pull + verifica digest (ultimo step abort-safe)
    step(9, "pull")
    res = run([*compose_cmd(repo, files=staged), "pull"], check=False, env=env_new)
    if res.returncode != 0:
        step(9, "pull", "failed")
        die("pull fallito — stack intatto sulla vecchia versione")
    try:
        verify_digests(repo, lockfile, target)
    except RuntimeError as exc:
        step(9, "pull", "failed", str(exc))
        for svc in SERVICES:
            run(["docker", "image", "rm", image_ref(repo, svc, target)],
                check=False, capture=True)
        die(f"verifica digest fallita — immagini rimosse, stack intatto: {exc}")

    # ─── PUNTO DI NON RITORNO ───
    # 10 — applica i file gestiti
    step(10, "apply-files")
    st["previous"] = cur
    st["previous_images"] = capture_current_images(repo, cur)
    st["update_in_progress"] = {"target": target, "step": 10, "started_at": now_iso()}
    state_save(repo, st)
    save_rollback_files(repo, cur, bundle)
    sync_managed_files(repo, bundle)
    install_systemd_units(repo, enable=False)
    env_set(repo, "VPS1777_TAG", target)

    # 11 — stop
    step(11, "stop")
    run([*compose_cmd(repo), "down"], check=False, env=env_new)

    # 12 — migrazioni
    step(12, "migrate")
    need_data_restore = False
    try:
        executed, need_data_restore = run_migrations(repo, lockfile, target)
        if executed:
            ok(f"{len(executed)} migrazioni applicate")
    except MigrationError as exc:
        return _rollback_routine(repo, st, target, cur, bundle, snap,
                                 exc.mutated, f"migrazione fallita: {exc}")
    except subprocess.CalledProcessError as exc:
        # fallimento del registro (busybox): non sappiamo cosa è successo
        # ai dati → per prudenza si ripristina lo snapshot
        return _rollback_routine(repo, st, target, cur, bundle, snap,
                                 True, f"registro migrazioni fallito: {exc}")

    # 13 — up
    step(13, "up")
    res = run([*compose_cmd(repo), "up", "-d"], check=False, env=env_new)
    if res.returncode != 0:
        return _rollback_routine(repo, st, target, cur, bundle, snap,
                                 need_data_restore, "compose up fallito")

    # 14 — health-gate
    step(14, "health-gate")
    healthy, why = health_gate(repo, env=env_new)
    if not healthy:
        return _rollback_routine(repo, st, target, cur, bundle, snap,
                                 need_data_restore, f"health-gate: {why}")

    # 15 — successo
    st["current"] = target
    st["update_in_progress"] = None
    st["history"].append({"event": "updated", "from": cur, "to": target,
                          "at": now_iso()})
    state_save(repo, st)
    prune_old_images(repo, {target, cur}, st["history"])
    snapshot_prune(repo, keep=snap)
    releases_prune(repo, {target, cur})
    # allinea la card admin subito (senza attendere il check giornaliero):
    # current=target → non mostra più "aggiornamento disponibile" stantio
    status_write(repo, current=target)
    step(15, "done", "ok")
    sync_state_card(repo, target)  # best-effort, mai bloccante
    telegram_notify(repo, f"✅ vps1777 aggiornato: v{norm_ver(cur)} → v{target}")
    ok(f"aggiornato a v{target}")
    return 0


def cmd_rollback(repo: Path, args) -> int:
    lock = acquire_lock(repo)
    if lock is None:
        die("update/rollback già in corso (lock attivo)")
    st = state_load(repo)
    cur = current_version(repo)
    prev = st.get("previous")
    if not prev:
        die("nessuna versione precedente registrata (state.json)")
    if not args.yes:
        extra = " + RESTORE DATI dallo snapshot" if args.with_data else ""
        ack = input(f"Rollback {cur} → {prev}{extra}? [s/N]: ").strip().lower()
        if ack not in ("s", "si", "y", "yes"):
            die("annullato")
    env = {"VPS1777_TAG": norm_ver(prev)}
    run([*compose_cmd(repo), "down"], check=False, env=env)
    rollback_dir = staging_dir(repo, prev) / "rollback-files"
    bundle = staging_dir(repo, cur) / "bundle"
    if rollback_dir.is_dir() and bundle.is_dir():
        restore_rollback_files(repo, rollback_dir, bundle)
    elif rollback_dir.is_dir():
        for p in rollback_dir.rglob("*"):
            if p.is_file():
                rel = p.relative_to(rollback_dir)
                (repo / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, repo / rel)
    else:
        warn("rollback-files assenti: ripristino solo il tag immagine")
    env_set(repo, "VPS1777_TAG", norm_ver(prev))
    if args.with_data:
        snap = snapshot_latest(repo)
        if snap is None:
            die("--with-data ma nessuno snapshot pre-update disponibile")
        snapshot_restore(repo, snap)
    install_systemd_units(repo, enable=False)
    run([*compose_cmd(repo), "up", "-d"], check=False, env=env)
    healthy, why = health_gate(repo, env=env)
    st["history"].append({"event": "manual_rollback", "from": cur, "to": prev,
                          "at": now_iso(), "with_data": bool(args.with_data)})
    st["current"] = prev
    st["previous"] = cur
    state_save(repo, st)
    if healthy:
        telegram_notify(repo, f"↩️ vps1777: rollback manuale a v{norm_ver(prev)} riuscito")
        ok(f"rollback a v{norm_ver(prev)} completato")
        return 0
    telegram_notify(repo, f"🆘 vps1777: rollback manuale a v{norm_ver(prev)} "
                          f"NON healthy ({why})")
    die(f"rollback applicato ma health-gate fallito: {why}", 2)
    return 2


def cmd_status(repo: Path, args) -> int:
    st = state_load(repo)
    cur = current_version(repo)
    status_file = onboarding_dir(repo) / "update_status.json"
    status = {}
    if status_file.is_file():
        try:
            status = json.loads(status_file.read_text())
        except json.JSONDecodeError:
            status = {}
    data = {
        "current": cur,
        "previous": st.get("previous"),
        "latest_known": status.get("latest"),
        "last_check": st.get("last_check"),
        "check_error": status.get("error"),
        "update_in_progress": st.get("update_in_progress"),
        "channel": release_channel(repo),
    }
    if args.probe:
        services = compose_ps(repo)
        data["services"] = {
            s.get("Service", s.get("Name", "?")): {
                "state": s.get("State"), "health": s.get("Health", "") or "-"}
            for s in services}
        data["deep_health"] = deep_health_ok(repo)
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(f"versione corrente : {data['current']}")
        print(f"precedente        : {data['previous'] or '-'}")
        print(f"latest nota       : {data['latest_known'] or '?'}")
        print(f"ultimo check      : {data['last_check'] or 'mai'}")
        if data["check_error"]:
            print(f"errore check      : {data['check_error']}")
        if data["update_in_progress"]:
            print(f"⚠ update in corso : {data['update_in_progress']}")
        if args.probe:
            for name, s in data.get("services", {}).items():
                print(f"  {name:<14} {s['state']:<10} {s['health']}")
            print(f"deep health       : {'ok' if data['deep_health'] else 'FAIL'}")
    return 0


def cmd_version(repo: Path, _args) -> int:
    cur = current_version(repo)
    bundle_ver = "?"
    vf = repo / "VERSION"
    if vf.is_file():
        bundle_ver = vf.read_text().strip()
    print(f"vps1777 CLI — tag deployato: {cur} (bundle: {bundle_ver})")
    for svc in SERVICES:
        res = run([*compose_cmd(repo), "exec", "-T", svc, "printenv",
                   "VPS1777_VERSION"], capture=True, check=False)
        ver = res.stdout.strip() if res.returncode == 0 else "n/d"
        drift = "" if ver in (norm_ver(cur), "n/d") else "  ← DRIFT"
        print(f"  {svc:<14} {ver}{drift}")
    return 0


def cmd_migrate(repo: Path, args) -> int:
    if args.pending or not args.run:
        pend = migrations_pending(repo)
        if not pend:
            ok("nessuna migrazione pendente")
        for d in pend:
            meta = json.loads((d / "migration.json").read_text())
            print(f"  {meta['id']}  ({meta.get('description', '')})")
        return 0
    cur = current_version(repo)
    images = {svc: image_ref(repo, svc, cur) for svc in SERVICES}
    lockf = staging_dir(repo, cur) / "bundle" / "images.lock"
    if lockf.is_file():
        images = json.loads(lockf.read_text())
    executed, _ = run_migrations(repo, images, cur)
    ok(f"{len(executed)} migrazioni applicate")
    return 0


def cmd_bootstrap(repo: Path, args) -> int:
    """Cutover one-shot: installazione legacy (build locale) → modello pull."""
    lock = acquire_lock(repo)
    if lock is None:
        die("update/bootstrap già in corso (lock attivo)")
    st = state_load(repo)
    if st.get("current"):
        ok(f"già a regime (v{st['current']}) — bootstrap non necessario")
        return 0

    bundle = Path(args.bundle).resolve() if args.bundle else None
    if bundle is None:
        # auto-detect: lo script gira dal bundle estratto (tools/vps1777.py)
        candidate = Path(__file__).resolve().parent.parent
        if (candidate / "bundle-manifest.json").is_file():
            bundle = candidate
    if bundle is None or not (bundle / "bundle-manifest.json").is_file():
        die("bundle non trovato: passa --bundle <dir del bundle estratto>")
    target = norm_ver((bundle / "VERSION").read_text().strip())
    lockfile = json.loads((bundle / "images.lock").read_text())
    cur = current_version(repo)
    log(f"bootstrap: installazione legacy (tag '{cur}') → v{target} (pull)")

    # preflight
    if run(["docker", "info"], check=False, capture=True).returncode != 0:
        die("docker non attivo")
    if not args.yes:
        ack = input(f"Converto questa installazione al canale update (v{target})? [s/N]: ").strip().lower()
        if ack not in ("s", "si", "y", "yes"):
            die("annullato")

    # rete di sicurezza: backup age completo pre-cutover
    backup_script = repo / "tools" / "backup.sh"
    if not backup_script.is_file():
        backup_script = bundle / "tools" / "backup.sh"
    run(["bash", str(backup_script)], cwd=repo)

    # install CLI + unit
    sudo(["install", "-m", "755", str(bundle / "tools" / "vps1777.py"), INSTALLED_CLI])
    # Dir runtime di proprietà dell'operator: su un'installazione LEGACY,
    # onboarding/ è spesso root-owned (creata da Docker al primo bind-mount, il
    # vecchio installer non la pre-creava) → CLI e gateway (stesso uid) non
    # potrebbero scrivere update_status/pending/progress. Le creiamo e ne
    # sistemiamo l'ownership all'uid del processo (l'operator). Verificato live
    # su una VPS reale: senza, check/update/pulsante falliscono con PermissionError.
    runtime_dirs = [repo / d for d in ("onboarding", "var", "backups", "releases")]
    for d in runtime_dirs:
        d.mkdir(exist_ok=True)
    sudo(["chown", "-R", f"{os.getuid()}:{os.getgid()}", *[str(d) for d in runtime_dirs]])
    (repo / "var").chmod(0o700)
    # salva i compose LEGACY per il rollback del bootstrap. Solo la PRIMA volta:
    # se pre-bootstrap esiste già (bootstrap precedente fallito e ri-tentato),
    # NON sovrascrivere — sync_managed_files ha già mutato i compose nel repo,
    # ri-salvarli catturerebbe la versione nuova e perderebbe il paracadute.
    pre = repo / "releases" / "pre-bootstrap"
    old_tag = cur
    if not pre.is_dir() or not any(pre.glob("compose*.yaml")):
        pre.mkdir(parents=True, exist_ok=True)
        for f in repo.glob("compose*.yaml"):
            shutil.copy2(f, pre / f.name)
    else:
        log("pre-bootstrap già presente (ri-tentativo): compose legacy preservati")
    sync_managed_files(repo, bundle)
    install_systemd_units(repo, enable=True)
    envd = env_read(repo)
    if "VPS1777_IMAGE_BASE" not in envd:
        first_ref = next(iter(lockfile.values()))
        base = first_ref.split("/vps1777-", 1)[0]
        env_set(repo, "VPS1777_IMAGE_BASE", base)
    env_set(repo, "VPS1777_TAG", target)

    # pull + digest check
    env_new = {"VPS1777_TAG": target}
    res = run([*compose_cmd(repo), "pull"], check=False, env=env_new)
    if res.returncode != 0:
        die("pull fallito — nulla è stato fermato, lo stack legacy gira ancora")
    verify_digests(repo, lockfile, target)

    # cutover: up ricrea i container dalle immagini ghcr; i volumi named
    # non vengono MAI rimossi/ricreati da `up` → zero perdita dati.
    res = run([*compose_cmd(repo), "up", "-d"], check=False, env=env_new)
    healthy, why = health_gate(repo, env=env_new) if res.returncode == 0 else (False, "up fallito")
    if not healthy:
        warn(f"cutover non healthy ({why}) → ripristino lo stack pre-bootstrap")
        run([*compose_cmd(repo), "down"], check=False)
        for f in pre.glob("compose*.yaml"):
            shutil.copy2(f, repo / f.name)
        env_set(repo, "VPS1777_TAG", old_tag)
        run([*compose_cmd(repo), "up", "-d"], check=False,
            env={"VPS1777_TAG": old_tag})
        telegram_notify(repo, f"🆘 vps1777: bootstrap a v{target} fallito ({why}) "
                              "— ripristinato lo stack precedente")
        die(f"bootstrap fallito ({why}) — stack precedente ripristinato", 2)

    # baseline migrazioni: le migrazioni incluse nel bundle target sono
    # considerate già riflesse nei dati (à la --fake-initial)
    reg = registry_read()
    known = {e["id"] for e in reg["applied"]}
    for d in sorted((repo / "migrations").iterdir()) if (repo / "migrations").is_dir() else []:
        if d.is_dir() and (d / "migration.json").is_file():
            meta = json.loads((d / "migration.json").read_text())
            if meta["id"] not in known:
                reg["applied"].append({
                    "id": meta["id"], "version": target, "applied_at": now_iso(),
                    "checksum": hashlib.sha256((d / "run.py").read_bytes()).hexdigest(),
                    "baseline": True})
    _registry_write(reg)

    st.update({"current": target, "previous": None, "bootstrap": True})
    st["history"].append({"event": "bootstrap", "from": old_tag, "to": target,
                          "at": now_iso()})
    state_save(repo, st)
    telegram_notify(repo, f"🔁 vps1777: installazione migrata al canale update (v{target})")
    ok(f"bootstrap completato — installazione a regime su v{target}")
    log("le vecchie immagini :dev restano come paracadute fino al primo update riuscito")
    return 0


# ─────────────────────────────────────────── archive-ingest (via NotebookLM)

_ARCH_NAME_RE = re.compile(r"[^a-z0-9_-]+")


def cmd_archive_ingest(repo: Path, args) -> int:
    """Estrae il testo di un file via NotebookLM (OCR/lettura multimodale) e lo
    indicizza nell'archivio FTS. Per immagini/scansioni che pypdf non sa leggere.

    Orchestrazione (l'host ha docker; nb1777-mcp ha l'auth nlm; il gateway ha
    l'indexer + il volume archive):
      1. copia il file in nb1777-mcp → `app.ingest` trascrive (scratch usa-e-getta)
      2. porta il testo nel gateway → `app.archive_indexer` lo indicizza nel .db
      3. archive-mcp lo scopre da solo (scan-mode). Pulizia dei temp inclusa.
    """
    src = Path(args.file).expanduser().resolve()
    if not src.is_file():
        die(f"file non trovato: {src}")
    db_name = _ARCH_NAME_RE.sub("-", (args.db or src.stem).lower()).strip("-") or "archivio"
    project = args.project or db_name
    rid = os.urandom(4).hex()
    nb_in = f"/tmp/ing_{rid}{src.suffix}"
    gw_txt = f"/tmp/ing_{rid}.txt"
    host_txt = Path(f"/tmp/vps1777_ing_{rid}.txt")
    cc = compose_cmd(repo)
    try:
        log(f"NotebookLM: trascrizione di «{src.name}» (può richiedere un minuto)…")
        run([*cc, "cp", str(src), f"nb1777-mcp:{nb_in}"], check=True)
        ecmd = [*cc, "exec", "-T", "nb1777-mcp", "python", "-m", "app.ingest", "--file", nb_in]
        if args.verify:
            ecmd.append("--verify")
        res = run(ecmd, capture=True, check=False, timeout=900)
        if res.returncode != 0:
            die(f"trascrizione fallita: {(res.stderr or res.stdout or '').strip()[:300]}")
        try:
            data = json.loads((res.stdout or "").strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError):
            die(f"output trascrizione non interpretabile: {(res.stdout or '')[:200]}")
        text = data.get("text") or ""
        if not text.strip():
            die("NotebookLM non ha restituito testo — il file è leggibile?")
        ok(f"trascritti {len(text)} caratteri da NotebookLM")
        if data.get("verification"):
            log(f"verifica NotebookLM: {data['verification'][:400]}")
        host_txt.write_text(text, encoding="utf-8")
        run([*cc, "cp", str(host_txt), f"gateway:{gw_txt}"], check=True)
        db_path = f"/var/lib/archive/db/{db_name}.db"
        res2 = run([*cc, "exec", "-T", "gateway", "python", "-m", "app.archive_indexer",
                    gw_txt, db_path, "--project", project], capture=True, check=False)
        if res2.returncode != 0:
            die(f"indicizzazione fallita: {(res2.stderr or res2.stdout or '').strip()[:300]}")
        ok(f"indicizzato nell'archivio → DB «{db_name}»: {(res2.stdout or '').strip()}")
        return 0
    finally:
        # -u root: i temp sono creati da `compose cp` (root); l'utente app (uid
        # 1000) non li potrebbe rimuovere.
        host_txt.unlink(missing_ok=True)
        run([*cc, "exec", "-u", "root", "-T", "nb1777-mcp", "rm", "-f", nb_in], check=False)
        run([*cc, "exec", "-u", "root", "-T", "gateway", "rm", "-f", gw_txt], check=False)


# ─────────────────────────────────────────── secrets-status (età + scadenze)

# Policy per secret: (file, etichetta, max_giorni, auto-rotabile?, nota su come si ruota).
# max_giorni = età oltre la quale va ruotato (promemoria, non enforcement).
# I secret OPZIONALI (presenti solo con certi profili, es. cloudflared_token con
# ingress.cloudflared) restano nella lista: se il file non c'è, il loop li salta.
_SECRET_POLICY = [
    ("oauth_signing_secret", "oauth_signing_secret.txt", "Chiave firma JWT", 90, False,
     "manuale: invalida i token attivi → i connettori si ri-autenticano / re-login admin"),
    ("admin_password", "admin_password_bcrypt.txt", "Password admin", 90, False,
     "manuale: dalla pagina o `rotate-secret.sh admin_password`"),
    ("gateway_secret", "gateway_secret.txt", "Namespace URL MCP", 180, False,
     "manuale: cambia le URL dei connettori → vanno ri-aggiunti su claude.ai"),
    # 90 giorni, non 365 (H29): è la RADICE DI FIDUCIA della Mini App — con questo
    # token si forgia un initData valido per qualunque user id. Fascia massima.
    ("telegram_bot_token", "telegram_bot_token.txt", "Token bot Telegram (radice Mini App)", 90, False,
     "manuale: revoca e rigenera su @BotFather"),
    # H37: era scoperto. Solo con ingress.cloudflared (altrimenti file assente →
    # saltato). Ruotare = rigenerare il token del tunnel nella dashboard CF.
    ("cloudflared_token", "cloudflared_token.txt", "Token tunnel Cloudflare", 365, False,
     "manuale: rigenera il token del tunnel su dash.cloudflare.com → aggiorna secrets/cloudflared_token.txt"),
]

# H37 — freschezza dei cookie NotebookLM. NON è un file in secrets/: vive nel
# volume docker nlm-auth (profiles/default/cookies.json, cfr. nb1777-mcp). Se
# scadono in silenzio, NotebookLM smette di funzionare senza spiegazione → qui
# se ne monitora la freschezza (mtime = ultima volta che il profilo è stato
# scritto/ricaricato). Soglia di PROMEMORIA, non di enforcement: nudge a
# ri-caricare da /admin/nlm prima che la sessione muoia del tutto.
NLM_COOKIE_MAX_DAYS = 14
_NLM_COOKIE_REL = "profiles/default/cookies.json"


def nlm_cookie_status(repo: Path) -> dict | None:
    """Età (giorni) dei cookie NotebookLM nel volume nlm-auth, o None se non
    determinabile (docker assente, volume/profilo non ancora caricato). Puro
    best-effort: non deve MAI far fallire secrets-status."""
    vol = f"vps1777_{NLM_AUTH_VOLUME}"
    try:
        res = run(["docker", "run", "--rm", "--network", "none",
                   "-v", f"{vol}:/src:ro", "--entrypoint", "sh", "busybox:latest",
                   "-c", f"stat -c %Y /src/{_NLM_COOKIE_REL}"],
                  check=False, capture=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0:
        return None  # profilo mai caricato o volume assente: non è un errore
    try:
        mtime = int((res.stdout or "").strip())
    except ValueError:
        return None
    now = time.time()
    age_days = int((now - mtime) / 86400)
    return {
        "name": "nlm_cookies", "label": "Cookie sessione NotebookLM",
        "age_days": age_days, "max_age_days": NLM_COOKIE_MAX_DAYS,
        "overdue": age_days > NLM_COOKIE_MAX_DAYS, "auto_rotatable": False,
        "note": "ricarica il profilo NotebookLM da /admin/nlm (i cookie Google scadono)",
        "last_rotated": datetime.fromtimestamp(mtime, timezone.utc)
                        .strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def cmd_secrets_status(repo: Path, args) -> int:
    """Età e scadenze dei secret. Scrive onboarding/secrets_status.json (letto
    dalla pagina /admin/secrets) e — con --notify — avvisa su Telegram quelli
    scaduti. L'età deriva dall'mtime del file (riscritto a ogni rotazione)."""
    import time as _t
    now = _t.time()
    items: list[dict] = []
    overdue: list[str] = []
    for name, fname, label, max_days, auto, note in _SECRET_POLICY:
        p = repo / "secrets" / fname
        if not p.is_file():
            continue
        age_days = int((now - p.stat().st_mtime) / 86400)
        is_overdue = age_days > max_days
        items.append({
            "name": name, "label": label, "age_days": age_days, "max_age_days": max_days,
            "overdue": is_overdue, "auto_rotatable": auto, "note": note,
            "last_rotated": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)
                            .strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
        if is_overdue:
            overdue.append(f"{label} ({age_days}g)")
    # H37: freschezza cookie NotebookLM (volume nlm-auth, non un file secrets/).
    # Best-effort: se il profilo non è ancora caricato o docker non c'è, si salta.
    nlm = nlm_cookie_status(repo)
    if nlm is not None:
        items.append(nlm)
        if nlm["overdue"]:
            overdue.append(f"{nlm['label']} ({nlm['age_days']}g)")
    status = {"checked_at": now_iso(), "secrets": items}
    try:
        (onboarding_dir(repo) / "secrets_status.json").write_text(json.dumps(status, indent=2))
    except OSError as exc:
        warn(f"scrittura secrets_status.json fallita: {exc}")

    for it in items:
        mark = "⚠️  SCADUTO" if it["overdue"] else "ok"
        log(f"{it['label']:<22} {it['age_days']:>4}g / max {it['max_age_days']}g  [{mark}]")
    if not items:
        warn("nessun secret trovato in secrets/")
    if overdue:
        warn(f"da ruotare: {', '.join(overdue)}")
        if args.notify:
            telegram_notify(repo, "🔑 vps1777 — secret da ruotare:\n• " + "\n• ".join(overdue))
    else:
        ok("tutti i secret entro la soglia")
    return 0


# ─────────────────────────────────────────── main

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="vps1777", description="canale di aggiornamento controllato vps1777")
    parser.add_argument("--home", help="root del repo sulla VPS (default: $VPS1777_HOME o /home/vps1777/vps1777)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("check", help="controlla l'ultima release")
    p.add_argument("--notify", action="store_true", help="notifica Telegram se c'è una versione nuova")

    p = sub.add_parser("update", help="aggiorna alla release più recente (o --version)")
    p.add_argument("--version", help="target esplicito (vX.Y.Z), es. per le rc")
    p.add_argument("--yes", action="store_true", help="nessuna conferma")
    p.add_argument("--from-intent", help="path dell'intent file scritto dal pulsante admin")
    p.add_argument("--require-cosign", action="store_true",
                   help="(ridondante: la verifica cosign è già obbligatoria di default)")
    p.add_argument("--no-require-cosign", action="store_true",
                   help="VIA D'EMERGENZA: salta la verifica firma cosign (sconsigliato)")
    p.add_argument("--skip-self-update", action="store_true", help=argparse.SUPPRESS)

    p = sub.add_parser("rollback", help="torna alla versione precedente")
    p.add_argument("--with-data", action="store_true", help="ripristina anche i volumi dallo snapshot")
    p.add_argument("--yes", action="store_true")

    p = sub.add_parser("status", help="stato del canale update")
    p.add_argument("--json", action="store_true")
    p.add_argument("--probe", action="store_true", help="interroga anche i container")

    sub.add_parser("version", help="versioni deployate (tag + container)")

    p = sub.add_parser("migrate", help="runner migrazioni")
    p.add_argument("--pending", action="store_true", help="elenca le pendenti")
    p.add_argument("--run", action="store_true", help="applica le pendenti")

    p = sub.add_parser("bootstrap", help="cutover one-shot da installazione legacy")
    p.add_argument("--bundle", help="dir del bundle estratto (default: auto-detect)")
    p.add_argument("--yes", action="store_true")

    p = sub.add_parser("archive-ingest", help="indicizza un file nell'archivio via NotebookLM (OCR/lettura multimodale)")
    p.add_argument("file", help="file da estrarre (PDF-immagine, scansione, doc…)")
    p.add_argument("--db", help="nome del DB archivio (default: dal nome file)")
    p.add_argument("--project", help="etichetta progetto (default: nome DB)")
    p.add_argument("--verify", action="store_true", help="chiedi a NotebookLM di verificare la trascrizione")

    p = sub.add_parser("secrets-status", help="età e scadenze dei secret (+ notifica Telegram)")
    p.add_argument("--notify", action="store_true", help="notifica Telegram i secret scaduti")

    args = parser.parse_args()
    repo = find_repo(args.home)
    os.chdir(repo)

    handlers = {"check": cmd_check, "update": cmd_update, "rollback": cmd_rollback,
                "status": cmd_status, "version": cmd_version,
                "migrate": cmd_migrate, "bootstrap": cmd_bootstrap,
                "archive-ingest": cmd_archive_ingest,
                "secrets-status": cmd_secrets_status}
    try:
        return handlers[args.cmd](repo, args)
    except KeyboardInterrupt:
        die("interrotto")
        return 130


if __name__ == "__main__":
    sys.exit(main())
