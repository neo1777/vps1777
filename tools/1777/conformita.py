#!/usr/bin/env python3
"""conformita.py — il controllo di conformità del contratto 1777 (DD-P8.9, Ka.2, Ka.11).

Verifica, da fonti INDIPENDENTI dal file che le nomina:
  1. [comandi]   i comandi nominati in AGENTS.md esistono secondo `mise tasks ls --json`
                 (non secondo AGENTS.md), e ci sono i 7 del contratto;
  2. [prova]     ogni riga di RIGHE.md con C3 «derivata: `id`» ha la sua prova a tre tempi in
                 tools/1777/prova-controlli.sh (il «visto rosso» lo scrive quella, qui si legge);
  3. [file]      i file nominati fra backtick in AGENTS.md e in RIGHE.md esistono, o la riga
                 li dichiara «pigro» (RIGHE.md da F.2: nominava un file del template che
                 nel figlio non c'è, e il doc-riferimenti di vps1777 l'ha fermato);
  4. fail-loud:  se manca uno strumento lo dice ed esce 2. Mai verde senza aver misurato.
E le righe del contratto che stanno in file condivisi, una per una (Ka.8, idea):
  [descrizione]  ogni task ha una description (Ka.11: senza è rosso);
  [tera]         ogni task si lascia leggere da mise: mise passa ogni `run` per Tera, e un `{#`
                 di bash (`${#ARR[@]}`) rompe quel task e chi ne dipende, `check` compreso.
                 `mise tasks ls` e `mise tasks validate` restano verdi: lo dice solo
                 `mise run --dry-run` (misurato il 29/09; F.3);
  [claude-import] un CLAUDE.md senza `@AGENTS.md` (DD-P8.3);
  [filo]         `setup` chiama tools/hooks/installa.sh (Kc.5), letto da `mise tasks info`;
  [prepare]      nei TS, "prepare" chiama SOLO l'installatore (Kc.3);
  [gitignore]    .env è ignorato da git;
  [ci]           la CI usa action fissate per sha, mise alla stessa versione di min_version (Ka.5),
                 e i suoi step `run:` chiamano solo comandi del contratto (K-a): niente apt,
                 uno strumento di sistema sta in [tools] di mise (F.8);
  [src-path]     `.copier-answers.yml` non dice da quale cartella di casa è nato il repo: su un
                 repo pubblico è rosso, su un privato è una nota (F.9);
  [env-example]  nei Dart, .env.example senza *_KEY (Pr.8);
  [lingua]       se il repo è pubblico, AGENTS, RIGHE e il glossario esistono in italiano E in
                 inglese, si rimandano, sono allineati nella forma e la traduzione non è stantia
                 (K5, F2.3; la logica sta in tools/1777/lingue.py);
  [glossario]    ogni sigla dei documenti è spiegata nel glossario (F2.3).
E in [ci], dal v0.2 (F2.4): `runs-on` fissato (mai `-latest`), e nei Python senza python in
[tools] il python di uv fissato (`UV_PYTHON` in [env], o `.python-version`).

Esce 0 se tutto regge, 1 se c'è un rosso, 2 se non può misurare.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lingue  # sta accanto a questo file, in tools/1777/

CONTRATTO = ["setup", "dev", "test", "lint", "build", "check", "release"]
rossi: list[str] = []
note: list[str] = []


def rosso(regola: str, msg: str) -> None:
    rossi.append(f"✗ ROSSO [{regola}] {msg}")


def non_misurato(msg: str) -> None:
    print(f"[⚪] conformità: NON MISURATO — {msg}", file=sys.stderr)
    sys.exit(2)


def mise_json(*args: str):
    try:
        r = subprocess.run(
            ["mise", *args, "--json"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except OSError as e:
        non_misurato(f"mise non si lancia ({e})")
    if r.returncode != 0:
        non_misurato(
            f"`mise {' '.join(args)} --json` esce {r.returncode}: {r.stderr.strip()[:300]}"
        )
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        non_misurato(f"`mise {' '.join(args)} --json` non dà JSON")


def main() -> int:
    top = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if top.returncode != 0:
        non_misurato("non sono in un repository git")
    radice = pathlib.Path(top.stdout.strip())
    if shutil.which("mise") is None:
        non_misurato(
            "mise non è nel PATH: i comandi del contratto non si possono leggere"
        )

    os.chdir(radice)

    # --- 1. i comandi, dalla fonte indipendente
    tasks = mise_json("tasks", "ls")
    nomi = {t.get("name") for t in tasks}
    for t in tasks:
        if not (t.get("description") or "").strip():
            rosso(
                "descrizione", f"il task «{t.get('name')}» non ha description (Ka.11)"
            )
    for n in sorted(nomi):
        try:
            r = subprocess.run(
                ["mise", "run", "--dry-run", n],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            non_misurato(f"`mise run --dry-run {n}` non si lancia ({e})")
        if "invalid task script template" in r.stderr:
            rosso(
                "tera",
                f"il task «{n}» non si legge: mise passa il `run` per Tera (un `{{#` di bash apre un commento). "
                "La logica va in uno script in tools/, o fra raw ed endraw",
            )
    for n in CONTRATTO:
        if n not in nomi:
            rosso("comandi", f"manca il comando del contratto «{n}» in `mise tasks ls`")

    agents = radice / "AGENTS.md"
    testo = agents.read_text(encoding="utf-8") if agents.is_file() else ""
    if not testo:
        rosso("file", "manca AGENTS.md (DD-P8.3)")
    for m in re.finditer(r"mise run ([a-z][a-z0-9:_-]*)", testo):
        if m.group(1) not in nomi:
            rosso(
                "comandi",
                f"AGENTS.md nomina `mise run {m.group(1)}`, che `mise tasks ls` non conosce",
            )
    for frase in (
        "mise run check",
        "mise tasks ls --json",
        "mise tasks info test --json",
    ):
        if testo and frase not in testo:
            rosso("comandi", f"AGENTS.md non nomina `{frase}` (Ka.1, Ka.9)")

    # --- 3. i file nominati esistono o sono dichiarati pigri (AGENTS, RIGHE e il
    # glossario, in ogni lingua che il repo ha: K5)
    _, docs = lingue.piano(radice)
    for nome_doc in [n for _, it, en in docs for n in (it, en) if n]:
        f = radice / nome_doc
        doc = f.read_text(encoding="utf-8") if f.is_file() else ""
        for riga in doc.splitlines():
            for m in re.finditer(r"`([^`\s<>*]+)`", riga):
                p = m.group(1).rstrip("/")
                if p.startswith(("mise", "http", "--", "@")) or "=" in p:
                    continue
                if not (
                    "/" in p
                    or re.search(
                        r"\.(md|py|sh|toml|ya?ml|json|ndjson|tsv|dart|ts|lock)$", p
                    )
                ):
                    continue
                if not (radice / p).exists() and not re.search(
                    r"pigro|lazy", riga, re.IGNORECASE
                ):
                    rosso(
                        "file",
                        f"{nome_doc} nomina `{p}`, che non esiste e non è dichiarato «pigro»",
                    )

    # --- DD-P8.3: CLAUDE.md solo con l'import
    for c in ("CLAUDE.md", ".claude/CLAUDE.md", "CLAUDE.local.md"):
        f = radice / c
        if f.is_file() and "@AGENTS.md" not in f.read_text(encoding="utf-8"):
            rosso(
                "claude-import",
                f"{c} esiste senza `@AGENTS.md`: Claude Code non leggerebbe AGENTS.md",
            )
    for sopra in radice.parents:
        if (sopra / "CLAUDE.md").is_file():
            note.append(
                f"ⓘ c'è un CLAUDE.md sopra il repo ({sopra}): è della macchina, non lo giudico"
            )
            break

    # --- il filo: setup chiama l'installatore degli hook
    info = mise_json("tasks", "info", "setup")
    run = json.dumps(info.get("run", info))
    if "tools/hooks/installa.sh" not in run:
        rosso(
            "filo",
            "`setup` non chiama tools/hooks/installa.sh: l'hook non si installa (Kc.5)",
        )
    if not (radice / "tools/hooks/installa.sh").is_file():
        rosso("filo", "manca tools/hooks/installa.sh")

    # --- TS: prepare chiama solo l'installatore
    pj = radice / "package.json"
    if pj.is_file():
        prep = (
            json.loads(pj.read_text(encoding="utf-8")).get("scripts", {}).get("prepare")
        )
        if prep != "bash tools/hooks/installa.sh":
            rosso(
                "prepare",
                f'package.json: "prepare" deve essere "bash tools/hooks/installa.sh", è {prep!r} (Kc.3)',
            )

    # --- .env ignorato
    if (
        subprocess.run(["git", "check-ignore", "-q", ".env"], check=False).returncode
        != 0
    ):
        rosso("gitignore", ".env NON è ignorato da git (manca la riga in .gitignore)")

    # --- Dart: .env.example senza chiavi
    ex = radice / ".env.example"
    risposte = radice / ".copier-answers.yml"
    stack = (
        re.search(
            r"^stack:\s*(\S+)", risposte.read_text(encoding="utf-8"), re.MULTILINE
        )
        if risposte.is_file()
        else None
    )
    dart = (radice / "pubspec.yaml").is_file() or (
        stack is not None and stack.group(1) == "dart"
    )
    if (
        dart
        and ex.is_file()
        and re.search(
            r"^[A-Za-z0-9_]*_KEY\s*=", ex.read_text(encoding="utf-8"), re.MULTILINE
        )
    ):
        rosso(
            "env-example",
            ".env.example di un client Dart porta un *_KEY: setup preparerebbe il file che Ka.10 vieta",
        )

    # --- da dove è nato il repo: mai una cartella di casa (F.9)
    if risposte.is_file():
        rt = risposte.read_text(encoding="utf-8")
        sp = re.search(r"^_src_path:\s*['\"]?([^'\"\n]+)", rt, re.MULTILINE)
        pub = re.search(r"^pubblico:\s*true\b", rt, re.MULTILINE)
        if sp and re.match(r"(/|~|\.\.?/|file:)", sp.group(1).strip()):
            if pub:
                rosso(
                    "src-path",
                    ".copier-answers.yml: _src_path è una cartella locale su un repo pubblico. "
                    "Rigenera da gh:neo1777/template1777 (o redigi a mano PRIMA del commit)",
                )
            else:
                note.append(
                    "ⓘ _src_path è una cartella locale: `copier update` riparte solo da questa macchina"
                )

    # --- Ka.5: la versione di mise, fissata e uguale
    mt = (
        (radice / "mise.toml").read_text(encoding="utf-8")
        if (radice / "mise.toml").is_file()
        else ""
    )
    mv = re.search(r'min_version\s*=\s*\{[^}]*hard\s*=\s*"([^"]+)"', mt)
    if not mv:
        rosso("ci", "mise.toml senza `min_version = { hard = ... }` (Ka.5)")
    lock = radice / "mise.lock"
    lt = lock.read_text(encoding="utf-8") if lock.is_file() else ""
    blocco = re.search(r"^\[tools\]\n(.*?)(?=^\[)", mt, re.MULTILINE | re.DOTALL)
    for nome, ver in re.findall(
        r'^([a-z0-9_-]+)\s*=\s*"([^"]+)"',
        blocco.group(1) if blocco else "",
        re.MULTILINE,
    ):
        if not re.search(
            rf'^\[\[tools\.{re.escape(nome)}\]\]\nversion = "{re.escape(ver)}"',
            lt,
            re.MULTILINE,
        ):
            rosso(
                "ci",
                f"mise.lock non fissa {nome} {ver} (Ka.5): rilancia `mise lock` e committalo",
            )
    wf = radice / ".github/workflows/check.yml"
    if not wf.is_file():
        rosso("ci", "manca .github/workflows/check.yml")
    else:
        w = wf.read_text(encoding="utf-8")
        if not re.search(r"uses:\s*jdx/mise-action@[0-9a-f]{40}\b", w):
            rosso("ci", "check.yml: jdx/mise-action non è fissata per sha (Ka.5)")
        for m in re.finditer(r"^\s*-?\s*uses:\s*([^\s#]+)", w, re.MULTILINE):
            if not re.search(r"@[0-9a-f]{40}$", m.group(1)):
                rosso("ci", f"check.yml: `{m.group(1)}` non è fissata per sha (Ka.5)")
        # K-a: la CI chiama i comandi del contratto e nient'altro. Uno step apt (o pip, npm…)
        # farebbe divergere la CI dal locale: lo strumento va in [tools] di mise.toml.
        for m in re.finditer(r"^\s*-?\s*run:\s*(.+)$", w, re.MULTILINE):
            cmd = m.group(1).strip()
            if not re.fullmatch(
                r"mise run [a-z][a-z0-9:_-]*( .*)?|bash tools/1777/prova-controlli\.sh",
                cmd,
            ):
                rosso(
                    "ci",
                    f"check.yml: lo step `run: {cmd[:60]}` non è un comando del contratto (K-a): "
                    "uno strumento di sistema va in [tools] di mise.toml",
                )
        vs = set(re.findall(r"^\s*version:\s*[\"']?([0-9][0-9.]*)", w, re.MULTILINE))
        if mv and vs != {mv.group(1)}:
            rosso(
                "ci",
                f"check.yml: version di mise {sorted(vs) or 'assente'} ≠ min_version {mv.group(1)} (Ka.5)",
            )
        if "mise run check" not in w:
            rosso("ci", "check.yml non lancia `mise run check`")
        # F2.4: il runner fissato. `-latest` cambia immagine da solo (ubuntu-latest passa a
        # Ubuntu 26 dal 19/10/2026), e con lei il python e gli strumenti di sistema.
        for m in re.finditer(r"^\s*runs-on:\s*(\S+)", w, re.MULTILINE):
            if m.group(1).endswith("-latest"):
                rosso(
                    "ci",
                    f"check.yml: `runs-on: {m.group(1)}` non è fissato (F2.4): "
                    "scrivi l'immagine, per esempio ubuntu-24.04, e alzala a lotti",
                )
    # F2.4: nei Python senza python in [tools], il python di uv è fissato senza toccare il
    # PATH: UV_PYTHON in [env] di mise.toml, o .python-version
    blocco_tools = blocco.group(1) if blocco else ""
    if (
        stack is not None
        and stack.group(1) == "python"
        and not re.search(r"^python\s*=", blocco_tools, re.MULTILINE)
        and not re.search(r"^\[env\][^\[]*^UV_PYTHON\s*=", mt, re.MULTILINE | re.DOTALL)
        and not (radice / ".python-version").is_file()
    ):
        rosso(
            "ci",
            "il python di uv non è fissato (F2.4): python non è in [tools], e mancano "
            "UV_PYTHON in [env] di mise.toml e .python-version. uv userebbe il python del runner",
        )

    # --- 2. ogni controllo ha la sua prova a tre tempi
    righe = radice / "RIGHE.md"
    prova = radice / "tools/1777/prova-controlli.sh"
    pt = prova.read_text(encoding="utf-8") if prova.is_file() else ""
    if not pt:
        rosso("prova", "manca tools/1777/prova-controlli.sh (DD-P8.9, AP.1)")
    ids = []
    if righe.is_file():
        # una riga è un controllo se la sua cella C3 dice «derivata: `id`» (AP.1)
        testi = [righe.read_text(encoding="utf-8")]
        testi += [
            (radice / n).read_text(encoding="utf-8")
            for b, it, en in docs
            if b == "RIGHE"
            for n in (it, en)
            if n and n != "RIGHE.md" and (radice / n).is_file()
        ]
        for m in re.finditer(r"(?:derivata|derived): `([a-z0-9-]+)`", "\n".join(testi)):
            if m.group(1) not in ids:
                ids.append(m.group(1))
    else:
        rosso("prova", "manca RIGHE.md (DD-P8.1)")
    for i in ids:
        if not re.search(rf"^\s*prova\w*\s+{re.escape(i)}\b", pt, re.MULTILINE):
            rosso(
                "prova",
                f"il controllo «{i}» di RIGHE.md non ha una prova in tools/1777/prova-controlli.sh",
            )

    # --- C3: si legge, non si giudica (AP.5: senza «visto rosso» resta «proposto»)
    vr = radice / "tools/1777/visto-rosso.tsv"
    if vr.is_file():
        # visto = ogni guasto «sì» o «non si applica», e almeno un «sì» (un guasto che non si
        # applica a questo stack non rende «proposto» il controllo: v0.2, misurato nel repo di prova)
        esiti: dict[str, list[str]] = {}
        for ln in vr.read_text(encoding="utf-8").splitlines()[1:]:
            c = ln.split("\t")
            if len(c) >= 6:
                esiti.setdefault(c[0], []).append(c[5])
        visti = {
            k
            for k, v in esiti.items()
            if "sì" in v and all(x in ("sì", "non si applica") for x in v)
        }
        proposti = [i for i in ids if i not in visti]
        note.append(
            f"ⓘ C3: {len(ids) - len(proposti)} controlli visti rossi su {len(ids)}"
            + (f"; proposti: {', '.join(proposti)}" if proposti else "")
        )
    else:
        note.append(
            f"ⓘ C3: tools/1777/visto-rosso.tsv non c'è ancora: i {len(ids)} controlli sono tutti «proposti» (AP.5)"
        )

    # --- K5 e il glossario (tools/1777/lingue.py)
    rl, nl = lingue.controlla(radice)
    for r in rl:
        regola, _, msg = r.partition("] ")
        rosso(regola.lstrip("["), msg)
    note.extend(nl)

    for n in note:
        print(n)
    for r in rossi:
        print(r, file=sys.stderr)
    if rossi:
        print(f"✗ conformità: {len(rossi)} rossi", file=sys.stderr)
        return 1
    print(
        f"✓ conformità: {len(nomi)} comandi, {len(ids)} controlli con la prova, righe del contratto a posto"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
