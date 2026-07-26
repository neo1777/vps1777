#!/usr/bin/env python3
"""
Il guardiano del registro dei rilievi.

PERCHÉ ESISTE. SECURITY.md ha dichiarato «il dossier è applicato per intero»
quando 8 rilievi su 43 erano chiusi. Nessuno se n'è accorto perché quella frase
non puntava a nulla: un claim senza coordinata è infalsificabile, quindi marcisce
in silenzio invece che rumorosamente.

Questo script rende impossibile ripeterlo. Gira in CI e fallisce se:

  1. una voce `closed` non porta evidenza, o la sua evidenza NON C'È PIÙ nel codice
     → è il caso «dichiarato fatto ma assente»;
  2. una voce `partial`/`open` non dichiara che cosa manca
     → è il caso «soluzione scritta ma non applicata», detta a mezza bocca;
  3. il conteggio dichiarato in SECURITY.md non combacia col registro
     → è lo scostamento doc↔codice (H21), commesso dal documento di sicurezza stesso.

Non prova che il fix sia CORRETTO — prova che è ANCORA LÌ. È un antidoto al
marcire, non un sostituto della review.

Uso:
    uv run --with pyyaml security/check_findings.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "security" / "findings.yml"
SECURITY_MD = ROOT / "SECURITY.md"

# `accepted` = la review l'ha sollevato, l'abbiamo considerato, e abbiamo deciso
# di NON agire, con una motivazione. È un esito legittimo (risk acceptance): non
# è "chiuso" (niente è stato fatto) né "aperto" (non è dimenticato, è una scelta).
VALID_STATUS = {"closed", "partial", "open", "accepted"}
VALID_SEVERITY = {"critical", "high", "medium", "low"}
# Quante voci il registro DEVE avere per fascia: se non le rispetta, qualcuno
# ha aggiunto o perso un rilievo per strada. L'àncora si muove SOLO con un
# commit deliberato che nomina le voci nuove — mai per far passare la CI.
# Provenienza dei numeri: 43 dal dossier della review difensiva originaria
# (2 critical · 7 high · 21 medium · 13 low) + 7 dal ciclo di audit con misure
# sul vivo chiuso in v0.40.3 (H44-H48 medium · H49 low · H50 high) = 50.
# NB: questo scostamento è rimasto invisibile per un giorno intero perché
# tutti leggevamo la coda dell'output senza l'exit code — il registro era a
# 44+ dal round-2 e ogni «checker verde» dichiarato quel giorno era falso.
EXPECTED_TOTAL = 50
EXPECTED_BY_SEVERITY = {"critical": 2, "high": 8, "medium": 26, "low": 14}

RED, GRN, YEL, DIM, OFF = "\033[31m", "\033[32m", "\033[33m", "\033[2m", "\033[0m"
if not sys.stdout.isatty():
    RED = GRN = YEL = DIM = OFF = ""


def fail(errors: list[str], msg: str) -> None:
    errors.append(msg)


def check_titolo_nomina_file(f: dict, errors: list[str]) -> None:
    """Se il TITOLO nomina un file che esiste nel repo, quel file dev'essere fra le evidence.

    Nasce da H43 (27/07): titolo «sandbox update.service», `closed`, CI verde — e le
    sue prove verificavano un'ALTRA unit. Togliendo ogni direttiva di sandbox dal
    servizio nominato nel titolo il gate restava verde: la voce era presidiata su un
    oggetto diverso da quello che dichiarava.

    La condizione «che esiste nel repo» non è un dettaglio: senza, il controllo
    accusava anche H36, il cui titolo nomina `pending.json` — un file di RUNTIME, mai
    versionato, che NON PUÒ essere un'evidence. Misurato da abdd732a prima di
    proporre il presidio: 4 voci nominano un file nel titolo, 2 sembravano difettose,
    1 lo era davvero. Un presidio che accusa una voce sana è quello che si impara a
    ignorare.

    LIMITI, dichiarati perché il verde non prometta più di quel che vale:
      · guarda i TITOLI, non il corpo: una voce che nomina il file sbagliato nella
        prosa passa (un pattern sul corpo produrrebbe rumore, non è stato misurato);
      · verifica che il file COMPAIA fra le evidence, non che l'evidenza dica
        qualcosa di vero su di esso. Chiude «il titolo parla di un file che la prova
        non guarda», non «la prova lo guarda e non prova niente».
    """
    titolo = str(f.get("title", ""))
    citati = {m for m in re.findall(r"[\w./-]+\.(?:py|sh|yml|yaml|json|service|timer|md|toml)", titolo)}
    if not citati:
        return
    coperti = {str(ev.get("file", "")) for ev in (f.get("evidence") or [])}
    for nome in sorted(citati):
        # Il file dev'essere VERSIONATO: uno di runtime non può essere un'evidence.
        # 🔴 La prima versione usava rglob(nome) — match ESATTO sul nome — e non
        # trovava nulla: il titolo dice «update.service», il file si chiama
        # `vps1777-update.service`. Il presidio girava, dava verde, e non poteva
        # prendere il caso per cui era stato scritto. Scoperto con la controprova
        # (rimettere H43 allo stato rotto): senza, sarebbe stato committato come
        # «classe chiusa». Ora il match è per SUFFISSO, come si nominano i file
        # in un titolo: per nome corto, non per percorso completo.
        reali = [q for q in ROOT.rglob(f"*{nome}")
                 if ".git" not in q.parts and q.is_file()]
        if not reali:
            continue
        if not any(nome in c for c in coperti):
            fail(errors,
                 f"{f['id']}: il titolo nomina «{nome}», che esiste nel repo, ma nessuna\n"
                 f"       evidence lo verifica. La voce è presidiata su un altro oggetto:\n"
                 f"       si potrebbe svuotare {nome} e questo gate resterebbe verde.")


def check_evidence(f: dict, errors: list[str]) -> None:
    """L'evidenza di una voce esiste ancora nel codice?"""
    fid = f["id"]
    for ev in f.get("evidence") or []:
        path = ROOT / ev["file"]
        if not path.is_file():
            fail(errors, f"{fid}: l'evidenza punta a un file che non esiste — {ev['file']}")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for needle in ev.get("contains") or []:
            if needle not in text:
                fail(errors,
                     f"{fid}: EVIDENZA SPARITA — «{needle}» non è più in {ev['file']}.\n"
                     f"       O il fix è stato rimosso, o l'evidenza va aggiornata. "
                     f"Non lasciare la voce a `{f['status']}` senza guardare.")
        for needle in ev.get("not_contains") or []:
            if needle in text:
                fail(errors,
                     f"{fid}: REGRESSIONE — «{needle}» è RITORNATO in {ev['file']}.\n"
                     f"       Il fix dichiarava che non ci fosse.")


def main() -> int:
    errors: list[str] = []

    if not REGISTRY.is_file():
        print(f"{RED}registro assente: {REGISTRY}{OFF}")
        return 1

    data = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    findings = data.get("findings") or []

    seen: set[str] = set()
    counts = {"closed": 0, "partial": 0, "open": 0, "accepted": 0}
    by_sev: dict[str, int] = {}

    for f in findings:
        fid = f.get("id", "<senza id>")

        # schema
        if fid in seen:
            fail(errors, f"{fid}: id duplicato")
        seen.add(fid)

        status = f.get("status")
        if status not in VALID_STATUS:
            fail(errors, f"{fid}: status «{status}» non valido")
            continue
        counts[status] += 1

        sev = f.get("severity")
        if sev not in VALID_SEVERITY:
            fail(errors, f"{fid}: severity «{sev}» non valida")
        else:
            by_sev[sev] = by_sev.get(sev, 0) + 1

        if not f.get("title"):
            fail(errors, f"{fid}: manca il titolo")

        # LA REGOLA: niente claim senza coordinata.
        if status == "closed" and not f.get("evidence"):
            fail(errors,
                 f"{fid}: dichiarata CHIUSA senza evidenza.\n"
                 f"       Se non sai scrivere l'evidenza, non è chiusa.")

        # LA REGOLA GEMELLA: niente «non fatto» senza dire cosa manca.
        if status in {"partial", "open"} and not f.get("missing"):
            fail(errors,
                 f"{fid}: è `{status}` ma non dichiara cosa manca.\n"
                 f"       Un residuo taciuto è un residuo dimenticato.")

        # Un rischio accettato senza motivazione è un rischio nascosto.
        if status == "accepted" and not (f.get("missing") or f.get("rationale")):
            fail(errors,
                 f"{fid}: è `accepted` ma non dice PERCHÉ non si fa.\n"
                 f"       Accettare un rischio in silenzio è peggio che non accettarlo.")

        check_evidence(f, errors)
        check_titolo_nomina_file(f, errors)

    # l'àncora: il totale atteso, dichiarato in testa con la sua provenienza
    total = len(findings)
    if total != EXPECTED_TOTAL:
        fail(errors, f"il registro ha {total} voci, l'àncora ne dichiara {EXPECTED_TOTAL}")
    for sev, expected in EXPECTED_BY_SEVERITY.items():
        got = by_sev.get(sev, 0)
        if got != expected:
            fail(errors, f"fascia {sev}: {got} voci nel registro, {expected} nel dossier")

    # ── il conteggio in SECURITY.md deve combaciare col registro ──
    # È il loop che si chiude: il documento non può più dichiarare più del codice.
    if SECURITY_MD.is_file():
        md = SECURITY_MD.read_text(encoding="utf-8")
        for label, key in (("chiusi", "closed"), ("parziali", "partial"),
                           ("accettati", "accepted"), ("aperti", "open")):
            m = re.search(rf"\*\*{label}\*\*\s*\|\s*(\d+)", md)
            if not m:
                fail(errors, f"SECURITY.md: non trovo il conteggio «{label}» nella tabella dei residui")
            elif int(m.group(1)) != counts[key]:
                fail(errors,
                     f"SECURITY.md dichiara {m.group(1)} «{label}», il registro ne conta "
                     f"{counts[key]}.\n"
                     f"       È lo scostamento doc↔codice (H21). Allinea il documento, "
                     f"non il registro — il registro lo verifica il codice.")

    # ── esito ──
    print(f"{DIM}registro: {total} rilievi · "
          f"{GRN}{counts['closed']} chiusi{OFF}{DIM} · "
          f"{YEL}{counts['partial']} parziali{OFF}{DIM} · "
          f"{DIM}{counts['accepted']} accettati · "
          f"{RED}{counts['open']} aperti{OFF}")

    if errors:
        print(f"\n{RED}✗ il registro non regge — {len(errors)} problemi:{OFF}\n")
        for e in errors:
            print(f"  {RED}•{OFF} {e}")
        print(f"\n{DIM}Nessun claim senza coordinata. Nessun residuo taciuto.{OFF}")
        return 1

    print(f"{GRN}✓ ogni voce chiusa ha la sua evidenza, e l'evidenza c'è ancora.{OFF}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
