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
DATA_VOLUMES = ["gateway-data", "archive-data", "nlm-auth"]
# Path canonico di mount di ogni volume nei container one-off delle migrazioni.
VOLUME_MOUNTS = {
    "gateway-data": "/var/lib/gateway",
    "archive-data": "/var/lib/archive",
    "nlm-auth": "/var/lib/nlm",
}
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


def compose_cmd(repo: Path, *, files: list[Path] | None = None) -> list[str]:
    profile = ingress_profile(repo)
    if files is None:
        files = [repo / "compose.yaml", repo / f"compose.{profile}.yaml"]
    cmd = ["docker", "compose", "--project-directory", str(repo)]
    for f in files:
        cmd += ["-f", str(f)]
    cmd += ["--profile", profile]
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

    # cosign: obbligatorio solo se richiesto; se presente, comunque usato
    cosign = shutil.which("cosign")
    if require_cosign and not cosign:
        raise RuntimeError("--require-cosign ma cosign non è installato")
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
    dest = staging_dir(repo, version) / "rollback-files"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
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

def snapshot_create(repo: Path, from_version: str, to_version: str) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    snap = repo / "backups" / "pre-update" / f"{norm_ver(to_version)}-{ts}"
    snap.mkdir(parents=True, exist_ok=True)
    snap.chmod(0o700)
    for vol in DATA_VOLUMES:
        log(f"snapshot volume {vol}…")
        run(["docker", "run", "--rm",
             "-v", f"vps1777_{vol}:/src:ro", "-v", f"{snap}:/dst",
             "--entrypoint", "sh", "busybox:latest",
             "-c", f"cd /src && tar cf /dst/{vol}.tar ."], check=True)
    (snap / "meta.json").write_text(json.dumps({
        "from_version": from_version, "to_version": to_version,
        "created_at": now_iso(), "volumes": DATA_VOLUMES}, indent=2) + "\n")
    ok(f"snapshot locale: {snap}")
    return snap


def snapshot_restore(repo: Path, snap: Path) -> None:
    run(["bash", str(repo / "tools" / "restore.sh"), "--yes",
         "--volumes-only", ",".join(DATA_VOLUMES), str(snap)], check=True)


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

def install_systemd_units(repo: Path, *, enable: bool) -> None:
    src = repo / "systemd"
    if not src.is_dir():
        return
    changed = False
    for unit in sorted(src.glob("vps1777-*")):
        if unit.suffix not in (".service", ".timer", ".path"):
            continue
        installed = Path("/etc/systemd/system") / unit.name
        if not installed.is_file() or installed.read_bytes() != unit.read_bytes():
            sudo(["install", "-m", "644", str(unit), str(installed)])
            changed = True
    if changed:
        sudo(["systemctl", "daemon-reload"])
    if enable:
        sudo(["systemctl", "enable", "--now",
              "vps1777-check-update.timer", "vps1777-update.path"], check=False)


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
    excerpt = (rel.get("body") or "")[:800]
    status_write(repo, current=cur, latest=latest,
                 changelog_excerpt=excerpt, error=None,
                 html_url=rel.get("html_url", ""))
    st["last_check"] = now_iso()
    if norm_ver(cur) != latest:
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
    # già tutto). `latest` naturale non downgrada mai.
    if args.from_intent and version_key(target) < version_key(cur):
        progress_write(repo, target, 0, "intent", "failed", "downgrade rifiutato")
        die(f"downgrade rifiutato via pulsante: v{target} < v{cur} "
            "(usa `vps1777 update --version` da terminale se intenzionale)")
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

    # 5 — fetch + verifica bundle
    step(5, "fetch")
    # require_cosign: flag CLI OPPURE VPS1777_REQUIRE_COSIGN=1 in .env/env
    # (systemd non carica .env → va letto qui, non solo da os.environ).
    require_cosign = (args.require_cosign
                      or env_read(repo).get("VPS1777_REQUIRE_COSIGN") == "1")
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
            if args.require_cosign:
                new_argv.append("--require-cosign")
            os.execv(INSTALLED_CLI, new_argv)

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
                   default=os.environ.get("VPS1777_REQUIRE_COSIGN") == "1",
                   help="fallisci se la verifica cosign non è possibile")
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

    args = parser.parse_args()
    repo = find_repo(args.home)
    os.chdir(repo)

    handlers = {"check": cmd_check, "update": cmd_update, "rollback": cmd_rollback,
                "status": cmd_status, "version": cmd_version,
                "migrate": cmd_migrate, "bootstrap": cmd_bootstrap}
    try:
        return handlers[args.cmd](repo, args)
    except KeyboardInterrupt:
        die("interrotto")
        return 130


if __name__ == "__main__":
    sys.exit(main())
