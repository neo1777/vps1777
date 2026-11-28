#!/usr/bin/env python3
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
import ast
import datetime
import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    # 2 = non ho potuto misurare (manca uno strumento), non 1 = ho misurato ed è rosso
    print("verify-features: manca PyYAML (pip install pyyaml / uv add pyyaml)", file=sys.stderr)
    sys.exit(2)

CMD_TIMEOUT_S = 600     # un `verify: cmd` che non finisce non tiene ferma la CI
REQUIRED = ("id", "nome", "cosa", "dove", "status", "verify")
STATUSES = ("active-default", "opt-in", "deferred", "removed")
# 🔴 CATEGORIE ENTRATE NELL'ENUMERAZIONE DOPO CHE `baseline_completo` ERA GIÀ `true`.
#   Il flag non è una proprietà del ledger: è una proprietà **delle categorie che
#   `enum_reality` guardava QUANDO è stato messo a true**. Aggiungerne una senza dirlo
#   trasformerebbe la sua promessa («tutto ciò che esiste è dichiarato») in una bugia
#   retroattiva, e lo farebbe con 20 fallimenti duri in un colpo.
# ⭐ Quindi ogni categoria nuova ha la SUA semina: segnalata, non fatale, finché le sue
#   voci non sono scritte. Poi si toglie da qui — e da quel momento è dura come le altre.
# `cli_command` è uscita dalla semina il 02/08 nello stesso commit che l'ha creata:
# le sue dieci voci sono state scritte subito, quindi non c'è un intervallo in cui
# la categoria segnala e nessuno agisce. Una semina che dura è una segnalazione che
# si impara a ignorare.
# ⏳ E una semina ha una FINE (DER-03 dello standard: «una semina che dura è una segnalazione
#   che si impara a ignorare»). `tools_script` era in semina dal 02/08 senza data (rilievo di
#   Sagoma, 24/11); Neo ha scelto il 31/01/2027, la stessa data di QUA-04 (scelta
#   2026-11-25-soglia-tools-script-semina). Dal giorno dopo i non dichiarati sono fallimenti duri.
CATEGORIE_IN_SEMINA = {"tools_script": "2027-01-31"}
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
    verifica = _VERIFICHE.get(kind)
    if verifica is None:
        return False, f"tipo di verify sconosciuto: {kind}"
    return verifica(arg, repo)



def _v_path_exists(arg, repo: Path) -> tuple[bool, str]:
    p = repo / arg
    return p.exists(), f"path {'esiste' if p.exists() else 'MANCA'}: {arg}"


def _v_file_contains(arg, repo: Path) -> tuple[bool, str]:
    p = repo / arg["path"]
    if not p.exists():
        return False, f"file MANCA: {arg['path']}"
    hit = re.search(arg["pattern"], p.read_text(errors="replace"))
    return bool(hit), f"pattern {'trovato' if hit else 'ASSENTE'} in {arg['path']}"


def _v_python_def(arg, repo: Path) -> tuple[bool, str]:
    # `file_contains` con pattern «def nome_funzione» era il controllo più usato di
    # questo registro (dieci voci su sedici), ed è il caso in cui una ricerca testuale
    # è più debole di quanto sembri: la stessa stringa passa anche se sta in un
    # commento, in una docstring, dentro un'altra stringa, o se il file NON SI COMPILA.
    # 🔑 Il rilievo è dell'audit del round-11 e regge: `tools/prove-empiriche/
    # prova-8-le-unit-si-comportano-come-dichiarano.sh` condanna il match di
    # sottostringa, e questo registro lo praticava. Qui non si esegue nulla — si
    # legge l'ALBERO SINTATTICO, che è strettamente più forte del testo e non ha
    # gli effetti collaterali di un import.
    #
    # ⚠️ COSA NON PROVA, e va detto perché il difetto che cura nasce dal non dirlo:
    #    che la funzione sia CHIAMATA · che il file sia importato da qualcuno ·
    #    che la feature sia ACCESA a runtime. Prova che è DEFINITA, e che il file
    #    che la contiene è codice Python valido. Per il resto ci sono `mcp_tool`,
    #    `systemd_unit` e le prove empiriche.
    p = repo / arg["path"]
    if not p.exists():
        return False, f"file MANCA: {arg['path']}"
    try:
        albero = ast.parse(p.read_text(errors="replace"))
    except SyntaxError as e:
        return False, (f"{arg['path']} NON SI COMPILA (riga {e.lineno}): "
                       f"una ricerca testuale non se ne sarebbe accorta")
    nomi = {n.name for n in ast.walk(albero)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    ok = arg["name"] in nomi
    return ok, (f"{arg['name']} {'DEFINITA' if ok else 'NON definita'} in "
                f"{arg['path']} (albero sintattico, non testo)")


def _v_grep_count(arg, repo: Path) -> tuple[bool, str]:
    p = repo / arg["path"]
    base = p if p.exists() else None
    if base is None:
        return False, f"path MANCA: {arg['path']}"
    files = list(base.rglob("*")) if base.is_dir() else [base]
    n = sum(len(re.findall(arg["pattern"], f.read_text(errors="replace")))
            for f in files if f.is_file())
    ok = n >= arg.get("min", 1)
    return ok, f"{n} occorrenze di /{arg['pattern']}/ (min {arg.get('min', 1)})"


def _v_cli_command(arg, repo: Path) -> tuple[bool, str]:
    # 🔴 PERCHÉ DUE CONDIZIONI E NON UNA (b82df434, 02/08). Un sottocomando vive
    # in DUE posti: l'`add_parser` che lo fa accettare dalla riga di comando, e
    # la mappa nome→funzione che lo esegue. **Divergono**: un `add_parser` senza
    # voce nella mappa fa sì che `vps1777 <cmd>` venga accettato e non faccia
    # NIENTE — o cada con un KeyError che si legge come un bug del comando invece
    # che come un comando mai collegato.
    # ⇒ «esiste» qui vuol dire ENTRAMBE. Provarne una sola darebbe un verde su
    # metà della cosa, che è la classe che questo ledger esiste per chiudere.
    cli = repo / "tools" / "vps1777.py"
    if not cli.is_file():
        # Senza la CLI non c'è niente in cui cercare il comando: una voce rossa che lo dice,
        # non un FileNotFoundError che ferma tutto il referto (rilievo di Sagoma, 25/11).
        return False, f"{arg}: tools/vps1777.py MANCA ⇒ nessun sottocomando da cercare"
    src = cli.read_text(errors="replace")
    nel_parser = f'sub.add_parser("{arg}"' in src
    nel_dispatch = f'"{arg}": cmd_' in src
    ok = nel_parser and nel_dispatch
    return ok, (f"{arg}: parser {'sì' if nel_parser else 'NO'} · "
                f"dispatcher {'sì' if nel_dispatch else 'NO'}"
                + ("" if ok else " ⇒ definito a metà"))


def _v_systemd_unit(arg, repo: Path) -> tuple[bool, str]:
    p = repo / "systemd" / arg
    return p.exists(), f"systemd/{arg} {'esiste' if p.exists() else 'MANCA'}"


def _v_compose_profile(arg, repo: Path) -> tuple[bool, str]:
    p = repo / arg["file"]
    if not p.exists():
        return False, f"compose MANCA: {arg['file']}"
    hit = arg["profile"] in p.read_text(errors="replace")
    return hit, f"profilo {arg['profile']} {'dichiarato' if hit else 'ASSENTE'} in {arg['file']}"


def _v_mcp_tool(arg, repo: Path) -> tuple[bool, str]:
    # il tool è registrato se una `def <name>` porta il decoratore `@…​.tool`
    svc = repo / "services" / arg["service"] / "app"
    if not svc.exists():
        return False, f"servizio MANCA: {arg['service']}"
    want = arg["name"]
    rotti = []
    for f in svc.rglob("*.py"):
        esito = _tool_mcp_definito(f, want)
        if esito is None:
            rotti.append(f.name)
        elif esito:
            return True, (f"tool MCP {arg['service']}/{want} registrato "
                          "(albero sintattico, non testo)")
    if rotti:
        # un file che non compila non è «il tool non c'è»: è «non ho potuto guardare».
        return False, (f"tool MCP {arg['service']}/{want} non trovato, MA "
                       f"{len(rotti)} file NON COMPILANO ({', '.join(rotti[:3])}): "
                       "questo esito non distingue «assente» da «illeggibile»")
    return False, f"tool MCP {arg['service']}/{want} NON registrato"


def _v_cmd(arg, repo: Path) -> tuple[bool, str]:
    # `arg` viene dal ledger del repo (features.yaml), che passa da revisione come il codice
    try:
        r = subprocess.run(arg, shell=True, cwd=repo, capture_output=True, text=True,  # noqa: S602
                           timeout=CMD_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return False, f"`{arg}` non ha finito entro {CMD_TIMEOUT_S} s"
    return r.returncode == 0, f"`{arg}` exit {r.returncode}"


# I tipi di `verify` che il verificatore sa trattare, ognuno con la sua funzione. `manual` è a
# parte (non è né ok né non-ok). `tools/tests/test_ledger_tipi.py` legge le chiavi di questa
# tabella: un tipo usato nel ledger e assente qui è una voce che si dichiara verificata e non lo è.
_VERIFICHE = {
    "path_exists": _v_path_exists,
    "file_contains": _v_file_contains,
    "python_def": _v_python_def,
    "grep_count": _v_grep_count,
    "cli_command": _v_cli_command,
    "systemd_unit": _v_systemd_unit,
    "compose_profile": _v_compose_profile,
    "mcp_tool": _v_mcp_tool,
    "cmd": _v_cmd,
}



def _tool_mcp_definito(path: Path, want: str) -> bool | None:
    """True/False se il tool è definito+decorato. **None se il file non compila** —
    e la distinzione è il punto: «non ho potuto guardare» non è «non c'è»."""
    try:
        albero = ast.parse(path.read_text(errors="replace"))
    except SyntaxError:
        return None
    for n in ast.walk(albero):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) or n.name != want:
            continue
        for d in n.decorator_list:
            f = d.func if isinstance(d, ast.Call) else d      # @x.tool  e  @x.tool()
            if isinstance(f, ast.Attribute) and f.attr == "tool":
                return True
    return False


# ── enumeratori del REALE (per il verso reale→dichiarato) ─────────────────────
def enum_reality(repo: Path) -> dict[str, set[str]]:
    """Cosa ESISTE davvero nel repo, per categoria. Ogni chiave qui DEVE trovare una
    voce nel ledger, o il verso reale→dichiarato segnala/fallisce."""
    real: dict[str, set[str]] = {"mcp_tool": set(), "systemd_unit": set(),
                                 "compose_profile": set(), "tools_script": set(),
                                 "cli_command": set()}

    real["cli_command"] = _comandi_reali(repo)
    script = _script_reali(repo)
    if script is None:
        del real["tools_script"]
    else:
        real["tools_script"] = script
    real["mcp_tool"] = _tool_mcp_reali(repo)
    real["systemd_unit"] = _unit_reali(repo)
    real["compose_profile"] = _profili_reali(repo)
    return real


def _comandi_reali(repo: Path) -> set[str]:
    # ── cli_command ───────────────────────────────────────────────────────────
    # 🔴 PERCHÉ QUESTA CATEGORIA ESISTE (b82df434, 02/08/2026 09:2x), ed è la SECONDA
    #   volta che questo verso si scopre cieco su un piano. Stanotte avevo aggiunto
    #   `tools_script` perché tutto `tools/` era fuori dall'enumerazione. Restava
    #   fuori un piano più fine: i SOTTOCOMANDI dentro `tools/vps1777.py` — un file
    #   solo, dieci funzioni-comando. Curato «i file», non «i comandi dentro un file».
    # 📏 Misurato quando è stata scritta: 9 sottocomandi definiti, ZERO con una voce
    #   nel ledger. Le voci `update.*` che sembravano coprirlo sono altro (timer,
    #   bottone), e le ho aperte una per una prima di dire zero.
    # ⚠️ E il modo in cui è saltato fuori vale più del numero: `verify-features` è
    #   passato VERDE sulla PR che AGGIUNGE `archive-retag`. Il verde era corretto —
    #   era su un piano che il presidio non guarda. Uno zero che non sa di essere zero,
    #   dentro il presidio scritto apposta per gli zeri.
    # 🖐️ COSA NON PROVA: che il comando FUNZIONI, o che qualcuno lo usi. Prova che è
    #   accettato dalla riga di comando E collegato a una funzione — le due metà che
    #   possono divergere in silenzio.
    cli = repo / "tools" / "vps1777.py"
    if not cli.exists():
        return set()
    testo = cli.read_text(errors="replace")
    return set(re.findall(r'sub\.add_parser\("([a-z0-9-]+)"', testo))



def _script_reali(repo: Path) -> set[str] | None:
    """Gli script tracciati in tools/; None se git non risponde (vedi sotto)."""
    # ── tools_script ──────────────────────────────────────────────────────────
    # 🔴 PERCHÉ QUESTA CATEGORIA ESISTE (b82df434, 02/08/2026 00:0x).
    #   Il verso reale→dichiarato enumerava TRE categorie. Tutto `tools/` era fuori
    #   dall'insieme che guarda — quindi il ledger anti-amnesia, il cui scopo scritto
    #   è «che vps1777 non perda MAI una funzione», su quel piano dava verde **senza
    #   aver guardato**. Misurato: 20 script su 24 mai nominati nel ledger.
    # ⭐ E si vede da cosa è stato trovato: `tools/collaudo-quadratura.py` contiene la
    #   sonda che un audit del round-12 proponeva come «cosa che ci manca». Non manca:
    #   c'è, e non la invoca nessuno. Il presidio che doveva accorgersene non guardava lì.
    # ⚠️ COSA NON PROVA, e va detto perché è la stessa classe che sto curando:
    #   · NON prova che lo script sia INVOCATO da qualcuno (è la domanda vera, e questa
    #     enumerazione non la risponde: dice solo «esiste e il ledger lo nomina o no»);
    #   · NON prova che serva, che funzioni, o che sia raggiungibile a runtime.
    #   ⇒ è un inventario, non un collaudo. Chiamarlo altrimenti sarebbe rifare il difetto.
    # 📌 L'insieme è `git ls-files`, non un glob del disco: stesso criterio dello
    #   shellcheck in CI (`mapfile -t SCRIPTS < <(git ls-files '*.sh')`), così un file
    #   non tracciato non entra e un file tracciato non può sfuggire.
    try:
        tracciati = subprocess.run(
            ["git", "-C", str(repo), "ls-files",
             "tools/*.sh", "tools/*.py", "tools/prove-empiriche/*.sh"],
            capture_output=True, text=True, check=True, timeout=30).stdout.split("\n")
    except (subprocess.SubprocessError, OSError):
        # git assente o non è un repo: NON fingo un insieme vuoto — un set vuoto qui
        # direbbe «nessuno script non dichiarato», che è esattamente il verde-senza-
        # aver-guardato. Lascio la categoria fuori: il referto dirà che manca.
        return None
    return {r for r in (x.strip() for x in tracciati) if r}


def _tool_mcp_reali(repo: Path) -> set[str]:
    """Ogni funzione decorata `@x.tool` sotto services/, come «servizio/nome»."""
    trovati: set[str] = set()
    svc = repo / "services"
    if not svc.exists():
        return trovati
    for f in svc.rglob("*.py"):
        if ".venv" in f.parts:
            continue
        # stesso criterio del verso opposto: albero sintattico, non regex.
        # Se il file non compila NON si enumera nulla da lì — e il verso
        # dichiarato→reale lo dirà, invece di far sparire i tool in silenzio.
        try:
            albero = ast.parse(f.read_text(errors="replace"))
        except SyntaxError:
            continue
        service = _servizio_di(f)
        trovati |= {f"{service}/{nome}" for nome in _tool_decorati(albero)}
    return trovati


def _servizio_di(f: Path) -> str | None:
    """Il nome del servizio: la cartella subito sotto `services/`."""
    for i, part in enumerate(f.parts):
        if part == "services" and i + 1 < len(f.parts):
            return f.parts[i + 1]
    return None


def _tool_decorati(albero: ast.AST) -> list[str]:
    """I nomi delle funzioni decorate con `@x.tool` o `@x.tool(...)`."""
    nomi: list[str] = []
    for n in ast.walk(albero):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for d in n.decorator_list:
            fn = d.func if isinstance(d, ast.Call) else d
            if isinstance(fn, ast.Attribute) and fn.attr == "tool":
                    nomi.append(n.name)
                    break
    return nomi


def _unit_reali(repo: Path) -> set[str]:
    sysd = repo / "systemd"
    if not sysd.exists():
        return set()
    return {f.name for f in sysd.iterdir() if f.suffix in (".service", ".timer", ".path")}


def _profili_reali(repo: Path) -> set[str]:
    profili: set[str] = set()
    for comp in repo.glob("compose*.yaml"):
        for m in re.finditer(r"profiles:\s*\[([^\]]+)\]", comp.read_text(errors="replace")):
            for prof in m.group(1).split(","):
                profili.add(prof.strip())
    return profili


def _keys_of(e: dict) -> dict[str, set[str]]:
    """Le chiavi-reali che UNA voce dichiara, lette da `verify`, `follow_up.verify` E
    `dove`. Leggere anche `dove` (non solo verify) è ciò che permette a una voce con
    verify `manual` — es. un `removed` — di risultare comunque DICHIARATA per la sua
    coordinata (il buco fine trovato da setaccio: un profilo removed con verify manual
    veniva dato per non-dichiarato)."""
    k: dict[str, set[str]] = {"mcp_tool": set(), "systemd_unit": set(),
                              "compose_profile": set(), "tools_script": set(),
                              "cli_command": set()}
    _chiavi_dai_verify(e, k)
    _chiavi_dal_dove(e, k)
    return k


def _chiavi_dai_verify(e: dict, k: dict[str, set[str]]) -> None:
    for spec in (e.get("verify"), (e.get("follow_up") or {}).get("verify")):
        if isinstance(spec, dict):
            if "mcp_tool" in spec:
                k["mcp_tool"].add(f"{spec['mcp_tool']['service']}/{spec['mcp_tool']['name']}")
            elif "systemd_unit" in spec:
                k["systemd_unit"].add(spec["systemd_unit"])
            elif "compose_profile" in spec:
                k["compose_profile"].add(spec["compose_profile"]["profile"])
            elif "cli_command" in spec:
                k["cli_command"].add(spec["cli_command"])


def _chiavi_dal_dove(e: dict, k: dict[str, set[str]]) -> None:
    # dove: "compose-profile:<file>#<profilo>" · "mcp-tool:<svc>/<nome>" · "systemd:<unit>"
    for d in e.get("dove", []):
        if d.startswith("compose-profile:") and "#" in d:
            k["compose_profile"].add(d.split("#", 1)[1])
        elif d.startswith("mcp-tool:"):
            k["mcp_tool"].add(d.split(":", 1)[1])
        elif d.startswith("systemd:"):
            k["systemd_unit"].add(d.split(":", 1)[1])
        elif d.startswith("cli:"):
            k["cli_command"].add(d.split(":", 1)[1])
        # tools_script: il `dove` è già il percorso nudo (`tools/backup.sh`) — nessun
        # prefisso nuovo da imparare, e le voci che lo citano risultano dichiarate
        # senza toccarle. È il motivo per cui la semina parte già non-vuota.
        elif d.startswith("tools/"):
            k["tools_script"].add(d.split("#", 1)[0].split(":", 1)[0].strip())


def main() -> int:
    ap = argparse.ArgumentParser(description="Verifica il ledger delle feature vps1777")
    ap.add_argument("--ledger", default="features.yaml", type=Path)
    ap.add_argument("--repo", default=".", type=Path, help="radice del repo vps1777")
    ap.add_argument("--oggi", type=datetime.date.fromisoformat, default=None,
                    help="AAAA-MM-GG: la data con cui leggere scadenze e semine (default: oggi, UTC)")
    a = ap.parse_args()
    repo = a.repo.resolve()

    doc = _leggi_ledger(a.ledger if a.ledger.is_absolute() else repo / a.ledger)
    if isinstance(doc, str):
        print(f"ERRORE: {doc}. Un ledger che non so leggere non si verifica, e non è un verde.",
              file=sys.stderr)
        return 2
    entries = doc.get("features", [])
    # Il default è SEVERO (21/11/2026). L'interruttore sta nel file che si verifica: se `_meta`
    # spariva (o il ledger restava senza voci) ogni «non dichiarato» diventava un avviso e la
    # CI restava verde. Ora «semina» va chiesto per iscritto, e zero voci è un errore.
    baseline_completo = (doc.get("_meta") or {}).get("baseline_completo", True)
    if not entries:
        print("ERRORE: il ledger non ha nessuna voce in `features`: non ho niente da "
              "verificare, e «niente» non è un verde.", file=sys.stderr)
        return 2
    oggi = a.oggi or datetime.datetime.now(datetime.timezone.utc).date()   # le scadenze in UTC

    hard_fail: list[str] = []      # fanno uscire != 0
    surveil: list[str] = []        # solo segnalati

    _schema(entries, hard_fail)
    _date_dei_rinvii(entries, oggi, hard_fail)
    _dichiarato_reale(entries, repo, hard_fail, surveil)
    _reale_dichiarato(entries, repo, baseline_completo, hard_fail, surveil, oggi)
    _sorveglianza(entries, repo, oggi, surveil)
    return _referto(entries, baseline_completo, oggi, surveil, hard_fail)


def _leggi_ledger(percorso: Path) -> dict | str:
    """Il ledger come mappa con una lista di voci-mappa in `features`, o il perché non lo è.

    Prima un file vuoto, una lista al posto della mappa o una voce che non è una mappa
    facevano crollare lo strumento con un errore Python (rilievo di Sagoma, 25/11): il
    cancello teneva, ma non diceva che cosa non andava."""
    try:
        doc = yaml.safe_load(percorso.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
        return f"il ledger {percorso} non si legge ({type(e).__name__}: {e})"
    if not isinstance(doc, dict):
        return (f"il ledger {percorso} non è una mappa con la chiave `features` "
                f"(è {type(doc).__name__})")
    voci = doc.get("features", [])
    if not isinstance(voci, list):
        return f"`features` nel ledger {percorso} non è una lista (è {type(voci).__name__})"
    storte = [str(i) for i, v in enumerate(voci) if not isinstance(v, dict)]
    if storte:
        return (f"nel ledger {percorso} le voci in posizione {', '.join(storte[:10])} "
                "non sono mappe")
    return doc


def _schema(entries: list[dict], hard_fail: list[str]) -> None:
    # ── 1. SCHEMA + regola di cattura ─────────────────────────────────────────
    ids = set()
    for e in entries:
        _schema_voce(e, ids, hard_fail)


def _schema_voce(e: dict, ids: set, hard_fail: list[str]) -> None:
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
    # dichiara COSA la chiude. Il follow_up è il cuore anti-amnesia. Lo pretendiamo
    # SEMPRE su una deferred, senza scampo. (Watchtower però NON l'avrebbe preso questa
    # regola: nel ledger fu `opt-in`, non `deferred`. Quel buco lo chiude `al_posto_suo`.)
    # un `verify` non lo sostituisce (il verify prova la presenza, il follow_up
    # dice cosa manca perché sia presente).
    if e.get("status") == "deferred" and not e.get("follow_up"):
        hard_fail.append(f"[cattura] {eid}: 'deferred' senza follow_up — decisione a metà: "
                         "che cosa la chiude, e quando si riguarda?")
    # «CONDIZIONE O DATA» (27/09/2026, lezione dei gemelli dei rinvii — todo_or_die,
    # curatrice F1-Gbis): un rinvio che aspetta SOLO una condizione non scatta mai se
    # la condizione non arriva (Graphiti, «dopo il test» cinque volte, e il test abolito).
    # Una condizione verificabile porta anche la sua data di riserva.
    fu_ = _follow_up_ben_fatto(e, eid, hard_fail)
    if (e.get("status") == "deferred" and isinstance(fu_.get("verify"), dict)
            and not fu_.get("rivedi_dopo")
            and not (fu_.get("manuale") or {}).get("rivedi_dopo")):
        hard_fail.append(f"[cattura] {eid}: follow_up.verify senza data — aggiungi "
                         "follow_up.rivedi_dopo: la condizione può non avverarsi mai "
                         "(condizione O data, non condizione E data)")
    # UN RINVIO A GIUDIZIO HA LA SUA DATA (28/11/2026, rilievo di Arianna): senza
    # `manuale.rivedi_dopo` la voce dava verde e non tornava più come [RIVEDI]. La
    # sorveglianza può rimettere davanti solo ciò che ha una data.
    if isinstance(fu_.get("manuale"), dict) and not fu_["manuale"].get("rivedi_dopo"):
        hard_fail.append(f"[cattura] {eid}: follow_up.manuale senza rivedi_dopo — un rinvio a "
                         "giudizio senza data non torna più davanti a nessuno")
    if e.get("status") in ("deferred", "removed", "opt-in") and not e.get("decisione"):
        hard_fail.append(f"[cattura] {eid}: '{e['status']}' senza 'decisione' — invisibile "
                         "allo storico (perché/quando fu deciso?)")
    # CHE COSA C'È AL POSTO SUO (28/11/2026, rilievo di Arianna): una voce `opt-in` o
    # `removed` non è accesa per chi installa. Watchtower fu declassato a «opt-in, non
    # supportato» senza dire che cosa aggiornava la macchina al posto suo, e per un mese
    # niente la aggiornò. La `decisione` dice perché; `al_posto_suo` dice che cosa copre
    # quel bisogno per chi non la attiva, oppure «niente: è un di più» detto in chiaro.
    # ⚠️ È testo libero: la macchina obbliga a DIRLO, non può sapere se è vero. Che sia vero
    # lo guarda chi rilegge la PR. Qui si ferma solo il segnaposto (`x`, `tbd`): una frase.
    al_posto = str(e.get("al_posto_suo") or "").strip()
    if e.get("status") in ("removed", "opt-in") and len(al_posto) < AL_POSTO_SUO_MINIMO:
        hard_fail.append(f"[cattura] {eid}: '{e['status']}' senza 'al_posto_suo' — chi non la "
                         "attiva che cosa ha? (scrivi in una frase che cosa la sostituisce, "
                         "o «niente: è un di più»)")


AL_POSTO_SUO_MINIMO = 12        # caratteri: una frase, non un segnaposto
RINVIO_MASSIMO_GIORNI = 366     # un rinvio oltre un anno è un «mai» scritto con una data


def _date_dei_rinvii(entries: list[dict], oggi: datetime.date, hard_fail: list[str]) -> None:
    """Ogni `deferred` ha una data in cui torna davanti a qualcuno, e quella data è vicina.

    Secondo giro di Arianna (28/11/2026): un `deferred` con `follow_up: {nota: …}`, senza
    condizione e senza giudizio, dava verde e non tornava mai; e `rivedi_dopo: 2999-01-01`
    passava. La sorveglianza rimette davanti solo ciò che ha una data che arriva."""
    for e in entries:
        grezzo = e.get("follow_up")
        fu: dict = grezzo if isinstance(grezzo, dict) else {}
        grezzo = fu.get("manuale")
        man: dict = grezzo if isinstance(grezzo, dict) else {}
        date = [d for d in (fu.get("rivedi_dopo"), man.get("rivedi_dopo")) if d]
        eid = e.get("id", "<senza id>")
        if e.get("status") == "deferred" and fu and not date:
            hard_fail.append(f"[cattura] {eid}: 'deferred' senza una data — aggiungi "
                             "follow_up.rivedi_dopo (o follow_up.manuale.rivedi_dopo): un "
                             "rinvio senza data non torna più davanti a nessuno")
        for d in date:
            if _data_iso(d) and (datetime.date.fromisoformat(str(d)) - oggi).days > RINVIO_MASSIMO_GIORNI:
                hard_fail.append(f"[cattura] {eid}: rivedi_dopo «{d}» è oltre un anno da oggi — "
                                 "un rinvio così lontano è un «mai» scritto con una data")


def _data_iso(valore: object) -> bool:
    try:
        datetime.date.fromisoformat(str(valore))
        return True
    except ValueError:
        return False


def _follow_up_ben_fatto(e: dict, eid: str, hard_fail: list[str]) -> dict:
    """Il `follow_up` della voce se ha la forma giusta, altrimenti {} e il rosso che dice che
    cosa correggere. Un testo al posto della mappa faceva cadere il verificatore con un
    AttributeError invece di un messaggio (28/11/2026, rilievo di Arianna); una data scritta
    male lo faceva cadere nella sorveglianza."""
    fu = e.get("follow_up")
    if fu is None:
        return {}
    if not isinstance(fu, dict):
        hard_fail.append(f"[schema] {eid}: follow_up deve essere una mappa (verify, rivedi_dopo, "
                         f"manuale), non {type(fu).__name__}: «{str(fu)[:60]}»")
        e["follow_up"] = {}
        return {}
    man = fu.get("manuale")
    if man is not None and not isinstance(man, dict):
        hard_fail.append(f"[schema] {eid}: follow_up.manuale deve essere una mappa (cosa, "
                         f"rivedi_dopo), non {type(man).__name__}")
        fu.pop("manuale")              # un rosso solo: non anche «manuale senza rivedi_dopo»
    ver = fu.get("verify")
    if ver is not None and not isinstance(ver, dict):
        # una condizione scritta come frase non la verifica nessuno: niente [PROMUOVI], e la
        # regola «condizione O data» la saltava (rilievo di Arianna, secondo giro)
        hard_fail.append(f"[schema] {eid}: follow_up.verify deve essere una mappa con un tipo di "
                         f"verifica (path_exists, file_contains…), non {type(ver).__name__}: "
                         f"«{str(ver)[:60]}»")
        fu.pop("verify")
    for dove, mappa in (("follow_up", fu), ("follow_up.manuale", fu.get("manuale") or {})):
        data = mappa.get("rivedi_dopo")
        if data and not _data_iso(data):
            # la data resta scritta (così non si aggiunge il rosso «senza data»): è la
            # sorveglianza a saltare ciò che non sa leggere
            hard_fail.append(f"[schema] {eid}: {dove}.rivedi_dopo «{data}» non è una data "
                             "AAAA-MM-GG")
    return fu


def _dichiarato_reale(entries: list[dict], repo: Path, hard_fail: list[str],
                      surveil: list[str]) -> None:
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


def _reale_dichiarato(entries: list[dict], repo: Path, baseline_completo: bool,
                      hard_fail: list[str], surveil: list[str],
                      oggi: datetime.date) -> None:
    # ── 3. REALE → DICHIARATO (cattura ciò che poi si dimentica) ──────────────
    # Tre vie, non due (raffinamento dal buco fine di setaccio):
    #   reale + dichiarato present (active/opt-in) → OK
    #   reale + dichiarato removed                 → STATO≠REALTÀ (l'hai detto tolto, c'è ancora)
    #   reale + nessuna voce                       → NON DICHIARATO (aggiungi la voce)
    # (reale + deferred lo copre la sorveglianza [PROMUOVI] più sotto: è pronto a promozione.)
    real = enum_reality(repo)
    accounted, removed_keys = _chiavi_dichiarate(entries, real)
    for cat in real:
        # una categoria in semina è NUOVA per l'enumerazione: `baseline_completo` non
        # parlava di lei, quindi non può renderla fatale senza mentire su cosa prometteva.
        fine = CATEGORIE_IN_SEMINA.get(cat)
        in_semina = fine is not None and oggi <= datetime.date.fromisoformat(fine)
        for u in sorted(real[cat]):
            if u not in accounted[cat]:
                msg = f"[NON DICHIARATO] {cat} '{u}' esiste nel codice ma NON è nel ledger"
                if in_semina:
                    surveil.append(msg + f" (categoria '{cat}' in semina fino al {fine}: "
                                         "segnalato, dal giorno dopo è un fallimento duro)")
                else:
                    (hard_fail if baseline_completo else surveil).append(
                        msg + ("" if baseline_completo else " (semina in corso: segnalato, non-fatale)"))
            elif u in removed_keys[cat]:
                msg = (f"[STATO≠REALTÀ] {cat} '{u}' è nel ledger come 'removed' ma ESISTE ancora "
                       "nel repo: togli l'artefatto (se davvero rimosso) o cambia status "
                       "(es. opt-in, se resta disponibile ma declassato)")
                (hard_fail if baseline_completo else surveil).append(msg)


def _chiavi_dichiarate(entries: list[dict], real: dict[str, set[str]]
                       ) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Per categoria: le chiavi nominate da qualche voce, e quelle delle voci `removed`."""
    accounted: dict[str, set[str]] = {c: set() for c in real}
    removed_keys: dict[str, set[str]] = {c: set() for c in real}
    for e in entries:
        keys = _keys_of(e)
        for c in real:
            accounted[c] |= keys[c]
            if e.get("status") == "removed":
                removed_keys[c] |= keys[c]
    return accounted, removed_keys


def _sorveglianza(entries: list[dict], repo: Path, oggi: datetime.date,
                  surveil: list[str]) -> None:
    # ── SORVEGLIANZA: follow_up a-giudizio scaduti + verificabili pronti ──────
    for e in entries:
        fu = e.get("follow_up") or {}
        man = fu.get("manuale")
        if man and _data_iso(man.get("rivedi_dopo")):
            due = datetime.date.fromisoformat(str(man["rivedi_dopo"]))
            if oggi > due:
                surveil.append(f"[RIVEDI] {e['id']}: rinvio-a-giudizio scaduto il {due} "
                               f"(«{man.get('cosa', '')}») — rimettilo in discussione")
        if _data_iso(fu.get("rivedi_dopo")):
            due = datetime.date.fromisoformat(str(fu["rivedi_dopo"]))
            if oggi > due:
                surveil.append(f"[RIVEDI] {e['id']}: la condizione non si è avverata e la data "
                               f"di riserva ({due}) è passata — rimettilo in discussione")
        if e.get("status") == "deferred" and isinstance(fu.get("verify"), dict):
            ok, det = run_check(fu["verify"], repo)
            if ok:
                surveil.append(f"[PROMUOVI] {e['id']}: il follow_up verificabile è ORA soddisfatto "
                               f"({det}) — la deferred può passare ad active-default")


def _referto(entries: list[dict], baseline_completo: bool, oggi: datetime.date,
             surveil: list[str], hard_fail: list[str]) -> int:
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
