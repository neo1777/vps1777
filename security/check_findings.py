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
CHANGELOG = ROOT / "CHANGELOG.md"

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
# sul vivo chiuso in v0.40.3 (H44-H48 medium · H49 low · H50 high) = 50,
# + 1 (H51 high, 27/07) = 51, + 1 (H52 medium, 27/07) = 52.
# H51 non nasce da una lettura: nasce da un incidente in produzione — il presidio
# di salute sonda il loopback da dentro il container e non può vedere un servizio
# irraggiungibile. H52 non nasce da noi: l'ha nominata l'analisi esterna del
# round-7 — «il registro convalida un'etichetta di testo invece del comportamento»
# — ed è vera di QUESTO file, che qui sotto fa `if needle not in text`.
# NB: questo scostamento è rimasto invisibile per un giorno intero perché
# tutti leggevamo la coda dell'output senza l'exit code — il registro era a
# 44+ dal round-2 e ogni «checker verde» dichiarato quel giorno era falso.
# + 1 (H53 medium, 27/07) = 53. H53 non nasce da una lettura né da un audio:
# nasce dal misurare la copertura dei gate invece di leggerla — lo step shellcheck
# girava con `|| true` e nascondeva un bug vero nella ritenzione dei backup.
# + 1 (H54 medium, 27/07) = 54. H54 nasce da un rilievo dell'analisi esterna del
# round-7 che il registro copriva solo di sponda: H44 era `closed` sulla lacuna
# DOCUMENTALE, e il rischio sotto non aveva una voce propria — chi cercava il
# residuo sotto `partial` non trovava niente.
# + 1 (H55 medium, 27/07) = 55. H55 non è stata letta: è stata TROVATA aggiornando
# davvero la macchina — `vps1777 update`, il comando che la documentazione consiglia,
# moriva con un traceback su un file che serve solo a disegnare una barra.
# + 1 (H56 medium, 27/07) = 56. H56 è la seconda metà di H14, misurata sulla VPS viva
# da abdd732a: lo snapshot pre-update tiene archive-data IN CHIARO (~2,58 GB) e nessuna
# voce lo diceva — H14 era `closed` su un volume solo, il più piccolo.
EXPECTED_TOTAL = 56
EXPECTED_BY_SEVERITY = {"critical": 2, "high": 9, "medium": 31, "low": 14}

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


SINCE_NON_RILASCIATO = "unreleased"


def versioni_rilasciate() -> set[str]:
    """Le versioni che il CHANGELOG dichiara rilasciate.

    È il CHANGELOG e NON `git tag`, e la differenza non è di gusto: la CI fa
    `actions/checkout` senza `fetch-tags`, quindi lassù `git tag` non stampa
    niente. Un gate ancorato ai tag sarebbe verde in locale (60 tag) e avrebbe
    bocciato TUTTE le 51 voci in CI — un presidio che si comporta in modo
    diverso dove gira davvero è peggio di nessun presidio. Il CHANGELOG è un
    file versionato: c'è in ogni checkout, anche il più superficiale.
    """
    if not CHANGELOG.is_file():
        return set()
    return set(re.findall(r"^##\s*\[?v?(\d+\.\d+\.\d+)\]?",
                          CHANGELOG.read_text(encoding="utf-8"), re.M))


def check_since(f: dict, rilasciate: set[str], errors: list[str]) -> bool:
    """`since` dichiara da quale versione la voce è nello stato che dice.

    Era l'UNICO campo del registro che nessuno controllava — e il 27/07/2026
    conteneva `v0.40.7`: una versione mai rilasciata, assente dal CHANGELOG,
    assente dai tag, diversa dal VERSION del repo. Ce l'avevo messa io poche
    ore prima, ancorando H52 alla release successiva come se fosse già uscita.
    Il gate era verde: un registro nato per rendere falsificabili i claim
    portava una provenienza infalsificabile, ed è esattamente la classe che
    H52 stessa denuncia.

    Ritorna True se la voce è dichiarata NON ancora rilasciata: `main` la conta
    e la stampa a ogni esecuzione. Non è un errore — il lavoro sta su main e
    aspetta la release — ma non deve poter marcire in silenzio: un numero
    stampato a ogni commit è un residuo che qualcuno vede.
    """
    fid, since = f.get("id", "?"), str(f.get("since") or "").strip()
    if not since:
        # `accepted` = si è deciso di non fare: non c'è una versione da cui
        # «vale», e pretenderla sarebbe chiedere una data a una non-azione.
        if f.get("status") != "accepted":
            fail(errors, f"{fid}: non dichiara da quale versione (`since`) vale il suo stato.")
        return False
    if since == SINCE_NON_RILASCIATO:
        return True
    if not rilasciate:
        # Nessuna versione leggibile: il problema è UNO (il CHANGELOG), non 51.
        # `main` lo dice una volta sola; qui non si accusa ogni voce di un difetto
        # che non ha. Una sonda che riporta 51 guasti quando ce n'è uno mente
        # sulla FORMA del problema, ed è la lezione delle otto sonde difettose.
        return False
    if since.lstrip("v") not in rilasciate:
        fail(errors,
             f"{fid}: `since: {since}` non è una versione rilasciata — il CHANGELOG\n"
             f"       non la nomina. O è un refuso, o è una release che non è mai\n"
             f"       uscita: se il lavoro è su main e aspetta il rilascio, scrivi\n"
             f"       `since: {SINCE_NON_RILASCIATO}`, che è vero e viene contato.")
    return False


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
    rilasciate = versioni_rilasciate()
    non_rilasciate: list[str] = []
    if not rilasciate:
        fail(errors,
             "CHANGELOG.md assente o senza intestazioni di versione: senza di lui\n"
             "       il campo `since` di ogni voce torna a essere prosa non verificata.\n"
             "       (Il gate NON accusa le singole voci: il difetto è uno solo, qui.)")

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

        if check_since(f, rilasciate, errors):
            non_rilasciate.append(fid)
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

    # ── ogni RESIDUO dev'essere NOMINATO in SECURITY.md, non solo contato ──
    # Il controllo qui sotto confronta quattro numeri, e quattro numeri combaciano
    # anche quando il testo racconta un'altra cosa. Misurato il 27/07: la tabella
    # diceva 10 parziali e la prosa ne descriveva 9 — H52, aggiunta quel giorno,
    # non era nominata da nessuna parte. Il gate era verde: il totale tornava.
    # Un residuo che nessuna riga nomina è un residuo che nessuno legge.
    if SECURITY_MD.is_file():
        md_ids = SECURITY_MD.read_text(encoding="utf-8")
        for f in findings:
            fid = str(f.get("id", ""))
            if f.get("status") in {"partial", "open"} and fid and not re.search(
                    rf"\b{re.escape(fid)}\b", md_ids):
                fail(errors,
                     f"{fid}: è `{f.get('status')}` ma SECURITY.md non lo NOMINA mai.\n"
                     f"       Il conteggio tornerebbe lo stesso — ed è il punto: un\n"
                     f"       residuo contato e non raccontato sparisce dalla lettura.")

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
    if non_rilasciate:
        # Stampato SEMPRE, non solo in errore: è il residuo che aspetta una
        # release. Finché ha un numero sullo schermo a ogni commit, nessuno può
        # dire di non averlo visto.
        print(f"{YEL}⧗ {len(non_rilasciate)} su main, non ancora rilasciati: "
              f"{', '.join(non_rilasciate)}{OFF}"
              f"{DIM} — l'evidenza è nel codice, la versione che la porta non è uscita.{OFF}")

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
