#!/usr/bin/env python3
"""doc-riferimenti.py — i file che i doc NOMINANO esistono ancora?

Gira in CI. Non è un daemon, non tocca la produzione, non scrive niente.

PERCHÉ (b82df434, 15/08): un documento che cita `tools/qualcosa.sh` dopo una rinomina
non fallisce — resta lì e manda il lettore a cercare un file che non c'è. È la stessa
classe che questo repo cura altrove (dichiarato ≠ reale), sul versante dei doc: nessuno
la vede perché **un documento non si esegue**. Il ledger delle feature copre il codice;
questo copre le PAROLE che lo descrivono.

COSA CONTA COME RIFERIMENTO: un path fra backtick con un'estensione nota. Non i link
markdown, non le URL, non i nomi nudi senza estensione — sono ambigui e produrrebbero
rumore, e un presidio che parla quando non serve viene spento.

⚠️ E COSA QUESTO CONTROLLO **NON** DICE, perché la prima misura è stata sbagliata:
la sonda ingenua dava **79 path inesistenti su 403** in un repo curato. Il numero non
tornava, e infatti erano quattro insiemi diversi mescolati:

  · path ASSOLUTI (`/var/lib/...`)      → stato sulla VPS, non file del repo
  · file di RUNTIME (`state.json`, …)   → li CREA il sistema: citarli è corretto
  · path IMPRECISI (`admin.py`)         → il file esiste, il path scritto no
  · CITAZIONI e TEMPLATE               → `0001-<slug>/run.py` è un contratto da
                                          riempire, non un file mancante

Solo l'ultimo scarto è un difetto, e va giudicato leggendo il contesto. ⇒ qui i primi
tre sono classificati e mostrati SEPARATI, non sommati: *un totale che mescola insiemi
diversi non è impreciso, è di un altro oggetto.*

Il CHANGELOG e i piani sono esclusi per costruzione: parlano del PASSATO per mestiere,
e un file che non c'è più è esattamente ciò che devono poter nominare.

USO
    python3 tools/doc-riferimenti.py              # referto; exit 1 se ci sono introvabili
    python3 tools/doc-riferimenti.py --autoprova  # verifica che la sonda sappia dire di SÌ
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

RIF = re.compile(r"`([A-Za-z0-9_./-]+\.(?:sh|py|yml|yaml|md|json|conf|service|env|toml))`")

# File che il sistema CREA a esecuzione: nominarli in un doc è corretto, cercarli no.
RUNTIME = re.compile(
    r"(auth|cookies|metadata|pending|state|status|result|users|progress|conversations"
    r"|migration|manifest)s?(_\w+)?\.json$|^var/|^onboarding/|^state/|\.service$"
)

# I doc che parlano del passato: un file sparito è ciò che DEVONO poter nominare.
STORICI = ("CHANGELOG", "SELF_UPDATE_PLAN", "BRIEF")

# 🖐️ Le eccezioni si dichiarano CON LA RAGIONE, non si nascondono: se una diventa un
#    file vero, la riga qui resta a dire perché era esclusa — e si può togliere.
ATTESI = {
    "02-LOOP-SU-CODICE.md": "citazione di un corpus esterno al repo (lezione C9)",
    "aperti.sh": "strumento del tavolo 1777, vive in un altro repo",
    "run.py": "TEMPLATE del contratto migrazioni: 0001-<slug>/run.py va creato, non esiste",
    "golden-voice-2026-08-27.json": "il golden-set del campione cieco (COLLAUDO-VERGINE, "
        "fase 4): DELIBERATAMENTE fuori dal repo — porta i giudizi su messaggi "
        "privati; vive nel volume archive della macchina e nel backup dell'owner",
    "plugins/mio-mcp/compose.mio-mcp.yaml": "esempio didattico: è il file che il lettore CREA",
    # 16/08 — i doc di `docs/roadmap/` parlano di cose FUORI da questo repo, ed è il loro
    # mestiere: sono prompt di onboarding e cataloghi, non documentazione del prodotto.
    # Il gate li segnava introvabili e aveva ragione ALLA LETTERA (nel repo non ci sono) e
    # torto nella sostanza: non sono riferimenti rotti, sono citazioni di altri progetti.
    # ⭐ La distinzione che al gate manca: «il file non c'è QUI» ≠ «il file non c'è».
    #    Non correggo la prosa per far tornare un numero — dichiaro l'eccezione, che è
    #    quello che il gate stesso chiede di fare, e la ragione resta scritta accanto.
    "CLAUDE.md": "memoria di sessione (~/.claude), citata come CONCETTO in skill-sopra-archivio: non è un link a un file del repo",
    "MEMORY.md": "idem CLAUDE.md — le due sono nominate insieme nella stessa frase sul fact-checking dei ricordi",
    "ARCHITETTURA.md": "documento di ~/Scrivania/argus1777/, altro progetto, dichiarato come «Fonte» in prompt-c3-argus1777",
    "SICUREZZA.md": "idem: docs/ di argus1777, non di vps1777 (che ha SECURITY.md, in inglese)",
    "CONFINE_DEPLOY_vps1777.md": "idem: docs/ di argus1777 — il nome cita vps1777 ma il file vive là",
    "baseline_memoria_isolata.md": "artefatto di ricerca citato in skill-sopra-archivio, mai stato nel repo",
}


def _git(*args: str) -> list[str]:
    out = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    return out.stdout.split()


def analizza(iniettato: tuple[str, str] | None = None):
    tracciati = set(_git("ls-files"))
    per_nome: dict[str, list[str]] = {}
    for f in tracciati:
        per_nome.setdefault(os.path.basename(f), []).append(f)

    vivi = [f for f in sorted(tracciati) if f.endswith(".md") and not any(s in f for s in STORICI)]
    conteggi = {"esatti": 0, "assoluti": 0, "runtime": 0, "imprecisi": 0}
    imprecisi: dict[str, set[str]] = {}
    introvabili: dict[str, set[str]] = {}

    for f in vivi:
        try:
            testo = open(f, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        if iniettato and iniettato[0] == f:
            testo += iniettato[1]
        for m in RIF.finditer(testo):
            p = m.group(1)
            if p.startswith("/"):
                conteggi["assoluti"] += 1
            elif RUNTIME.search(p):
                conteggi["runtime"] += 1
            elif p in tracciati or os.path.join(os.path.dirname(f), p) in tracciati:
                conteggi["esatti"] += 1
            elif os.path.basename(p) in per_nome:
                conteggi["imprecisi"] += 1
                imprecisi.setdefault(p, set()).add(f)
            elif p not in ATTESI:
                introvabili.setdefault(p, set()).add(f)
    return conteggi, imprecisi, introvabili, len(vivi)


def autoprova() -> int:
    """La sonda saprebbe dire di SÌ? Un controllo che non può fallire non misura, afferma."""
    bersaglio = next((f for f in sorted(set(_git("ls-files"))) if f.startswith("docs/")), None)
    if not bersaglio:
        print("autoprova: nessun doc su cui iniettare — non posso provarmi.")
        return 2
    finto = "\nVedi `tools/questo-file-non-esiste-1777.sh`.\n"
    _, _, introvabili, _ = analizza(iniettato=(bersaglio, finto))
    preso = "tools/questo-file-non-esiste-1777.sh" in introvabili
    _, _, puliti, _ = analizza()
    print(f"  ① riferimento finto iniettato in {bersaglio} → {'PRESO ✓' if preso else 'NON PRESO ✗'}")
    print(f"  ② senza iniezione → {len(puliti)} introvabili {'✓' if not puliti else ''}")
    if preso and not puliti:
        print("  autoprova OK: la sonda sa dire di sì, e sul repo vero tace.")
        return 0
    print("  autoprova FALLITA.")
    return 1


def main() -> int:
    if "--autoprova" in sys.argv:
        return autoprova()
    conteggi, imprecisi, introvabili, n_doc = analizza()
    tot = sum(conteggi.values()) + len(introvabili)
    # 🔴 IL PERIMETRO SI DICHIARA (rilievo di 71d540e6 sul gemello di questo strumento,
    #   15/08: «garanzie-senza-coordinata.py guarda 4 file su 76 e non lo dice»).
    #   Girato addosso a me, il verdetto è DOPPIO e le due metà vanno tenute separate:
    #   · COPERTURA: regge. Il perimetro è DERIVATO (`git ls-files`), non una lista a
    #     mano — i 44 .md che stanno sul disco e non qui sono `.venv/` e `.pytest_cache/`,
    #     cioè dipendenze altrui: escluderli è corretto, e nessuno deve ricordarsene.
    #   · TRASPARENZA: no. Stampavo «32 documenti vivi» e chi legge non poteva sapere
    #     né su quanti su quanti, né che 3 sono esclusi apposta.
    # ⭐ Un perimetro giusto e taciuto dà lo stesso identico output di un perimetro
    #   sbagliato e taciuto: la differenza la vede solo chi apre il sorgente.
    esclusi = [f for f in _git("ls-files", "*.md") if any(s in f for s in STORICI)]
    print(f"doc-riferimenti — {n_doc} documenti vivi, {tot} riferimenti fra backtick")
    print(f"  perimetro: i .md TRACCIATI ({n_doc + len(esclusi)}), meno {len(esclusi)} storici"
          f" — {' · '.join(esclusi)}")
    print("             (parlano del passato: un file sparito è ciò che devono nominare)")
    print(f"  esistono a quel path        {conteggi['esatti']:4d}")
    print(f"  path assoluti (runtime VPS) {conteggi['assoluti']:4d}   non giudicabili da qui")
    print(f"  file creati a esecuzione    {conteggi['runtime']:4d}   citarli è corretto")
    print(f"  path IMPRECISI              {conteggi['imprecisi']:4d}   il file esiste, il path no")
    print(f"  INTROVABILI                 {len(introvabili):4d}   ← solo questi fanno fallire")
    if imprecisi:
        print("\n  imprecisi (non bloccano: il lettore il file lo trova comunque):")
        for p, fs in sorted(imprecisi.items())[:10]:
            print(f"    {p:44s} ← {', '.join(sorted(fs))[:50]}")
        if len(imprecisi) > 10:
            print(f"    … e altri {len(imprecisi)-10}")
        # 🖐️ QUESTA LISTA NON È UNA LISTA DI COSE DA CORREGGERE, ed è la ragione per cui
        #   non blocca. Guardati uno per uno i 20 di oggi, sono tutti usi IDIOMATICI e
        #   giusti: «Dopo `./deploy.sh`» è un COMANDO da lanciare, non un path; «controllo
        #   in `admin.py`» nomina il file in una frase, e `services/gateway/app/admin.py`
        #   lì dentro appesantisce senza aggiungere nulla a chi legge.
        # ⭐ Sostituirli in blocco farebbe tornare un numero PEGGIORANDO la prosa — cioè
        #   curare il misuratore invece dell'oggetto. Vale la pena toccarne uno solo quando
        #   il basename è ambiguo (`server.py`, `settings.py`: più candidati nel repo) e
        #   il lettore non può sapere quale sia.
        print("    ↑ informativi: quasi sempre sono usi idiomatici corretti (`./deploy.sh`")
        print("      è un comando). Correggerli in blocco peggiora la prosa per far tornare")
        print("      un numero — vale solo dove il nome è AMBIGUO nel repo.")
    if introvabili:
        print("\n  🔴 INTROVABILI — il doc manda a cercare un file che non c'è:")
        for p, fs in sorted(introvabili.items()):
            print(f"    {p:44s} ← {', '.join(sorted(fs))}")
        print("\n  Se è una citazione esterna o un template, dichiaralo in ATTESI con la ragione.")
        return 1
    print("\n  ✅ nessun riferimento introvabile.")
    print("     (le eccezioni dichiarate in ATTESI sono " + str(len(ATTESI)) + ", ognuna con la sua ragione)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
