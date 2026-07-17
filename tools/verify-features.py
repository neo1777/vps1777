#!/usr/bin/env python3
# BOZZA per tools/verify-features.py nel repo vps1777 — penna: b82df434 (schema+verificatore).
# Da mergiare in main da 71d540e6 (corsia release). Vedi sequenza anti-cozzo.
"""verify-features.py — il verificatore del ledger delle feature (features.yaml).

Gira in CI (GitHub Actions) — NON è un daemon, NON gira in produzione né sul PC utente.
È il muscolo della regola d'oro di Neo: «non perdere MAI una funzione, anche cambiando
sessione/LLM». Un LLM nuovo non deve RICORDARE le feature: lancia questo, e le SCOPRE —
e scopre se la realtà combacia col dichiarato.

Fa TRE controlli (exit != 0 se un controllo DURO fallisce):

  1. SCHEMA          ogni voce ha i campi obbligatori; status valido; la regola di
                     cattura (deferred ⇒ follow_up) è rispettata.
  2. DICHIARATO→REALE  ogni feature attiva* deve superare il suo `verify`. Una feature
                     dichiarata ma SPARITA dal codice → FALLIMENTO. Cattura la PERDITA.
  3. REALE→DICHIARATO  ogni tool MCP / systemd-unit / profilo compose REALE deve avere
                     una voce nel ledger. Reale ma NON dichiarato → segnalato (e, se
                     `_meta.baseline_completo: true`, FALLIMENTO). Cattura ciò che entra
                     senza traccia e POI si dimentica.

Più una SORVEGLIANZA (non fa fallire): i follow_up a-giudizio oltre `rivedi_dopo` e i
deferred il cui follow_up verificabile è ORA soddisfatto (pronti a promozione).

Perché due modalità sul controllo 3: durante la SEMINA il ledger è incompleto → il
reale→dichiarato griderebbe su tutto. Quindi finché `_meta.baseline_completo` è falso,
il verso 3 REPORTA (dice cosa manca, utile a chi semina); quando la semina è finita si
mette il flag a true e diventa DURO (cattura ogni feature nuova non dichiarata).
"""
from __future__ import annotations

import argparse
import datetime
import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("verify-features: manca PyYAML (pip install pyyaml / uv add pyyaml)")

REQUIRED = ("id", "nome", "cosa", "dove", "status", "verify")
STATUSES = ("active-default", "opt-in", "deferred", "removed")
# gli status che DEVONO essere reali adesso (il verso dichiarato→reale li controlla).
# 'deferred' e 'removed' NON si controllano contro il reale: il primo non c'è ANCORA,
# il secondo non c'è PIÙ di proposito — la loro assenza è corretta, non un guasto.
ACTIVE = ("active-default", "opt-in")


# ── esecuzione di un singolo `verify`/`follow_up.verify` ──────────────────────
def run_check(spec: dict, repo: Path) -> tuple[bool, str]:
    """Ritorna (ok, dettaglio). `spec` è un dict con UNA chiave fra i tipi noti.
    `manual` non è né ok né non-ok: ritorna (None, ...) e il chiamante lo tratta a parte."""
    if not isinstance(spec, dict) or len(spec) != 1:
        return False, f"verify malformato (serve UNA chiave fra i tipi): {spec!r}"
    kind, arg = next(iter(spec.items()))

    if kind == "manual":
        return None, f"[manuale] {arg}"

    if kind == "path_exists":
        p = repo / arg
        return p.exists(), f"path {'esiste' if p.exists() else 'MANCA'}: {arg}"

    if kind == "file_contains":
        p = repo / arg["path"]
        if not p.exists():
            return False, f"file MANCA: {arg['path']}"
        hit = re.search(arg["pattern"], p.read_text(errors="replace"))
        return bool(hit), f"pattern {'trovato' if hit else 'ASSENTE'} in {arg['path']}"

    if kind == "grep_count":
        p = repo / arg["path"]
        base = p if p.exists() else None
        if base is None:
            return False, f"path MANCA: {arg['path']}"
        files = list(base.rglob("*")) if base.is_dir() else [base]
        n = sum(len(re.findall(arg["pattern"], f.read_text(errors="replace")))
                for f in files if f.is_file())
        ok = n >= arg.get("min", 1)
        return ok, f"{n} occorrenze di /{arg['pattern']}/ (min {arg.get('min', 1)})"

    if kind == "systemd_unit":
        p = repo / "systemd" / arg
        return p.exists(), f"systemd/{arg} {'esiste' if p.exists() else 'MANCA'}"

    if kind == "compose_profile":
        p = repo / arg["file"]
        if not p.exists():
            return False, f"compose MANCA: {arg['file']}"
        hit = arg["profile"] in p.read_text(errors="replace")
        return hit, f"profilo {arg['profile']} {'dichiarato' if hit else 'ASSENTE'} in {arg['file']}"

    if kind == "mcp_tool":
        # il tool è registrato se il file del server ha @mcp.tool poi def <name>
        svc = repo / "services" / arg["service"] / "app"
        if not svc.exists():
            return False, f"servizio MANCA: {arg['service']}"
        want = arg["name"]
        for f in svc.rglob("*.py"):
            txt = f.read_text(errors="replace")
            if re.search(r"@mcp\.tool[\s\S]{0,200}?def\s+" + re.escape(want) + r"\b", txt):
                return True, f"tool MCP {arg['service']}/{want} registrato"
        return False, f"tool MCP {arg['service']}/{want} NON registrato"

    if kind == "cmd":
        r = subprocess.run(arg, shell=True, cwd=repo, capture_output=True, text=True)
        return r.returncode == 0, f"`{arg}` exit {r.returncode}"

    return False, f"tipo di verify sconosciuto: {kind}"


# ── enumeratori del REALE (per il verso reale→dichiarato) ─────────────────────
def enum_reality(repo: Path) -> dict[str, set[str]]:
    """Cosa ESISTE davvero nel repo, per categoria. Ogni chiave qui DEVE trovare una
    voce nel ledger, o il verso reale→dichiarato segnala/fallisce."""
    real: dict[str, set[str]] = {"mcp_tool": set(), "systemd_unit": set(), "compose_profile": set()}

    svc = repo / "services"
    if svc.exists():
        for f in svc.rglob("*.py"):
            if ".venv" in f.parts:
                continue
            service = None
            for i, part in enumerate(f.parts):
                if part == "services" and i + 1 < len(f.parts):
                    service = f.parts[i + 1]
                    break
            for m in re.finditer(r"@mcp\.tool[\s\S]{0,200}?def\s+(\w+)", f.read_text(errors="replace")):
                real["mcp_tool"].add(f"{service}/{m.group(1)}")

    sysd = repo / "systemd"
    if sysd.exists():
        for f in sysd.iterdir():
            if f.suffix in (".service", ".timer", ".path"):
                real["systemd_unit"].add(f.name)

    for comp in repo.glob("compose*.yaml"):
        for m in re.finditer(r"profiles:\s*\[([^\]]+)\]", comp.read_text(errors="replace")):
            for prof in m.group(1).split(","):
                real["compose_profile"].add(prof.strip())
    return real


def _keys_of(e: dict) -> dict[str, set[str]]:
    """Le chiavi-reali che UNA voce dichiara, lette da `verify`, `follow_up.verify` E
    `dove`. Leggere anche `dove` (non solo verify) è ciò che permette a una voce con
    verify `manual` — es. un `removed` — di risultare comunque DICHIARATA per la sua
    coordinata (il buco fine trovato da setaccio: un profilo removed con verify manual
    veniva dato per non-dichiarato)."""
    k: dict[str, set[str]] = {"mcp_tool": set(), "systemd_unit": set(), "compose_profile": set()}
    for spec in (e.get("verify"), (e.get("follow_up") or {}).get("verify")):
        if isinstance(spec, dict):
            if "mcp_tool" in spec:
                k["mcp_tool"].add(f"{spec['mcp_tool']['service']}/{spec['mcp_tool']['name']}")
            elif "systemd_unit" in spec:
                k["systemd_unit"].add(spec["systemd_unit"])
            elif "compose_profile" in spec:
                k["compose_profile"].add(spec["compose_profile"]["profile"])
    # dove: "compose-profile:<file>#<profilo>" · "mcp-tool:<svc>/<nome>" · "systemd:<unit>"
    for d in e.get("dove", []):
        if d.startswith("compose-profile:") and "#" in d:
            k["compose_profile"].add(d.split("#", 1)[1])
        elif d.startswith("mcp-tool:"):
            k["mcp_tool"].add(d.split(":", 1)[1])
        elif d.startswith("systemd:"):
            k["systemd_unit"].add(d.split(":", 1)[1])
    return k


def main() -> int:
    ap = argparse.ArgumentParser(description="Verifica il ledger delle feature vps1777")
    ap.add_argument("--ledger", default="features.yaml", type=Path)
    ap.add_argument("--repo", default=".", type=Path, help="radice del repo vps1777")
    a = ap.parse_args()
    repo = a.repo.resolve()

    doc = yaml.safe_load((repo / a.ledger).read_text()) if not a.ledger.is_absolute() \
        else yaml.safe_load(a.ledger.read_text())
    entries = doc.get("features", [])
    baseline_completo = (doc.get("_meta") or {}).get("baseline_completo", False)
    oggi = datetime.date.today()

    hard_fail: list[str] = []      # fanno uscire != 0
    surveil: list[str] = []        # solo segnalati

    # ── 1. SCHEMA + regola di cattura ─────────────────────────────────────────
    ids = set()
    for e in entries:
        eid = e.get("id", "<senza id>")
        for k in REQUIRED:
            if k not in e:
                hard_fail.append(f"[schema] {eid}: manca il campo obbligatorio '{k}'")
        if e.get("status") not in STATUSES:
            hard_fail.append(f"[schema] {eid}: status '{e.get('status')}' non valido {STATUSES}")
        if eid in ids:
            hard_fail.append(f"[schema] id duplicato: {eid}")
        ids.add(eid)
        # REGOLA DI CATTURA (setaccio): una deferred è una decisione a metà finché non
        # dichiara COSA la chiude. Il follow_up è il cuore anti-amnesia — è ciò che
        # mancava a Watchtower. Lo pretendiamo SEMPRE su una deferred, senza scampo:
        # un `verify` non lo sostituisce (il verify prova la presenza, il follow_up
        # dice cosa manca perché sia presente).
        if e.get("status") == "deferred" and not e.get("follow_up"):
            hard_fail.append(f"[cattura] {eid}: 'deferred' senza follow_up — decisione a metà "
                             "(è ESATTAMENTE il buco che ha perso Watchtower per un mese)")
        if e.get("status") in ("deferred", "removed", "opt-in") and not e.get("decisione"):
            hard_fail.append(f"[cattura] {eid}: '{e['status']}' senza 'decisione' — invisibile "
                             "allo storico (perché/quando fu deciso?)")

    # ── 2. DICHIARATO → REALE (cattura la PERDITA) ────────────────────────────
    for e in entries:
        if e.get("status") not in ACTIVE:
            continue
        ok, det = run_check(e.get("verify", {}), repo)
        if ok is None:      # manual
            surveil.append(f"[manuale] {e['id']}: {det} — verifica umana, non automatizzabile")
        elif not ok:
            hard_fail.append(f"[PERDITA] {e['id']} è dichiarata '{e['status']}' ma il verify "
                             f"FALLISCE: {det}. La feature è sparita, o la voce mente.")

    # ── 3. REALE → DICHIARATO (cattura ciò che poi si dimentica) ──────────────
    # Tre vie, non due (raffinamento dal buco fine di setaccio):
    #   reale + dichiarato present (active/opt-in) → OK
    #   reale + dichiarato removed                 → STATO≠REALTÀ (l'hai detto tolto, c'è ancora)
    #   reale + nessuna voce                       → NON DICHIARATO (aggiungi la voce)
    # (reale + deferred lo copre la sorveglianza [PROMUOVI] più sotto: è pronto a promozione.)
    real = enum_reality(repo)
    present: dict[str, set[str]] = {c: set() for c in real}
    accounted: dict[str, set[str]] = {c: set() for c in real}
    removed_keys: dict[str, set[str]] = {c: set() for c in real}
    for e in entries:
        keys = _keys_of(e)
        for c in real:
            accounted[c] |= keys[c]
            if e.get("status") in ACTIVE:
                present[c] |= keys[c]
            if e.get("status") == "removed":
                removed_keys[c] |= keys[c]
    for cat in real:
        for u in sorted(real[cat]):
            if u not in accounted[cat]:
                msg = f"[NON DICHIARATO] {cat} '{u}' esiste nel codice ma NON è nel ledger"
                (hard_fail if baseline_completo else surveil).append(
                    msg + ("" if baseline_completo else " (semina in corso: segnalato, non-fatale)"))
            elif u in removed_keys[cat]:
                msg = (f"[STATO≠REALTÀ] {cat} '{u}' è nel ledger come 'removed' ma ESISTE ancora "
                       "nel repo: togli l'artefatto (se davvero rimosso) o cambia status "
                       "(es. opt-in, se resta disponibile ma declassato)")
                (hard_fail if baseline_completo else surveil).append(msg)

    # ── SORVEGLIANZA: follow_up a-giudizio scaduti + verificabili pronti ──────
    for e in entries:
        fu = e.get("follow_up") or {}
        man = fu.get("manuale")
        if man and man.get("rivedi_dopo"):
            due = datetime.date.fromisoformat(str(man["rivedi_dopo"]))
            if oggi > due:
                surveil.append(f"[RIVEDI] {e['id']}: rinvio-a-giudizio scaduto il {due} "
                               f"(«{man.get('cosa', '')}») — rimettilo in discussione")
        if e.get("status") == "deferred" and isinstance(fu.get("verify"), dict):
            ok, det = run_check(fu["verify"], repo)
            if ok:
                surveil.append(f"[PROMUOVI] {e['id']}: il follow_up verificabile è ORA soddisfatto "
                               f"({det}) — la deferred può passare ad active-default")

    # ── REFERTO ───────────────────────────────────────────────────────────────
    print(f"── ledger: {len(entries)} voci · baseline_completo={baseline_completo} · {oggi} ──")
    for s in surveil:
        print(f"  ⚠ {s}")
    for h in hard_fail:
        print(f"  ✗ {h}")
    if hard_fail:
        print(f"\n  ✗ {len(hard_fail)} FALLIMENTI DURI. Il ledger e la realtà divergono: "
              "chiudi il divario o dichiara il cambio.")
        return 1
    print(f"\n  ✓ ledger e realtà QUADRANO ({len(surveil)} segnalazioni da guardare, 0 fallimenti).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
