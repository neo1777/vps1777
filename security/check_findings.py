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
# + 1 (H64 medium, 02/08) = 64. H64 non nasce da una lettura del codice ma dalla
# lettura di un TEST: la docstring che giustifica l'indicizzazione verbatim di
# `users.json` prometteva tre protezioni di output — «mascheramento in ricerca,
# cifratura at-rest, ACL» — all'indicativo, e nessuna delle tre esisteva. Il difetto
# non era l'indicizzazione (quella è la scelta giusta e il test la argomenta bene):
# era il compenso citato, che rende invisibile il debito perché chi lo legge smette
# di cercare. Curata la prima delle tre; le altre due restano nel residuo.
# + 1 (H65 medium, 10/08) = 65. H65 non nasce da un difetto: nasce da una garanzia
# VERA e non presidiata. «Ogni action è pinnata al commit SHA» era esatta — 16 `uses:`
# su 16, misurati — e non la teneva nessun test: sarebbe diventata falsa al primo
# `uses: …@v4`, la forma che ogni README del mondo suggerisce, senza che nessun file
# cambiasse il proprio testo. ⇒ *una promessa vera non ha sintomi finché regge, e
# quando smette non ne ha comunque.* Trovata lavorando la voce `a80025f1` col suo
# metodo: per ogni frase-garanzia in prosa, il codice regge? se sì merita un id.
EXPECTED_TOTAL = 65
EXPECTED_BY_SEVERITY = {"critical": 2, "high": 10, "medium": 35, "low": 18}

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


# Nei file di CODICE una riga che comincia con `#` è un commento. Non vale per i
# `.md`, dove non c'è codice da distinguere: là un `contains` è sempre una citazione.
# 🔴 IL BUCO CHE QUESTA LISTA AVEVA (curato il 02/08): il filtro è per SUFFISSO, e
# `Path(".env.example").suffix` è `".example"` — mentre `#` è il carattere di commento
# lì dentro. ⇒ un `contains:` su `.env.example` poteva essere soddisfatto da una riga
# COMMENTATA e il presidio non se ne accorgeva: **caso vivo misurato**, H49 aveva
# `VPS1777_REQUIRE_COSIGN` che in quel file compare su una riga sola, `#…=1`.
# ⭐ E la forma del difetto è quella che abbiamo misurato sei volte quella notte: il
# presidio riconosceva i file dalla FORMA DEL NOME, e i file col nome di forma diversa
# (`.env.example`, `Dockerfile`, `Caddyfile` — che un suffisso non ce l'hanno affatto)
# restavano fuori dal perimetro senza che nessuno l'avesse deciso.
_SUFFISSI_CON_COMMENTI = {".py", ".sh", ".yml", ".yaml", ".service", ".timer", ".path",
                          ".example", ".toml", ".ini", ".cfg", ".conf", ".env"}
# I file che il commento ce l'hanno ma un suffisso NO: qui il nome è tutto il nome.
_NOMI_CON_COMMENTI = {"Dockerfile", "Caddyfile", "Makefile", ".env", ".gitignore",
                      ".dockerignore", "requirements.txt"}


def _ha_commenti_hash(path: Path) -> bool:
    """`#` è il commento in questo file? Guarda il suffisso E il nome intero."""
    return path.suffix in _SUFFISSI_CON_COMMENTI or path.name in _NOMI_CON_COMMENTI


def solo_in_commenti(path: Path, needle: str) -> bool:
    """L'ago compare SOLTANTO su righe di commento?

    Nasce il 27/07 da un rilievo di abdd732a: un `contains` su un identificatore è
    soddisfatto anche se quell'identificatore vive solo in un commento — cioè il
    presidio può essere verde mentre il CODICE che dovrebbe presidiare non c'è più.
    Misurato su questo registro: 5 aghi su 56 voci stanno solo nei commenti.

    ⚠️ NON sono tutti difetti, ed è il punto: alcuni sono RICEVUTE deliberate — un
    commento che spiega perché una cosa è fatta così, e che non deve poter sparire in
    silenzio. Il difetto non è che esistano: è che il registro non distingueva una
    RICEVUTA da un PRESIDIO, e chi legge non poteva sapere quale delle due stesse
    guardando. Ora le ricevute si dichiarano (`ricevute:`) e un ago di `contains:` che
    finisce solo nei commenti fa fallire il gate.
    """
    if not _ha_commenti_hash(path):
        return False
    righe = [r for r in path.read_text(encoding="utf-8", errors="replace").splitlines()
             if needle in r]
    return bool(righe) and all(r.lstrip().startswith("#") for r in righe)


# ── la misura supera la sorgente (round-8) ───────────────────────────────────
# Rilievo dell'analisi esterna del round-8, e il suo contributo migliore:
#   «per dichiarare chiuso un elemento, il documento dovrebbe richiedere
#    obbligatoriamente l'inclusione dell'output testuale e dell'exit code dello
#    script. Quella diventa la condizione primaria per il PASS. L'esistenza della
#    funzione nel file Python verrebbe relegata a evidenza secondaria.»
#
# ⚠️ NON applicato come l'ha detto lui. La sua regola era «obbligatorio per tutte
# le voci oltre la H50»: un perimetro fissato su un NUMERO, che invecchia alla
# voce successiva — la prima voce nuova che parla di documentazione verrebbe
# accusata di non avere una prova sul vivo che non può avere. È la forma del
# `NoNewPrivileges` del round-7: giusta come principio, distruttiva come regola.
# (La somiglianza l'ha vista 71d540e6; che oggi non morda l'ho misurato io —
#  6 voci oltre H50, ZERO `closed`, e per tutte una prova sul vivo è possibile.)
#
# ⇒ Il perimetro è la NATURA DELL'OGGETTO, e si DICHIARA invece di indovinarla:
#     comportamento  ciò che il sistema FA. `closed` ⇒ serve una prova eseguita.
#     documento      ciò che il progetto DICE (H44). Si verifica leggendo, ed è giusto così.
#     decisione      ciò che si è scelto di non fare (H28). Non si esegue niente.
# Una regola basata sulla natura non invecchia alla voce successiva; una basata
# sul numero sì.
NATURE = {"comportamento", "documento", "decisione"}


def check_resta_aperto(f: dict, errors: list[str]) -> None:
    """Una voce `partial` deve dire, in una riga, COSA RESTA APERTO OGGI.

    IL CASO CHE L'HA GENERATA (27/07/2026, round-9, rilievo di 71d540e6): una voce
    `partial` racconta il difetto per esteso e il rimedio lo seppellisce in fondo al
    `missing:`. Chi legge — un umano di fretta o un'analisi esterna — prende la voce
    per una DENUNCIA ATTUALE.

    ⭐ E il costo l'abbiamo pagato lo stesso giorno, due volte:
      · l'audio del round-9 ha chiuso il suo intervento profetizzando che «un giorno il
        backup peserà 4 GB e la soglia fissa di 5 GB saturerà il disco» — ma alla
        versione d'arrivo quella soglia era GIÀ calcolata. Ha letto il difetto di H58 e
        non il suo rimedio, e ci ha costruito sopra la sua ultima parola.
      · e prima ancora due di noi hanno classificato la stessa riga in modo opposto —
        VERA e FALSA — e per scioglierla è servito aprire il codice.

    🔑 `missing:` racconta la STORIA (com'era, cosa si è fatto, cosa si è scartato e
    perché); `resta_aperto:` dice lo STATO (cosa non è fatto ADESSO). Sono due domande
    diverse, e finché convivevano nello stesso paragrafo vinceva sempre la prima —
    perché è più lunga e viene prima.

    ⚠️ LIMITE DICHIARATO: risolve il caso `partial`. Una voce `closed` il cui titolo
    nomina un sottoinsieme resta illeggibile allo stesso modo — è la forma di H42 e H56,
    e questa regola non la tocca.
    """
    if f.get("status") != "partial":
        return
    riga = (f.get("resta_aperto") or "").strip()
    if not riga:
        fail(errors,
             f"{f.get('id', '?')}: è `partial` ma non dice COSA RESTA APERTO.\n"
             f"       `missing:` racconta la storia; serve una riga `resta_aperto:` che\n"
             f"       dica lo STATO DI OGGI. Senza, chi legge prende il difetto\n"
             f"       raccontato per esteso e lo crede ancora vivo — è successo il 27/07\n"
             f"       a un'analisi esterna E a due di noi, sulla stessa voce.")
        return
    if len(riga) > 400:
        fail(errors,
             f"{f.get('id', '?')}: `resta_aperto` è lungo {len(riga)} caratteri.\n"
             f"       Deve stare in una riga o due: se serve un paragrafo, quello che\n"
             f"       hai scritto è un altro `missing:` e il problema torna identico.")


def check_natura_e_prova(f: dict, errors: list[str], senza_natura: list[str]) -> None:
    """Una voce `closed` di natura `comportamento` deve portare una PROVA ESEGUITA.

    `prova:` è un blocco con `comando`, `output` (anche solo l'ultima riga che conta),
    `exit` e `quando`. Non sostituisce le `evidence`: le SOPRAVANZA. Il file e la riga
    restano — dicono dov'è il codice; la prova dice che quel codice fa la cosa.

    Il campo `natura` non è ancora su tutte le voci: chi non ce l'ha viene CONTATO e
    stampato, non accusato. Un residuo con un numero sullo schermo a ogni giro è
    diverso da un residuo taciuto — ed è lo stesso patto del contatore ⧗.
    """
    fid, natura = f.get("id", "?"), f.get("natura")
    if natura is None:
        senza_natura.append(fid)
        return
    if natura not in NATURE:
        fail(errors, f"{fid}: `natura: {natura}` non è valida (attese: {sorted(NATURE)})")
        return
    if natura != "comportamento" or f.get("status") != "closed":
        return
    prove = f.get("prova") or []
    if not prove:
        fail(errors,
             f"{fid}: è `closed` ed è di natura COMPORTAMENTO, ma non porta nessuna\n"
             f"       `prova:` eseguita. Un file e una riga dicono dov'è il codice, non\n"
             f"       che faccia la cosa: serve comando + output + exit code.\n"
             f"       (Se invece parla di ciò che il progetto DICE, la natura è `documento`.)")
        return
    for p in prove:
        mancanti = [k for k in ("comando", "output", "exit", "quando") if p.get(k) in (None, "")]
        if mancanti:
            fail(errors,
                 f"{fid}: una `prova:` è incompleta — mancano {mancanti}.\n"
                 f"       Un output senza il comando non è ripetibile; un comando senza\n"
                 f"       l'exit code non dice com'è finito; nessuno dei due senza la data\n"
                 f"       dice a QUANDO si riferisce.")


# ── l'EPOCA DI SCOPERTA (round-8) ─────────────────────────────────────────────
# Secondo rilievo dell'analisi esterna: «includere scoperte empiriche successive nel
# bilancio di una revisione passata altera la percezione della qualità del codice
# originale … il denominatore per valutare l'efficacia del ciclo precedente deve
# rimanere fisso». Lui lo inquadra come GIUSTIZIA verso la revisione passata.
#
# ⚠️ Il nostro problema è più grande del suo, e la differenza vale: il registro non sa
# QUANDO una voce è diventata conoscibile. Senza quel dato, «stiamo migliorando?» non è
# falsificabile — il denominatore si muove sotto la domanda, e ogni round sembra andare
# meglio o peggio a seconda di quante voci sono nate nel frattempo.
#
# `since` dice DA QUALE VERSIONE la voce è nello stato che dichiara.
# `scoperta` dice QUANDO e COME l'abbiamo saputa. Sono due assi diversi — origine e
# impatto — e confonderli è il difetto che H51 racconta su un altro piano.
COME_SCOPERTA = {
    "lettura",        # qualcuno ha letto il codice o un documento
    "misura",         # qualcuno ha eseguito qualcosa e guardato il risultato
    "incidente",      # si è rotto in produzione e l'abbiamo capito riparando
    "audio-esterno",  # l'ha nominata l'analisi esterna di un round
}


def check_documento_non_solo_assenza(f: dict, errors: list[str]) -> None:
    """Una voce di natura `documento` non si chiude con la sola ASSENZA di una stringa.

    ⇒ È la regola che `H52` teneva in sospeso. Il suo `resta_aperto` diceva: *«non è
    applicata: così com'è accuserebbe tre voci sane. Serve prima un modo di dichiarare
    l'oggetto della voce»*.
    🔑 **Quel modo è arrivato**: il campo `natura`, introdotto con `H62`/`H63` il 27-28/07.
    Misurato il 01/08 prima di scrivere questa funzione:
        · voci che si chiudono con SOLO `not_contains`  →  UNA (H48)
        · e H48 NON è un documento: è `compose.yaml`, dove l'assenza di `ports:`
          **È** il comportamento, perché è il file che docker legge.
        · le tre voci `natura: documento` (H44, H54, H62) hanno tutte un `contains`.
    ⇒ **la regola oggi non accusa nessuno**, e il blocco dichiarato in `H52` è
      invecchiato: valeva quando `natura` non c'era e la regola avrebbe dovuto
      applicarsi a tutte le voci indistintamente.

    PERCHÉ SOLO SUI DOCUMENTI. Per una configurazione l'assenza di una riga è la
    proprietà stessa (H48). Per un DOCUMENTO no: «il testo X non c'è» non dimostra
    che il documento dica la cosa giusta — potrebbe dirla altrove, in altra forma, o
    non dirla affatto. *Un `not_contains` da solo prova che una frase è sparita, non
    che la verità sia scritta.*

    ⚠️ E non chiude `H52`, che è più largo (certificare per stringa un COMPORTAMENTO).
    Chiude il pezzo che `H52` dichiarava bloccato — e lo dice invece di lasciar credere
    che il rilievo sia risolto.
    """
    if f.get("natura") != "documento" or f.get("status") != "closed":
        return
    ev = f.get("evidence") or []
    if not ev:
        return
    chiavi: set[str] = set()
    for e in ev:
        chiavi |= set(e.keys()) - {"file"}
    if chiavi == {"not_contains"}:
        errors.append(
            f"  {f.get('id')}: è una voce `natura: documento` chiusa con la sola ASSENZA "
            f"di una stringa.\n"
            f"       «quel testo non c'è» prova che una frase è sparita, non che il "
            f"documento dica la cosa giusta.\n"
            f"       Aggiungi un `contains` con la frase che DEVE esserci, o una `prova` "
            f"di lettura.")


def check_scoperta(f: dict, errors: list[str], senza: list[str]) -> None:
    """`scoperta: {quando, come}` — quando l'abbiamo saputa e per quale strada.

    Contata e non pretesa, come `natura`: dichiararla su 56 voci è archeologia, e
    inventare una data è peggio che non averla. Il numero resta sullo schermo.
    """
    sc = f.get("scoperta")
    if sc is None:
        senza.append(f.get("id", "?"))
        return
    fid = f.get("id", "?")
    if not sc.get("quando"):
        fail(errors, f"{fid}: `scoperta` senza `quando` — una scoperta senza data non\n"
                     f"       si può collocare in nessun bilancio.")
    come = sc.get("come")
    if come not in COME_SCOPERTA:
        fail(errors, f"{fid}: `scoperta.come: {come}` non è valido (attesi: {sorted(COME_SCOPERTA)}).")


# ── il rilievo che viene da FUORI si giudica su TRE assi (round-8) ────────────
# Terzo rilievo dell'analisi esterna: «introdurre una matrice a due colonne per ogni
# voce: la A valida il perimetro del difetto, la B valuta separatamente la soluzione.
# Questo impedirebbe che una cura tossica invalidi una diagnosi corretta.»
#
# È vero, ed è costato caro: al round-7 la riga più pericolosa aveva DIFETTO VERO e
# RIMEDIO che avrebbe rotto la build per sempre (NoNewPrivileges su una unit che usa
# sudo). Chi avesse risposto a una domanda sola l'avrebbe implementata.
#
# ⚠️ Le colonne però sono TRE, non due, e la terza l'abbiamo pagata allo stesso round:
#   difetto        ciò che l'audit DICE che è rotto — è vero?
#   rimedio        ciò che propone — è giusto?
#   inquadramento  il difetto che c'è DAVVERO è lo stesso che descrive?
# Al round-7 un rilievo sul rollback era «vero a metà», e il difetto reale era un altro:
# l'abbiamo trovato per conto nostro dopo, non grazie al metro. Un metro a due domande
# fa passare l'INQUADRAMENTO dell'audit senza esaminarlo.
# Voci nate da un'analisi esterna che NON portano i tre verdetti: sorvegliate e
# stampate a ogni giro (vedi `check_rilievo_esterno`). Lista e non contatore: un
# numero senza i nomi non si può spuntare, e queste vanno chiuse una per una.
SORVEGLIATE: list[str] = []

VERDETTI = {
    "difetto": {"vero", "vero-a-meta", "falso", "non-decidibile"},
    "rimedio": {"giusto", "costoso", "sbagliato", "assente"},
    "inquadramento": {"stesso", "diverso", "piu-stretto", "piu-largo"},
}


def check_rilievo_esterno(f: dict, errors: list[str]) -> None:
    """Una voce nata da un'analisi esterna porta i TRE verdetti, o nessuno.

    Non è pignoleria di schema: registrare «il difetto è vero» e agire è esattamente
    come il round-7 ha quasi rotto la build. I tre campi obbligano a scrivere le tre
    risposte — e a scoprire, scrivendole, quando divergono.
    """
    r = f.get("rilievo_esterno")
    fid = f.get("id", "?")
    if r is None:
        # 🔴 IL BUCO (02/08, da un rilievo di un agent, verificato sul registro).
        #   Questa regola si applicava SOLO a chi si autodenuncia: bastava non scrivere
        #   il campo — che è FACOLTATIVO — per non essere guardati. E chi non lo scrive
        #   era indistinguibile da chi non ne ha bisogno.
        # 📏 MISURATO adesso su `findings.yml`: le voci con `scoperta.come:
        #   audio-esterno` sono 5 (H48, H49, H52, H54, H62); quelle con
        #   `rilievo_esterno` sono 2 (H52, H54). ⇒ **H48, H49 e H62 sono nate da
        #   un'analisi esterna, sono tutte e tre `closed`, e non passano da nessuno
        #   dei tre verdetti** — e il gate usciva 0 stampando «ogni voce chiusa ha la
        #   sua evidenza».
        # ⭐ Il dato per accorgersene era DENTRO il registro (`scoperta.come`): non
        #   mancava l'informazione, mancava chi la incrociasse.
        # ⚠️ SORVEGLIANZA, NON CANCELLO — e dichiaro perché, perché il pattern
        #   «segnalato, non fatale» è esattamente quello che stanotte abbiamo trovato
        #   essere un verde-per-costruzione: i tre verdetti sono un GIUDIZIO su un
        #   rilievo altrui, non un campo da riempire, e non posso inventarli né farli
        #   inventare da chi passa di qui col gate rosso. Le due differenze che lo
        #   rendono un presidio e non un alibi: **compare nell'OUTPUT a ogni giro** (non
        #   tace) e **ha un criterio di uscita scritto** — quando le tre voci hanno i
        #   loro verdetti, questo blocco diventa `fail()` e la regola vale per tutte.
        if (f.get("scoperta") or {}).get("come") == "audio-esterno":
            SORVEGLIATE.append(
                f"{fid} ({f.get('status', '?')}): nata da un'analisi esterna "
                f"(`scoperta.come: audio-esterno`) e SENZA `rilievo_esterno` ⇒ i tre "
                f"verdetti non sono mai stati dati."
            )
        return
    if not r.get("fonte"):
        fail(errors, f"{fid}: `rilievo_esterno` senza `fonte` — un rilievo di cui non si\n"
                     f"       sa da dove viene non si può nemmeno rimandare indietro.")
    for campo, ammessi in VERDETTI.items():
        v = r.get(campo)
        if v is None:
            fail(errors,
                 f"{fid}: `rilievo_esterno` senza `{campo}`. I tre verdetti si danno\n"
                 f"       INSIEME o non si dà nessuno: al round-7 «il difetto è vero» da\n"
                 f"       solo avrebbe fatto implementare un rimedio che rompeva la build.")
        elif v not in ammessi:
            fail(errors, f"{fid}: `{campo}: {v}` non è valido (attesi: {sorted(ammessi)}).")


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
            elif solo_in_commenti(path, needle):
                fail(errors,
                     f"{fid}: PRESIDIO NEI COMMENTI — «{needle}» in {ev['file']} compare\n"
                     f"       SOLO su righe di commento. Il gate resterebbe verde anche se\n"
                     f"       sparisse il codice: sta guardando la spiegazione, non la cosa.\n"
                     f"       Se è deliberato — una RICEVUTA, cioè un commento che non deve\n"
                     f"       sparire in silenzio — spostalo sotto `ricevute:` invece di\n"
                     f"       `contains:`, così si legge cosa promette.")
        # Le RICEVUTE: aghi che DEVONO stare in un commento. Si verificano come i
        # `contains` (devono esserci ancora), ma dichiarano di provare che una
        # ragione è ancora scritta — non che un comportamento esista.
        for needle in ev.get("ricevute") or []:
            if needle not in text:
                fail(errors,
                     f"{fid}: RICEVUTA SPARITA — «{needle}» non è più in {ev['file']}.\n"
                     f"       Era la ragione scritta di una scelta: se la scelta è cambiata\n"
                     f"       la voce va riletta, se è solo il commento a essere sparito\n"
                     f"       qualcuno ha tolto il perché senza toccare il cosa.")
        for needle in ev.get("not_contains") or []:
            if needle in text:
                fail(errors,
                     f"{fid}: REGRESSIONE — «{needle}» è RITORNATO in {ev['file']}.\n"
                     f"       Il fix dichiarava che non ci fosse.")


def rapporto_epoca(findings: list[dict], data: str) -> int:
    """`--epoca AAAA-MM-GG` — quante voci erano NOTE a quella data, e per quale strada.

    È lo strumento che rende falsificabile «stiamo migliorando?»: senza, il
    denominatore si muove sotto la domanda. Nasce dal round-8, che l'ha chiesto come
    giustizia verso una revisione passata; qui serve a una cosa più larga — poter dire
    «a questa data ne conoscevamo N» senza ricostruirlo a memoria.

    ⚠️ Dichiara sempre quante voci NON hanno la data: un conteggio che tace ciò che non
    sa è la cosa che questo registro esiste per non fare.
    """
    note, ignote, per_strada = [], [], {}
    for f in findings:
        sc = f.get("scoperta") or {}
        quando = str(sc.get("quando") or "")
        if not quando:
            ignote.append(f.get("id"))
            continue
        if quando <= data:
            note.append(f.get("id"))
            per_strada[sc.get("come", "?")] = per_strada.get(sc.get("come", "?"), 0) + 1
    print(f"{DIM}al {data}: {len(note)} voci NOTE su {len(findings)} nel registro di oggi{OFF}")
    for strada, n in sorted(per_strada.items(), key=lambda x: -x[1]):
        print(f"  {strada:14} {n}")
    if ignote:
        print(f"{YEL}⚠️  {len(ignote)} voci senza data di scoperta: NON sono nel conteggio.{OFF}")
        print(f"{DIM}    Il numero sopra è un minimo garantito, non il totale.{OFF}")
    return 0


def main() -> int:
    if "--epoca" in sys.argv:
        i = sys.argv.index("--epoca")
        if i + 1 >= len(sys.argv):
            print("uso: check_findings.py --epoca AAAA-MM-GG")
            return 2
        data = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
        return rapporto_epoca(data.get("findings") or [], sys.argv[i + 1])

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
    senza_natura: list[str] = []
    senza_scoperta: list[str] = []
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
        check_resta_aperto(f, errors)
        check_natura_e_prova(f, errors, senza_natura)
        check_documento_non_solo_assenza(f, errors)
        check_scoperta(f, errors, senza_scoperta)
        check_rilievo_esterno(f, errors)
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

    # ── …e ANCHE il conteggio in PROSA, non solo quello della tabella ──
    #
    # 🔴 PERCHÉ (abdd732a, 01/08). Il blocco qui sopra copre la TABELLA dei residui
    #   (chiusi/parziali/accettati/aperti), e SECURITY.md dichiara due righe più su:
    #   «Questo conteggio è verificato dalla CI … fallisce se i numeri qui sotto non
    #   combaciano col registro». Chi legge capisce «tutti i numeri di questa sezione».
    #   Erano quattro su otto. MISURATO quel giorno, col gate VERDE (exit 0):
    #     SECURITY.md  «Il registro conta 56 voci (2 critiche, 9 alte, 31 medie, 14 basse)»
    #     registro      63 voci (2 critiche, 10 alte, 33 medie, 18 basse)
    #     e la scomposizione in prosa sommava a 54, non ai 56 che dichiarava.
    # ⭐ LA FORMA, ed è quella che questo file esiste per impedire: *un check verde su
    #   una condizione PARZIALE è peggio di nessun check, perché sposta la fiducia su un
    #   perimetro più stretto di quello che sembra coprire.* La sezione dichiara di non
    #   poter più marcire in silenzio — e stava marcendo nella metà non coperta.
    if SECURITY_MD.is_file():
        md = SECURITY_MD.read_text(encoding="utf-8")
        sev_reali = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for f in findings:
            s = str(f.get("severity", ""))
            if s in sev_reali:
                sev_reali[s] += 1
        m = re.search(
            r"Il registro conta \*\*(\d+) voci\*\*\s*\(\s*(\d+)\s+critiche?,\s*"
            r"(\d+)\s+alte?,\s*(\d+)\s+medie?,\s*(\d+)\s+basse?\s*\)", md)
        if not m:
            fail(errors,
                 "SECURITY.md: non trovo la frase «Il registro conta **N voci** (A critiche, "
                 "B alte, C medie, D basse)».\n"
                 "       Se l'hai riscritta, aggiorna anche questo controllo: un gate che non\n"
                 "       trova più il suo bersaglio TACE, e il silenzio qui somiglia a un ok.")
        else:
            dich = {"totale": int(m.group(1)), "critical": int(m.group(2)),
                    "high": int(m.group(3)), "medium": int(m.group(4)), "low": int(m.group(5))}
            reali = dict(sev_reali, totale=total)
            for k in ("totale", "critical", "high", "medium", "low"):
                if dich[k] != reali[k]:
                    fail(errors,
                         f"SECURITY.md (prosa) dichiara {dich[k]} «{k}», il registro ne conta "
                         f"{reali[k]}.\n"
                         f"       Allinea il documento, non il registro.")
            somma = dich["critical"] + dich["high"] + dich["medium"] + dich["low"]
            if somma != dich["totale"]:
                fail(errors,
                     f"SECURITY.md (prosa): le severità dichiarate sommano a {somma}, ma il "
                     f"totale dichiarato è {dich['totale']}.\n"
                     f"       Il documento non torna con SE STESSO, prima ancora che col registro.")

    # ── esito ──
    print(f"{DIM}registro: {total} rilievi · "
          f"{GRN}{counts['closed']} chiusi{OFF}{DIM} · "
          f"{YEL}{counts['partial']} parziali{OFF}{DIM} · "
          f"{DIM}{counts['accepted']} accettati · "
          f"{RED}{counts['open']} aperti{OFF}")
    if senza_natura:
        # Contato e stampato, non accusato: la classificazione delle 56 voci è un
        # lavoro di giudizio e non si fa di corsa. Il numero scende a ogni voce
        # dichiarata, e finché è sullo schermo nessuno può dire di non averlo visto.
        print(f"{YEL}◍ {len(senza_natura)} voci senza `natura` dichiarata{OFF}"
              f"{DIM} — per loro la regola «un difetto di comportamento si chiude con una "
              f"prova eseguita» non può ancora valere.{OFF}")
    if senza_scoperta:
        print(f"{YEL}◍ {len(senza_scoperta)} voci senza `scoperta` (quando e come l'abbiamo saputa){OFF}"
              f"{DIM} — finché sono tante, «stiamo migliorando?» non è una domanda falsificabile.{OFF}")
    if SORVEGLIATE:
        # Stessa disciplina delle due qui sopra: contato, NOMINATO e stampato — non
        # accusato. I tre verdetti sono un giudizio su un rilievo altrui, non un campo
        # da riempire di corsa; ma finché i nomi sono sullo schermo a ogni giro,
        # nessuno può dire di non averli visti — ed è l'unica differenza fra una
        # sorveglianza e un verde-per-costruzione.
        print(f"{YEL}◍ {len(SORVEGLIATE)} voci da analisi esterna SENZA i tre verdetti{OFF}"
              f"{DIM} — la regola `rilievo_esterno` si applicava solo a chi si autodenuncia:{OFF}")
        for r in SORVEGLIATE:
            print(f"  {YEL}·{OFF} {r}")
        print(f"{DIM}    Quando queste hanno i loro verdetti, il ramo in "
              f"`check_rilievo_esterno` diventa un `fail()` e la regola vale per tutte.{OFF}")
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
        # ⚠️ QUI C'ERA, IDENTICA, la riga «Nessun claim senza coordinata. Nessun
        # residuo taciuto.» — al presente indicativo, dentro il ramo in cui è
        # FALSA, e in fondo: l'ultima cosa che resta sullo schermo di una run
        # rossa era l'affermazione della proprietà appena fallita. Misurato il
        # 27/07 eseguendo il checker su un registro rotto: dieci righe di errore
        # e poi, in chiusura, la rassicurazione.
        # 🔑 La frase non era sbagliata: era nel MODO sbagliato. Vale come
        # REGOLA («ecco cosa questo registro deve reggere»), non come RESOCONTO
        # («ecco cosa regge»), e nel ramo rosso si leggeva come il secondo.
        # È la stessa classe del `|| true` in CI, presa dall'altro capo: là un
        # gate che non poteva dire di no, qui un gate che dice di no e poi si
        # smentisce da solo nella riga dopo.
        print(f"\n{DIM}La regola che questo registro deve reggere: nessun claim "
              f"senza coordinata, nessun residuo taciuto. Sopra c'è dove non regge.{OFF}")
        return 1

    print(f"{GRN}✓ ogni voce chiusa ha la sua evidenza, e l'evidenza c'è ancora.{OFF}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
