#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""I numeri che i documenti ripetono li conta il codice, e se una pagina dice altro è rosso.

🔴 PERCHÉ ESISTE — audit della documentazione del 01/10/2026, sulla 0.66.0: «nb1777 ne
   espone 38» e «38 tool» in cinque pagine quando i `@mcp.tool()` erano 39; Trivy «sulle 5 immagini»
   dopo che `caddy-dns01` era diventata la sesta; «I 64 rilievi» in SECURITY.md con il
   registro a 77; «Deve apparire: cinque container» quando `setup.sh` ne avvia sei. Nessuna
   era sbagliata alla nascita: il codice si è mosso, la frase no. *Un numero giusto alla
   nascita e mai più guardato invecchia in silenzio* (docs/NB1777.md lo scrive in testa, e
   nella stessa pagina il numero era invecchiato).

⭐ LO SCHEMA è quello di `security/check_findings.py` sulla tabella di SECURITY.md: il
   documento non può dichiarare più (o meno) del codice. Là la tabella dei residui e la
   frase «Il registro conta N voci»; qui le frasi che stanno FUORI da quella tabella, in
   tutti i documenti che ripetono gli stessi numeri. Una scelta di Neo del 01/10: i numeri
   ripetuti nei doc li conta il codice.

📏 COSA CONTA, e da dove (tutto stdlib: gira nel job `lint`, senza PyYAML):
   · nb1777_tool        le righe che cominciano con `@mcp.tool(` in services/nb1777-mcp/app/server.py
   · archive_tool       idem in services/archive-mcp/app/server.py
   · immagini           la matrice `service:` di .github/workflows/release.yml (ciò che si
                        pubblica e si firma). E la stessa lista deve stare nella matrice
                        `build` di ci.yml, in trivy.yml e nel `for s in` di rebuild-mensile.yml:
                        un insieme scritto a mano quattro volte è il modo in cui `ocr` è
                        rimasta fuori dalla scansione (trivy.yml lo racconta).
   · immagini_stack     quelle della matrice che compose.yaml usa (`vps1777-<nome>`); le
                        altre sono le OPZIONALI (oggi `caddy-dns01`).
   · servizi_stack      i servizi di compose.yaml senza `profiles:`.
   · container_default  DEFINIZIONE, dichiarata qui e non lasciata al lettore: i container
                        che un'installazione nuova avvia con le feature di default
                        (`DEFAULT_FEATURES` in tools/vps1777.py → gli overlay di
                        `OPS_COMPOSE_FEATURES`) e l'ingresso Tailscale, che non aggiunge
                        container (il Funnel gira sull'host). Con caddy o cloudflared sono
                        uno in più: quel numero nessun documento lo ripete, e qui non c'è.
   · rilievi, rilievi_chiusi/_parziali/_accettati/_aperti/_non_chiusi
                        security/findings.yml, letto per righe (`  - id:`, `    status:`).
                        E la tabella di REVIEW.md delle voci non chiuse deve elencare
                        ESATTAMENTE le voci partial/accepted/open del registro: un conteggio
                        giusto con un nome sbagliato è il caso che check_findings racconta
                        per H52 (contata e non raccontata).
   · e in docs/NB1777.md §2 le famiglie, «(6)», «(9)»…, devono sommare a nb1777_tool.

🚫 COSA NON CONTA, dichiarato perché non lo si scopra da un verde:
   · i check obbligatori su `main`: la fonte è un'impostazione del repository su GitHub
     (branch protection), non un file del repo, e in CI non c'è un token per leggerla.
     SECURITY.md li elenca: lì il numero lo tiene la mano, non questo presidio.
   · i file di test in tools/tests/: nessun documento ne ripete il numero.
   · la tabella dei residui di SECURITY.md e la frase «Il registro conta N voci»: le
     controlla già check_findings.py, e due guardiani sulla stessa riga litigano.

⚖️ LA REGOLA DI ESCLUSIONE — per costruzione, non per eccezione:
   1. si leggono SOLO i file nominati in FRASI. Il CHANGELOG, docs/roadmap/ e i piani non
      ci sono: raccontano il passato per mestiere.
   2. dentro quei file, una riga che porta una VERSIONE (`0.44.1`, `v0.40.x`, `v0.31`) o
      una DATA (`27/08`, `01/10/2026`, `2026-09-28`) è STORICA e si salta: un numero vero
      alla sua data non è una deriva (origine ≠ impatto). Le righe saltate si contano e si
      stampano. ⇒ una tabella per versione («v0.62.x: 9 check») non fa mai scattare.
   3. le regex sono ANCORATE alle parole intorno (`ne espone **N**`, `N tool, in sei
      famiglie`): un numero qualunque vicino a «tool» non basta.
   ⚠️ IL LIMITE, e la sua cura: una frase riscritta in una forma nuova non la vede nessuna
      regex. Perché il presidio non si stacchi in silenzio, OGNI frase dichiarata deve
      comparire almeno una volta, su una riga non storica, nel suo file: se non c'è più è
      un errore («frase non trovata»), come in check_findings un gate che non trova il suo
      bersaglio. Si cura aggiornando la frase qui, non togliendola.

Uso:  python3 tools/fatti-nei-doc.py              # exit 1 se una pagina dice un altro numero
      python3 tools/fatti-nei-doc.py --autoprova  # prova che sa dire di NO (e di sì)
"""
from __future__ import annotations

import ast
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent

# I numeri si scrivono anche in lettere («**sei** container»). Solo quelli che servono.
PAROLE = {
    "uno": 1, "una": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5, "sei": 6,
    "sette": 7, "otto": 8, "nove": 9, "dieci": 10, "undici": 11, "dodici": 12,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}
N = r"(?:\d+|" + "|".join(sorted(PAROLE, key=len, reverse=True)) + r")"

# Riga storica: una versione o una data (regola 2 del docstring).
STORICA = re.compile(
    r"\bv?\d+\.\d+\.(?:\d+|x)\b"          # 0.44.1 · v0.40.x
    r"|\bv\d+\.\d+\b"                      # v0.31
    r"|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b"   # 27/08 · 01/10/2026
    r"|\b\d{4}-\d{2}-\d{2}\b"              # 2026-09-28
)

FATTI = {
    "nb1777_tool": "tool MCP di nb1777 (`@mcp.tool` in services/nb1777-mcp/app/server.py)",
    "archive_tool": "tool MCP di archive (`@mcp.tool` in services/archive-mcp/app/server.py)",
    "immagini": "immagini pubblicate (matrice di .github/workflows/release.yml)",
    "immagini_stack": "immagini della matrice che compose.yaml usa",
    "servizi_stack": "servizi di compose.yaml senza profilo",
    "container_default": "container con le feature di default e l'ingresso Tailscale",
    "rilievi": "voci di security/findings.yml",
    "rilievi_chiusi": "voci `closed` del registro",
    "rilievi_parziali": "voci `partial` del registro",
    "rilievi_accettati": "voci `accepted` del registro",
    "rilievi_aperti": "voci `open` del registro",
    "rilievi_non_chiusi": "voci non `closed` del registro",
}


@dataclass(frozen=True)
class Frase:
    file: str
    regex: str   # gruppi con nome = chiavi di FATTI; `{N}` = un numero, in cifre o in lettere

    def compilata(self) -> re.Pattern:
        return re.compile(self.regex.replace("{N}", N))


FRASI = [
    # ── nb1777: i tool ────────────────────────────────────────────────────────
    Frase("README.md", r"`nlm` CLI — \*\*(?P<nb1777_tool>{N}) tools\*\*"),
    Frase("README.md", r"NotebookLM: the (?P<nb1777_tool>{N}) MCP tools"),
    Frase("README.it.md", r"CLI `nlm` — \*\*(?P<nb1777_tool>{N}) tool\*\*"),
    Frase("README.it.md", r"NotebookLM: i (?P<nb1777_tool>{N}) tool MCP"),
    Frase("docs/INSTALL.md", r"`nb1777` ne espone \*\*(?P<nb1777_tool>{N})\*\*"),
    Frase("docs/en/INSTALL.md", r"`nb1777` exposes \*\*(?P<nb1777_tool>{N})\*\*"),
    Frase("installer/README.md", r"`nb1777` ne espone (?P<nb1777_tool>{N})\*\*"),
    Frase("docs/NB1777.md", r"I conteggi di questa pagina \((?P<nb1777_tool>{N}) tool,"),
    Frase("docs/NB1777.md", r"§2 — I tool MCP, per famiglia \((?P<nb1777_tool>{N})\)"),
    Frase("docs/NB1777.md", r"rumore su ogni tool \(oggi (?P<nb1777_tool>{N})\)"),
    Frase("docs/NB1777.md", r"tool MCP — l'header dice (?P<nb1777_tool>{N})\b"),
    Frase("docs/NB1777.md", r"Il resto — (?P<nb1777_tool>{N}) tool,"),
    Frase("services/nb1777-mcp/README.md", r"^(?P<nb1777_tool>{N}) tool, in sei famiglie"),
    # ── archive: i tool ───────────────────────────────────────────────────────
    Frase("README.md", r"`get_stirpe`\): \*\*(?P<archive_tool>{N}) tools\*\*"),
    Frase("README.md", r"the (?P<archive_tool>{N}) MCP tools, sessions and lineages"),
    Frase("README.it.md", r"`get_stirpe`\): \*\*(?P<archive_tool>{N}) tool\*\*"),
    Frase("README.it.md", r"i (?P<archive_tool>{N}) tool MCP, sessioni e stirpi"),
    Frase("installer/README.md", r"\*\*`archive` espone (?P<archive_tool>{N}) tool\*\*"),
    Frase("docs/ARCHIVE.md", r"attraverso i \*\*(?P<archive_tool>{N}) tool MCP\*\*"),
    Frase("docs/ARCHIVE.md", r"`archive-mcp` espone \*\*(?P<archive_tool>{N}) tool\*\*"),
    Frase("docs/en/ARCHIVE.md", r"through the \*\*(?P<archive_tool>{N}) MCP tools\*\*"),
    Frase("docs/en/ARCHIVE.md", r"`archive-mcp` exposes \*\*(?P<archive_tool>{N}) tools\*\*"),
    # ── le immagini del progetto ──────────────────────────────────────────────
    Frase("SECURITY.md", r"sulle (?P<immagini>{N}) immagini \*\*pubblicate\*\* "
                         r"\(le (?P<immagini_stack>{N}) dello stack"),
    Frase("SECURITY.md", r"chiusura-issue, le (?P<immagini>{N}) build\)"),
    Frase("features.yaml", r"Trivy settimanale sulle (?P<immagini>{N}) immagini pubblicate"),
    Frase(".github/workflows/release.yml", r"\(le (?P<immagini_stack>{N}) dello stack \+"),
    Frase(".github/workflows/rebuild-mensile.yml", r"la SOMMA sulle (?P<immagini>{N}) immagini"),
    Frase("docs/PRIMI-15-MINUTI.md", r"si scaricano (?P<immagini_stack>{N}) immagini da GHCR"),
    Frase("docs/PRIMI-15-MINUTI.md", r"\(le (?P<immagini_stack>{N}) dello stack, più `alpine`"),
    # ── i container ───────────────────────────────────────────────────────────
    Frase("docs/PRIMI-15-MINUTI.md", r"I \*\*(?P<servizi_stack>{N}) servizi\*\* dello stack"),
    Frase("docs/PRIMI-15-MINUTI.md", r"i (?P<servizi_stack>{N}) dello stack `Up"),
    Frase("docs/PRIMI-15-MINUTI.md", r"\*\*(?P<container_default>{N})\*\* container —"),
    Frase("docs/PRIMI-15-MINUTI.md", r"i (?P<container_default>{N}) container rimossi"),
    # ── il registro dei rilievi, fuori dalla tabella che controlla check_findings ──
    Frase("SECURITY.md", r"(?:I|Gli) (?P<rilievi>{N}) rilievi vivono in"),
    Frase("REVIEW.md", r"(?P<rilievi>{N}) voci, \*\*(?P<rilievi_chiusi>{N}) chiuse\*\*, e le "
                       r"\*\*(?P<rilievi_non_chiusi>{N}) qui sotto non chiuse\*\* "
                       r"\((?P<rilievi_parziali>{N}) parziali, "
                       r"(?P<rilievi_accettati>{N}) accettate\)"),
    Frase("docs/ARCHITECTURE.md", r"(?P<rilievi>{N}) rilievi: (?P<rilievi_chiusi>{N}) chiusi, "
                                  r"(?P<rilievi_parziali>{N}) parziali, "
                                  r"(?P<rilievi_accettati>{N}) accettati, "
                                  r"(?P<rilievi_aperti>{N}) aperti"),
    Frase("docs/en/ARCHITECTURE.md", r"(?P<rilievi>{N}) findings: (?P<rilievi_chiusi>{N}) closed, "
                                     r"(?P<rilievi_parziali>{N}) partial, "
                                     r"(?P<rilievi_accettati>{N}) accepted, "
                                     r"(?P<rilievi_aperti>{N}) open"),
]

# Le fonti che i conteggi leggono: servono anche all'autoprova e al test, che lavorano
# su una COPIA del repo ridotta a questi file più i documenti di FRASI.
SORGENTI = [
    "services/nb1777-mcp/app/server.py", "services/archive-mcp/app/server.py",
    ".github/workflows/release.yml", ".github/workflows/ci.yml",
    ".github/workflows/trivy.yml", ".github/workflows/rebuild-mensile.yml",
    "compose.yaml", "compose.ingress.tailscale.yaml", "compose.ops.backup.yaml",
    "compose.ops.portainer.yaml", "compose.ops.caddy-dns01.yaml",
    "tools/vps1777.py", "security/findings.yml", "REVIEW.md", "docs/NB1777.md",
]


def numero(s: str) -> int:
    return int(s) if s.isdigit() else PAROLE[s.lower()]


def _leggi(repo: Path, rel: str) -> str:
    return (repo / rel).read_text(encoding="utf-8")


# ── i conteggi ────────────────────────────────────────────────────────────────

def _tool(repo: Path, rel: str) -> int:
    # a inizio riga: un commento che NOMINA il decoratore non è un tool (archive-mcp ne ha due)
    return len(re.findall(r"^@mcp\.tool\(", _leggi(repo, rel), re.M))


def _matrice(repo: Path, rel: str) -> list[str]:
    m = re.search(r"^\s*service:\s*\[([^\]]*)\]", _leggi(repo, rel), re.M)
    return [s.strip() for s in m.group(1).split(",") if s.strip()] if m else []


def servizi_compose(testo: str) -> dict[str, list[str]]:
    """{servizio: profili} letto per righe: i servizi sono le chiavi a due spazi sotto
    `services:`, i profili la riga `profiles:` del servizio (in linea o a elenco)."""
    out: dict[str, list[str]] = {}
    dentro, cur, in_profili = False, None, False
    for riga in testo.splitlines():
        if not riga.strip() or riga.lstrip().startswith("#"):
            continue
        if re.match(r"^\S", riga):
            dentro, cur, in_profili = riga.startswith("services:"), None, False
            continue
        if not dentro:
            continue
        if m := re.match(r"^  ([A-Za-z0-9_.-]+):\s*$", riga):
            cur, in_profili = m.group(1), False
            out[cur] = []
            continue
        if cur is None:
            continue
        if m := re.match(r"^    profiles:\s*(.*)$", riga):
            resto = m.group(1).strip()
            in_profili = not resto
            if resto.startswith("["):
                out[cur] = [p.strip().strip("'\"") for p in resto.strip("[]").split(",")
                            if p.strip()]
            continue
        if in_profili and (m := re.match(r"^      -\s*(\S+)", riga)):
            out[cur].append(m.group(1).strip("'\""))
            continue
        if re.match(r"^    \S", riga):
            in_profili = False
    return out


def _letterale(repo: Path, nome: str):
    """Il valore letterale di una costante di primo livello di tools/vps1777.py, senza
    importarlo (l'import ha effetti, e qui serve solo leggere)."""
    albero = ast.parse(_leggi(repo, "tools/vps1777.py"))
    for nodo in albero.body:
        bersaglio = (nodo.targets[0] if isinstance(nodo, ast.Assign) else
                     nodo.target if isinstance(nodo, ast.AnnAssign) else None)
        if isinstance(bersaglio, ast.Name) and bersaglio.id == nome:
            return ast.literal_eval(nodo.value)
    raise LookupError(f"tools/vps1777.py: non trovo `{nome}`")


def container_default(repo: Path) -> set[str]:
    feat = set(_letterale(repo, "DEFAULT_FEATURES"))
    ops = _letterale(repo, "OPS_COMPOSE_FEATURES")
    file = ["compose.yaml", "compose.ingress.tailscale.yaml"]
    profili = {"ingress.tailscale"}
    for f in sorted(feat & set(ops)):
        stem, profilo = ops[f]
        file.append(f"compose.{stem}.yaml")
        if profilo:
            profili.add(profilo)
    attivi: set[str] = set()
    for rel in file:
        for nome, prof in servizi_compose(_leggi(repo, rel)).items():
            if not prof or set(prof) & profili:
                attivi.add(nome)
    return attivi


def registro(repo: Path) -> dict[str, str]:
    """{id: status} da security/findings.yml, per righe (stdlib)."""
    out: dict[str, str] = {}
    cur = None
    for riga in _leggi(repo, "security/findings.yml").splitlines():
        if m := re.match(r"^  - id:\s*(\S+)", riga):
            cur = m.group(1).strip("'\"")
            out[cur] = ""
        elif cur and (m := re.match(r"^    status:\s*(\w+)", riga)):
            out[cur] = m.group(1)
    return out


def conta(repo: Path) -> tuple[dict[str, int], list[str]]:
    """(i conteggi, le incoerenze fra fonti). Le incoerenze sono errori anche loro."""
    incoerenze: list[str] = []
    immagini = _matrice(repo, ".github/workflows/release.yml")
    if not immagini:
        incoerenze.append("release.yml: non trovo la matrice `service: [...]` — senza, il "
                          "conteggio delle immagini non ha una fonte")
    for rel in (".github/workflows/ci.yml", ".github/workflows/trivy.yml"):
        altra = _matrice(repo, rel)
        if set(altra) != set(immagini):
            incoerenze.append(f"{rel}: la matrice dice {sorted(altra)}, release.yml "
                              f"{sorted(immagini)} — un'immagine pubblicata e non "
                              f"costruita in CI o non scansionata")
    m = re.search(r"for s in ([A-Za-z0-9 _-]+); do",
                  _leggi(repo, ".github/workflows/rebuild-mensile.yml"))
    mensile = m.group(1).split() if m else []
    if set(mensile) != set(immagini):
        incoerenze.append(f".github/workflows/rebuild-mensile.yml: il `for s in` dice "
                          f"{sorted(mensile)}, release.yml {sorted(immagini)}")
    compose = _leggi(repo, "compose.yaml")
    stack = [s for s in immagini if re.search(rf"/vps1777-{re.escape(s)}:", compose)]
    servizi = servizi_compose(compose)
    reg = registro(repo)
    stati = list(reg.values())
    conti = {
        "nb1777_tool": _tool(repo, "services/nb1777-mcp/app/server.py"),
        "archive_tool": _tool(repo, "services/archive-mcp/app/server.py"),
        "immagini": len(immagini),
        "immagini_stack": len(stack),
        "servizi_stack": sum(1 for p in servizi.values() if not p),
        "container_default": len(container_default(repo)),
        "rilievi": len(reg),
        "rilievi_chiusi": stati.count("closed"),
        "rilievi_parziali": stati.count("partial"),
        "rilievi_accettati": stati.count("accepted"),
        "rilievi_aperti": stati.count("open"),
        "rilievi_non_chiusi": len(stati) - stati.count("closed"),
    }

    # REVIEW.md: la tabella delle voci non chiuse nomina ESATTAMENTE quelle del registro.
    tabella = {m.group(1): m.group(2) for m in re.finditer(
        r"^\| (H\d+) \| \**(partial|accepted|open|closed)\** \|", _leggi(repo, "REVIEW.md"), re.M)}
    attese = {i: s for i, s in reg.items() if s != "closed"}
    if tabella != attese:
        for i in sorted(set(attese) - set(tabella)):
            incoerenze.append(f"REVIEW.md: {i} è `{attese[i]}` nel registro e la tabella "
                              f"delle voci non chiuse non lo nomina")
        for i in sorted(set(tabella) - set(attese)):
            incoerenze.append(f"REVIEW.md: la tabella nomina {i} come `{tabella[i]}`, nel "
                              f"registro è `{reg.get(i, 'assente')}`")
        for i in sorted(set(tabella) & set(attese)):
            if tabella[i] != attese[i]:
                incoerenze.append(f"REVIEW.md: {i} è `{tabella[i]}` in tabella e "
                                  f"`{attese[i]}` nel registro")

    # docs/NB1777.md §2: le famiglie sommano al totale.
    nb = _leggi(repo, "docs/NB1777.md")
    sez = re.search(r"^## §2\b.*?(?=^## §)", nb, re.M | re.S)
    if sez:
        famiglie = [int(x) for x in re.findall(r"^\*\*[^*\n]+\((\d+)\)\*\*", sez.group(0), re.M)]
        if sum(famiglie) != conti["nb1777_tool"]:
            incoerenze.append(f"docs/NB1777.md §2: le famiglie {famiglie} sommano a "
                              f"{sum(famiglie)}, i tool sono {conti['nb1777_tool']}")
    else:
        incoerenze.append("docs/NB1777.md: non trovo la sezione «## §2» con le famiglie dei tool")
    return conti, incoerenze


# ── il confronto ──────────────────────────────────────────────────────────────

@dataclass
class Esito:
    conti: dict[str, int]
    viste: int          # numeri confrontati
    saltate: int        # righe che combaciavano ma sono storiche (regola 2)
    errori: list[str]


def controlla(repo: Path) -> Esito:
    conti, errori = conta(repo)
    viste = saltate = 0
    righe_cache: dict[str, list[str]] = {}
    for fr in FRASI:
        if fr.file not in righe_cache:
            p = repo / fr.file
            righe_cache[fr.file] = (p.read_text(encoding="utf-8").splitlines()
                                    if p.is_file() else [])
        righe = righe_cache[fr.file]
        if not righe:
            errori.append(f"{fr.file}: file assente o vuoto — la frase «{fr.regex}» non ha "
                          f"dove stare")
            continue
        rx, trovata = fr.compilata(), False
        for i, riga in enumerate(righe, 1):
            for m in rx.finditer(riga):
                if STORICA.search(riga):
                    saltate += 1
                    continue
                trovata = True
                for chiave, testo in m.groupdict().items():
                    viste += 1
                    detto, vero = numero(testo), conti[chiave]
                    if detto != vero:
                        estratto = m.group(0)
                        errori.append(f"{fr.file}:{i}  «{estratto}» — dice {detto} "
                                      f"({FATTI[chiave]}), il codice ne conta {vero}")
        if not trovata:
            errori.append(f"{fr.file}: frase non trovata «{fr.regex}». Se l'hai riscritta, "
                          f"aggiorna FRASI in tools/fatti-nei-doc.py: un presidio che non "
                          f"trova più il suo bersaglio TACE, e il silenzio somiglia a un ok")
    return Esito(conti, viste, saltate, errori)


def stampa(e: Esito) -> int:
    file = len({f.file for f in FRASI})
    print(f"📏 {e.viste} numeri in {len(FRASI)} frasi di {file} file, contro "
          f"{len(e.conti)} conteggi del codice"
          + (f" · {e.saltate} righe storiche saltate (versione o data)" if e.saltate else ""))
    opz = e.conti["immagini"] - e.conti["immagini_stack"]
    print(f"   nb1777 {e.conti['nb1777_tool']} tool · archive {e.conti['archive_tool']} tool · "
          f"{e.conti['immagini']} immagini ({opz} opzionali) · "
          f"{e.conti['servizi_stack']} servizi nello stack, "
          f"{e.conti['container_default']} container di default · "
          f"{e.conti['rilievi']} rilievi ({e.conti['rilievi_chiusi']} chiusi)\n")
    for err in e.errori:
        print(f"  🔴 {err}")
    if e.errori:
        print(f"\n⛔ {len(e.errori)} punti in cui la documentazione non dice ciò che il codice conta.\n"
              "   Allinea il documento, non il codice: il numero giusto è quello contato.")
        return 1
    print("✅ ogni numero ripetuto nei documenti è quello che il codice conta.\n"
          "   ⚠️ Vede solo le frasi di FRASI: una forma nuova va aggiunta lì.")
    return 0


def main() -> int:
    return stampa(controlla(RADICE))


# ── l'autoprova ───────────────────────────────────────────────────────────────

def copia_minima(da: Path, a: Path) -> None:
    """Le fonti e i documenti che il presidio legge, e nient'altro."""
    for rel in sorted(set(SORGENTI) | {f.file for f in FRASI}):
        dest = a / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(da / rel, dest)


def _sostituisci(p: Path, vecchio: str, nuovo: str) -> None:
    t = p.read_text(encoding="utf-8")
    assert vecchio in t, f"autoprova: «{vecchio}» non è in {p}"
    p.write_text(t.replace(vecchio, nuovo, 1), encoding="utf-8")


def _autoprova() -> int:
    print("🔬 autoprova di fatti-nei-doc.py\n")
    ko = 0

    def caso(nome: str, ok: bool, dettaglio: object) -> None:
        nonlocal ko
        if ok:
            print(f"  ✅ {nome:<58} → {dettaglio}")
        else:
            ko += 1
            print(f"  🔴 {nome:<58} → {dettaglio}")

    vero = controlla(RADICE).conti
    with tempfile.TemporaryDirectory() as d:
        repo = Path(d)
        copia_minima(RADICE, repo)

        # ① il caso buono: la copia del repo, così com'è, non ha errori.
        e = controlla(repo)
        caso("la copia del repo com'è → nessun errore", not e.errori, e.errori or f"{e.viste} numeri")

        # ② LA DOMANDA CHE CONTA: sa dire di NO? Un numero sbagliato in una pagina.
        p = repo / "docs" / "INSTALL.md"
        n = vero["nb1777_tool"]
        _sostituisci(p, f"ne espone **{n}**", f"ne espone **{n - 1}**")
        riga = next(i for i, r in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
                    if f"ne espone **{n - 1}**" in r)
        e = controlla(repo)
        caso("un numero sbagliato → UN errore, con file:riga",
             len(e.errori) == 1 and e.errori[0].startswith(f"docs/INSTALL.md:{riga} "),
             e.errori)
        _sostituisci(p, f"ne espone **{n - 1}**", f"ne espone **{n}**")

        # ③ il numero scritto in lettere si legge come quello in cifre.
        p = repo / "docs" / "PRIMI-15-MINUTI.md"
        c = vero["container_default"]
        parola = next(k for k, v in PAROLE.items() if v == c + 1)
        t = p.read_text(encoding="utf-8")
        m = re.search(r"i (" + N + r") container rimossi", t)
        _sostituisci(p, m.group(0), f"i {parola} container rimossi")
        e = controlla(repo)
        caso("un numero in lettere sbagliato → errore", len(e.errori) == 1 and
             "container" in e.errori[0], e.errori)
        _sostituisci(p, f"i {parola} container rimossi", m.group(0))

        # ④ una riga STORICA (con una data) col numero vecchio non fa scattare.
        p = repo / "docs" / "INSTALL.md"
        with p.open("a", encoding="utf-8") as f:
            f.write(f"\nIl 24/09/2026 `nb1777` ne espone **{n - 1}** (riga storica).\n")
        e = controlla(repo)
        caso("una riga datata col numero vecchio → saltata, nessun errore",
             not e.errori and e.saltate >= 1, e.errori or f"{e.saltate} saltate")

        # ⑤ il codice si muove: un tool in più e TUTTE le frasi di nb1777 diventano rosse.
        p = repo / "services" / "nb1777-mcp" / "app" / "server.py"
        with p.open("a", encoding="utf-8") as f:
            f.write("\n\n@mcp.tool()\nasync def tool_in_piu() -> str:\n    return ''\n")
        e = controlla(repo)
        attese = sum(1 for fr in FRASI if "nb1777_tool" in fr.regex)
        rossi_nb = [x for x in e.errori if "nb1777" in x.lower()]
        caso(f"un tool in più nel codice → {attese} frasi + la somma delle famiglie",
             len(rossi_nb) == attese + 1, f"{len(rossi_nb)} errori")

    with tempfile.TemporaryDirectory() as d:
        repo = Path(d)
        copia_minima(RADICE, repo)
        # ⑥ una frase riscritta in un'altra forma: il presidio non deve TACERE.
        p = repo / "README.md"
        _sostituisci(p, "NotebookLM: the ", "NotebookLM — the ")
        e = controlla(repo)
        caso("una frase che non c'è più → «frase non trovata»",
             len(e.errori) == 1 and "frase non trovata" in e.errori[0], e.errori)

        # ⑦ REVIEW.md perde una riga della tabella: il conteggio torna, il nome no.
        p = repo / "REVIEW.md"
        t = p.read_text(encoding="utf-8")
        m = re.search(r"^\| (H\d+) \| partial \|.*\n", t, re.M)
        p.write_text(t.replace(m.group(0), "", 1), encoding="utf-8")
        _sostituisci(repo / "README.md", "NotebookLM — the ", "NotebookLM: the ")
        e = controlla(repo)
        caso("REVIEW.md senza una voce partial → errore che la nomina",
             len(e.errori) == 1 and m.group(1) in e.errori[0], e.errori)

    if ko:
        print(f"\n⛔ {ko} casi sbagliati.", file=sys.stderr)
        return 1
    print("\n✅ 7 su 7: dice di no sul numero sbagliato (in cifre e in lettere), tace sulla\n"
          "   riga storica, si accorge quando il codice si muove e quando perde una frase.")
    return 0


if __name__ == "__main__":
    sys.exit(_autoprova() if "--autoprova" in sys.argv else main())
