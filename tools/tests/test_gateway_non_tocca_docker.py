#!/usr/bin/env python3
"""«Il gateway non tocca mai Docker» (`SECURITY.md`) — presidiata invece che dichiarata.

PERCHÉ ESISTE, per intero — serve a chi lo vedrà fallire.

Il canale di aggiornamento è costruito attorno a un invariante: **il gateway non esegue
nulla di privilegiato**. Il pulsante *Aggiorna* del pannello admin scrive soltanto un
*intent file* in `onboarding/`; l'update vero lo esegue la CLI host via systemd path
unit. La frase che chiude quel punto elenco è `Il gateway non tocca mai Docker.`

Quella frase era **vera e senza presidio**. È il terzo stato del metodo della voce
`a80025f1` — «per ogni garanzia in prosa: il codice regge? sì → merita un id, no → è un
finding» — e il terzo caso l'ha nominato 71d540e6 il 10/08: *regge, è presidiata in
parte, e il presidio non copre tutte le forme dell'oggetto.*

## Cosa NON è già coperto altrove, ed è la ragione per cui questo file esiste

`tools/tests/test_docker_sock_perimetro.py` presidia **il mount del socket in qualunque
compose**, e dopo la cura del 10/08 lo riconosce da qualunque path. Copre quindi la via
principale — ma «non tocca mai Docker» è una promessa sui MEZZI, e i mezzi sono più di
uno. Restano fuori di lì, e stanno qui:

  · `DOCKER_HOST` nell'environment — parlare col daemon via TCP non richiede alcun mount
  · `group_add` col gruppo `docker` — appartenenza, non montaggio
  · `privileged: true`
  · il **codice** del gateway: una SDK Python (`import docker`), o un `subprocess` che
    invoca il binario `docker`

⭐ E la ragione per cui il lato codice si legge con `ast` e non con `grep`: in
`services/gateway/app/admin.py` c'è un commento che NOMINA il socket — «nessun restart,
nessun docker.sock» — e dice il contrario di una violazione. *Un controllo che cerca una
stringa non distingue il codice dal commento che lo racconta*; `ast` non ha il problema,
perché i commenti non entrano nell'albero. Non è prudenza: è la classe di errore che il
10/08 ha prodotto quattro casi in un giorno.

## Il contratto quando la sonda non trova il bersaglio

Se il servizio `gateway` non si trova in nessun compose, o un alias YAML non si risolve,
questo test **fallisce**. Un presidio che non trova l'oggetto da controllare non è
«a posto»: è cieco, e il silenzio somiglia troppo a un ok.

Stile: stdlib-only, nessuna dipendenza — gira ovunque giri Python.
Uso:  python3 tools/tests/test_gateway_non_tocca_docker.py    (esce 1 al primo difetto)
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVIZIO = "gateway"
APP = ROOT / "services" / "gateway" / "app"

# I mezzi per parlare con Docker, nominati uno per uno con la ragione: un elenco che
# spiega è un elenco che si può discutere, allungare e — soprattutto — capire quando
# diventa rosso. Ogni voce: (regex sulla riga di compose, perché è un accesso).
MEZZI_COMPOSE: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("socket montato", re.compile(r"docker\.sock"),
     "chi raggiunge il socket parla con l'API Docker e può creare un container che monta /"),
    ("DOCKER_HOST", re.compile(r"\bDOCKER_HOST\b"),
     "il daemon si raggiunge anche via TCP: nessun mount, stesso potere"),
    ("group_add docker", re.compile(r"group_add|(?<![\w-])docker(?=\s*$)"),
     "appartenere al gruppo `docker` equivale a root sull'host"),
    ("privileged", re.compile(r"privileged\s*:\s*true"),
     "un container privilegiato ha già tutto, Docker compreso"),
)

# Lato codice: i moduli che parlano con Docker o che permettono di invocarlo.
MODULI_VIETATI = {"docker", "docker.client", "aiodocker", "podman"}
MODULI_ESECUZIONE = {"subprocess", "os.system", "pty", "commands"}


def blocchi_yaml(testo: str, chiave: str, livello: int = 2) -> list[list[str]]:
    """I blocchi di una chiave a un dato livello di indentazione, come liste di righe.

    Un parser YAML qui non c'è (la suite di `tools/tests/` gira `uvx pytest` STDLIB-ONLY:
    un import di troppo non fallisce il tuo test, impedisce agli ALTRI di partire, perché
    rompe in fase di collect). Serve solo isolare un blocco per indentazione, e per
    quello bastano le righe.
    """
    righe = testo.splitlines()
    fuori: list[list[str]] = []
    i = 0
    testa = re.compile(rf"^ {{{livello}}}{re.escape(chiave)}\s*:\s*$")
    while i < len(righe):
        if testa.match(righe[i]):
            corpo = [righe[i]]
            i += 1
            while i < len(righe):
                r = righe[i]
                if r.strip() and len(r) - len(r.lstrip()) <= livello:
                    break
                corpo.append(r)
                i += 1
            fuori.append(corpo)
            continue
        i += 1
    return fuori


def con_alias_risolti(corpo: list[str], testo: str) -> tuple[list[str], list[str]]:
    """Il blocco più i blocchi degli alias YAML che usa. Ritorna (righe, alias irrisolti).

    🔴 SENZA QUESTO IL PRESIDIO SAREBBE FINTO, e per una ragione che si vede solo
    aprendo il file: il servizio `gateway` comincia con
    `<<: [*restart, *logging, *security, *readonly]`. Se un domani uno di quegli anchor
    portasse un volume o una variabile, guardare il solo blocco `gateway:` non lo
    vedrebbe — e il test direbbe di sì con la stessa faccia.
    ⇒ è la forma «l'insieme misurato è più piccolo dell'oggetto promesso», la stessa che
      questo giorno ha prodotto quattro volte (i volumi enumerati a mano, le categorie
      dedotte dalla tipografia, i file in lista, il socket per path).
    """
    righe = list(corpo)
    irrisolti: list[str] = []
    for nome in sorted(set(re.findall(r"\*([A-Za-z0-9_-]+)", "\n".join(corpo)))):
        anchor = re.search(rf"^(\s*)[\w.-]+\s*:\s*&{re.escape(nome)}\b", testo, re.M)
        if not anchor:
            irrisolti.append(nome)
            continue
        indent = len(anchor.group(1))
        inizio = testo[:anchor.start()].count("\n")
        tutte = testo.splitlines()
        blocco = [tutte[inizio]]
        for r in tutte[inizio + 1:]:
            if r.strip() and len(r) - len(r.lstrip()) <= indent:
                break
            blocco.append(r)
        righe.extend(blocco)
    return righe, irrisolti


def senza_commento(riga: str) -> str:
    """`x: 1  # nota` → `x: 1`. Vedi la gemella in test_docker_sock_perimetro.py: là
    l'assenza di questo taglio ha reso rossa una baseline sana, il 10/08."""
    return re.sub(r"(?:^|\s)#.*$", "", riga)


def controlla_compose() -> tuple[int, int]:
    """Il gateway, in ogni compose che lo definisce, non ha i mezzi per toccare Docker."""
    compose = sorted(p for p in ROOT.rglob("compose*.y*ml")
                     if p.is_file() and ".git" not in p.parts)
    errori = trovati = 0
    for p in compose:
        testo = p.read_text(encoding="utf-8")
        for corpo in blocchi_yaml(testo, SERVIZIO):
            trovati += 1
            righe, irrisolti = con_alias_risolti(corpo, testo)
            if irrisolti:
                errori += 1
                print(f"  ✗ {p.name}: alias YAML non risolti {irrisolti} — il blocco del\n"
                      f"      gateway ne eredita il contenuto e questa sonda non lo vede.\n"
                      f"      Non è un dettaglio di parsing: è perimetro mancante.")
            for nome, rx, perche in MEZZI_COMPOSE:
                colpevoli = [r for r in righe if rx.search(senza_commento(r))]
                if colpevoli:
                    errori += 1
                    print(f"  ✗ {p.name} · servizio `{SERVIZIO}` → {nome}\n"
                          f"      {colpevoli[0].strip()}\n"
                          f"      {perche}\n"
                          f"      SECURITY.md promette «Il gateway non tocca mai Docker».")
    if not trovati:
        print(f"  ✗ nessun servizio `{SERVIZIO}` trovato in {len(compose)} compose: la\n"
              f"      sonda non sta guardando il repo giusto, e un presidio che non\n"
              f"      trova il bersaglio TACE — il silenzio somiglia a un ok.")
        return 1, 0
    print(f"  ✓ compose: {trovati} definizioni del servizio `{SERVIZIO}`, nessun mezzo "
          f"verso Docker ({len(MEZZI_COMPOSE)} cercati)")
    return errori, trovati


def controlla_codice() -> tuple[int, int]:
    """Il codice del gateway non importa una SDK Docker e non sa eseguire processi."""
    if not APP.is_dir():
        print(f"  ✗ {APP.relative_to(ROOT)} non esiste: la sonda guarda il posto sbagliato")
        return 1, 0
    sorgenti = sorted(APP.rglob("*.py"))
    if not sorgenti:
        print(f"  ✗ nessun .py sotto {APP.relative_to(ROOT)}")
        return 1, 0
    errori = 0
    for f in sorgenti:
        try:
            albero = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        except SyntaxError as e:                      # un sorgente rotto non è «a posto»
            errori += 1
            print(f"  ✗ {f.relative_to(ROOT)} non si compila ({e}): non misurato")
            continue
        for nodo in ast.walk(albero):
            nomi: list[str] = []
            if isinstance(nodo, ast.Import):
                nomi = [a.name for a in nodo.names]
            elif isinstance(nodo, ast.ImportFrom) and nodo.module:
                nomi = [nodo.module]
            for n in nomi:
                radice = n.split(".")[0]
                if n in MODULI_VIETATI or radice in MODULI_VIETATI:
                    errori += 1
                    print(f"  ✗ {f.relative_to(ROOT)}:{nodo.lineno} importa `{n}`:\n"
                          f"      è una SDK Docker. SECURITY.md promette che il gateway\n"
                          f"      non tocca mai Docker — l'update lo esegue la CLI host.")
                elif radice in MODULI_ESECUZIONE:
                    errori += 1
                    print(f"  ✗ {f.relative_to(ROOT)}:{nodo.lineno} importa `{n}`:\n"
                          f"      il gateway non esegue processi (invariante del canale\n"
                          f"      di aggiornamento: scrive un intent, non agisce).\n"
                          f"      Se serve davvero, va deciso e scritto — non importato.")
    print(f"  ✓ codice: {len(sorgenti)} sorgenti del gateway letti con `ast` "
          f"(i commenti non contano, per costruzione)")
    return errori, len(sorgenti)


def main() -> int:
    print(f"garanzia presidiata: «Il gateway non tocca mai Docker» (SECURITY.md)")
    e1, _ = controlla_compose()
    e2, _ = controlla_codice()
    totale = e1 + e2
    if totale:
        print(f"\n  ✗ {totale} difetti: la garanzia in SECURITY.md non è più vera.")
    return 1 if totale else 0


def test_il_gateway_non_ha_mezzi_verso_docker() -> None:
    """Il gancio che rende questo file un test PER PYTEST, non solo per la mano.

    Senza, `uvx pytest tools/tests/` RACCOGLIE il file (il nome combacia) e **non esegue
    niente**: nessuna funzione `test_*`, nessun errore, verde. Misurato il 09/08 su un
    presidio gemello — a mano usciva 1, la suite restava «250 passed».
    """
    assert main() == 0


def test_la_sonda_sa_diventare_rossa() -> None:
    """La controprova: le funzioni di riconoscimento vedono i casi che devono vedere.

    ⭐ *Un caso provato una volta a mano è una verifica; dentro il test è una garanzia.*
    Qui la prova è sui MEZZI, uno per uno: senza queste righe, chi restringe un pattern
    «per precisione» rimette il buco e nessun file cambia colore.
    """
    finto = """services:
  gateway:
    image: x
    environment:
      DOCKER_HOST: tcp://192.0.2.1:2375
    volumes:
      - /run/docker.sock:/var/run/docker.sock
    privileged: true
  altro:
    image: y
"""
    corpo = blocchi_yaml(finto, "gateway")
    assert len(corpo) == 1, "il blocco del servizio non è stato isolato"
    righe = [senza_commento(r) for r in corpo[0]]
    for nome, rx, _ in MEZZI_COMPOSE:
        if nome == "group_add docker":
            continue                      # non è in questo campione: ha il suo caso sotto
        assert any(rx.search(r) for r in righe), f"mezzo non riconosciuto: {nome}"
    # il blocco si ferma dove deve: `altro:` non ci finisce dentro
    assert not any("image: y" in r for r in corpo[0]), "il blocco ha sconfinato nel servizio dopo"

    gruppo = """services:
  gateway:
    group_add:
      - docker
"""
    righe_g = [senza_commento(r) for r in blocchi_yaml(gruppo, "gateway")[0]]
    rx_g = next(rx for nome, rx, _ in MEZZI_COMPOSE if nome == "group_add docker")
    assert any(rx_g.search(r) for r in righe_g), "group_add non riconosciuto"

    # e gli alias: il mezzo nascosto in un anchor deve entrare nel perimetro
    con_anchor = """x-comune: &comune
  volumes:
    - /var/run/docker.sock:/var/run/docker.sock
services:
  gateway:
    <<: *comune
    image: x
"""
    righe_a, irrisolti = con_alias_risolti(blocchi_yaml(con_anchor, "gateway")[0], con_anchor)
    assert not irrisolti, f"alias non risolto: {irrisolti}"
    assert any("docker.sock" in r for r in righe_a), \
        "il mezzo dentro l'anchor è invisibile: il perimetro è più piccolo dell'oggetto"


if __name__ == "__main__":
    sys.exit(main())
