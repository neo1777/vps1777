#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""I nomi che i documenti citano devono esistere nel codice, e se non esistono è rosso.

🔴 PERCHÉ ESISTE — verifica della documentazione del 12/10/2026, sulla 0.86.0. Quindici
   letture parallele contro il codice hanno trovato 332 difetti, e Neo ha chiesto perché la
   doc non dicesse DA SOLA di essere vecchia. I presìdi c'erano, ma ognuno guarda una cosa:
   `fatti-nei-doc.py` i numeri, `doc-riferimenti.py` i file, il MANIFEST delle traduzioni gli
   hash. Nessuno guardava i NOMI: `vps1777 auto-update` citato come comando in ARCHITECTURE
   (il timer lancia `update --eta-minima`), `BOT_RAG_COMMANDS` documentato in `.env.example`
   dopo che la 0.86.0 l'aveva tolto, `/lista` e `/chiedi` in pagine scritte prima.

📏 COSA CONTROLLA, nei `.md` tracciati (tranne CHANGELOG e docs/roadmap, che sono storia e
   piani) e in `.env.example`, solo dentro `codice` o nei blocchi ```:
   · `vps1777 <comando> [--flag]`  il comando e i suoi flag, letti dal parser VERO
                                   (`build_parser()` di tools/vps1777.py);
   · `NOME_IN_MAIUSCOLO`           una variabile d'ambiente: qualche file di codice o di
                                   config la deve nominare (anche come campo pydantic in
                                   minuscolo);
   · `nome_tool(...)`              un nome della famiglia dei tool MCP o delle funzioni del
                                   repo, scritto come chiamata: deve esistere come funzione;
   · `/comando` in una riga che parla del bot o di Telegram: deve essere fra i comandi del
                                   bot (`COMANDI` in services/nb1777-bot/app/bot.py), a meno
                                   che sia una rotta HTTP che il codice serve.

🕰️ LA STORIA NON È UN ERRORE. Una riga che dice che qualcosa è stato tolto («tolto»,
   «rimosso», «niente», «fino alla 0.x», «non è stato fatto», «was removed»…) può nominarlo:
   è il criterio della freschezza, origine contro impatto. Una riga che lo nomina come se ci
   fosse ancora, no.

Solo stdlib (gira nel job `lint`). `--autoprova` prova che sa dire di no e di sì.
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

RADICE = Path(__file__).resolve().parents[1]
FUORI = ("CHANGELOG.md", "docs/roadmap/")
STORICO = re.compile(
    r"tolt[oaie]\b|rimoss[oaie]\b|\bniente\b|removed|dropped|no longer|non (c'è|esiste|serve) più|"
    r"fino alla|until v?0\.|prima (della|era|erano|c'era)|non è stat[oa] fatt[oa]|"
    r"\bera\b|\berano\b|\bwas\b|\bwere\b|storic|historical", re.I)
FAMIGLIE = ("source_", "studio_", "nb_", "note_", "notebook_", "research_", "chat_", "memoria_",
            "lavoro_", "usage_", "get_", "search", "count", "check_", "list_", "archive_",
            "describe_", "set_", "precedenti", "delta", "canonico", "doctor", "censimento",
            "cmd_", "index_")
SPAN = re.compile(r"`([^`\n]+)`")
VPS = re.compile(r"(?:^|\s)vps1777\s+([a-z][a-z0-9-]*)((?:\s+[^\s|;&]+)*)")
ENV = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$")
CHIAMATA = re.compile(r"^([a-z_][a-z0-9_]*)\(")
BOTCMD = re.compile(r"^/([a-z]+)$")


def _git_ls(*pattern: str) -> list[str]:
    out = subprocess.run(["git", "ls-files", *pattern], cwd=RADICE, capture_output=True,
                         text=True, check=True).stdout
    return out.split()


def contesto() -> dict:
    spec = importlib.util.spec_from_file_location("vps1777_cli_nomi", RADICE / "tools/vps1777.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["vps1777_cli_nomi"] = mod
    spec.loader.exec_module(mod)
    p = mod.build_parser()
    glob = {o for a in p._actions for o in a.option_strings}
    sub = next(a for a in p._actions if isinstance(a, argparse._SubParsersAction))
    comandi = {nome: glob | {o for a in sp._actions for o in a.option_strings}
               for nome, sp in sub.choices.items()}
    funzioni: set[str] = set()
    for f in _git_ls("*.py"):
        try:
            albero = ast.parse((RADICE / f).read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        funzioni |= {n.name for n in ast.walk(albero)
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    parti = []
    for f in _git_ls():
        if f.endswith(".md") or f == ".env.example" or not (RADICE / f).is_file():
            continue
        try:
            parti.append((RADICE / f).read_text(encoding="utf-8"))
        except (UnicodeDecodeError, OSError):
            pass
    bot = (RADICE / "services/nb1777-bot/app/bot.py").read_text(encoding="utf-8")
    m = re.search(r"COMANDI = \(([^)]*)\)", bot)
    return {"comandi": comandi, "funzioni": funzioni, "codice": "\n".join(parti),
            "bot": set(re.findall(r'"([a-z_]+)"', m.group(1))) if m else set()}


def controlla(rel: str, testo: str, c: dict) -> list[str]:
    errori: list[str] = []
    in_blocco = False
    for i, riga in enumerate(testo.splitlines(), 1):
        if riga.lstrip().startswith("```"):
            in_blocco = not in_blocco
            continue
        if STORICO.search(riga):
            continue
        pezzi = [riga] if in_blocco or rel == ".env.example" else SPAN.findall(riga)
        for pezzo in pezzi:
            for m in VPS.finditer(pezzo):
                cmd, resto = m.group(1), m.group(2) or ""
                if cmd not in c["comandi"]:
                    errori.append(f"{rel}:{i}  `vps1777 {cmd}`: la CLI non ha questo comando")
                    continue
                for flag in re.findall(r"(?<![\w-])(--[a-z][a-z0-9-]*)", resto):
                    if flag not in c["comandi"][cmd]:
                        errori.append(f"{rel}:{i}  `vps1777 {cmd} {flag}`: il comando non ha questo flag")
            if in_blocco and rel != ".env.example":
                continue
            for s in ([pezzo.strip()] if rel != ".env.example"
                      else re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", pezzo)):
                if ENV.match(s) and s not in c["codice"] and s.lower() not in c["codice"]:
                    errori.append(f"{rel}:{i}  `{s}`: nessun file di codice o di config la nomina")
                ch = CHIAMATA.match(s)
                if ch and ch.group(1).startswith(FAMIGLIE) and ch.group(1) not in c["funzioni"]:
                    errori.append(f"{rel}:{i}  `{s[:40]}`: non è un tool né una funzione del repo")
                b = BOTCMD.match(s)
                if (b and re.search(r"\bbot\b|telegram", riga, re.I)
                        and not re.search(r"botfather", riga, re.I)
                        and not re.search(r"[\"']/" + b.group(1) + r"\b", c["codice"])
                        and b.group(1) not in c["bot"]):
                    errori.append(f"{rel}:{i}  `{s}`: il bot non ha questo comando "
                                  f"(ha: {', '.join('/' + x for x in sorted(c['bot']))})")
    return errori


def main() -> int:
    c = contesto()
    errori: list[str] = []
    for f in _git_ls("*.md") + [".env.example"]:
        if f.startswith(FUORI) or not (RADICE / f).is_file():
            continue
        errori += controlla(f, (RADICE / f).read_text(encoding="utf-8"), c)
    for e in errori:
        print(f"  🔴 {e}")
    if errori:
        print(f"⛔ {len(errori)} nomi che la documentazione cita e il codice non ha. Allinea il "
              "documento; se la riga racconta la storia, dillo nella riga («tolto», «fino alla…»).")
        return 1
    print("✅ ogni comando, flag, variabile, tool e comando del bot citato nei doc esiste")
    return 0


def _autoprova() -> int:
    c = {"comandi": {"update": {"--yes", "--version"}}, "funzioni": {"source_list"},
         "codice": 'GATEWAY_HOST\narchive_db_dir\nRoute("/app"', "bot": {"start"}}
    casi = [
        ("comando inesistente → errore", "usa `vps1777 auto-update`", 1),
        ("flag inesistente → errore", "```\nvps1777 update --resume\n```", 1),
        ("comando e flag veri → niente", "`vps1777 update --yes --version v1.2.3`", 0),
        ("assegnazione in backtick: non è un nome da solo → niente", "metti `BOT_RAG_COMMANDS=0`", 0),
        ("variabile ignota in backtick → errore", "metti `BOT_RAG_COMMANDS`", 1),
        ("variabile vera, anche come campo pydantic → niente", "`GATEWAY_HOST` e `ARCHIVE_DB_DIR`", 0),
        ("tool inesistente → errore", "chiama `source_replace_tutto(id)`", 1),
        ("tool vero → niente", "chiama `source_list(nb)`", 0),
        ("funzione SQL → niente", "`min(NULLIF(ts,''))` nel bot", 0),
        ("comando del bot tolto → errore", "nel bot scrivi `/lista`", 1),
        ("comando del bot vero → niente", "nel bot scrivi `/start`", 0),
        ("rotta HTTP vicino a «bot» → niente", "il bot apre `/app`", 0),
        ("riga storica → niente", "dalla 0.86.0 il bot non ha più `/lista`: tolto", 0),
        ("BotFather → niente", "su BotFather `/mybots`", 0),
    ]
    sbagliati = 0
    for nome, testo, attesi in casi:
        n = len(controlla("prova.md", testo, c))
        esito = "ok" if n == attesi else f"SBAGLIATO (attesi {attesi}, trovati {n})"
        sbagliati += n != attesi
        print(f"  {'✅' if n == attesi else '🔴'} {nome}: {esito}")
    env = controlla(".env.example", "#BOT_RAG_COMMANDS=true\nGATEWAY_HOST=0.0.0.0\n", c)
    sbagliati += len(env) != 1
    print(f"  {'✅' if len(env) == 1 else '🔴'} .env.example: una variabile tolta → un errore")
    return 1 if sbagliati else 0


if __name__ == "__main__":
    sys.exit(_autoprova() if "--autoprova" in sys.argv else main())
