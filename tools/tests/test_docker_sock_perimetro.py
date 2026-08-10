#!/usr/bin/env python3
"""Nessun compose monta il docker.sock — tranne UNO, nominato, e solo con l'avviso scritto.

PERCHÉ ESISTE, per intero — serve a chi lo vedrà fallire.

Montare `/var/run/docker.sock` in un container significa dargli **accesso root all'host**:
chi raggiunge quel socket parla con l'API Docker e può creare un container che monta `/`.
Il finding H13 lo dice, e il repo ha già la lezione scritta in `compose.ops.backup.yaml`
(«NIENTE docker.sock (finding 2.8/H13)»).

## Il difetto che questo file cura (issue #69, punto ②)

Il gate di H13 era:

    evidence:
      - file: compose.ops.backup.yaml
        not_contains: ["/var/run/docker.sock"]

⇒ garantiva **«il container di backup non monta il socket»** — vero — mentre la proprietà
che interessa a chi legge un registro di sicurezza è **«nessun container di questo repo
monta il socket»**, che è un'altra cosa. Se domani un compose nuovo lo montasse, H13
resterebbe `closed` e verde: *il gate guarda un nome di file, non la proprietà.*
⭐ È la forma che ci è costata tutto il 09/08: una sonda che risponde benissimo a una
domanda VICINA a quella che si ha in testa.

## Cosa presidia, e perché l'eccezione è dentro il test

`compose.ops.watchtower.yaml` il socket lo monta davvero, e resta: quel profilo è opt-in,
non attivo di default, e Watchtower è dichiarato declassato. **L'eccezione non si toglie:
si NOMINA** — così è una decisione scritta invece di un'assenza di controllo, e aggiungerne
una seconda richiede di modificare questo file, cioè di dichiararla.

E l'eccezione è **condizionata**: vale solo finché accanto al mount resta l'avviso che
`:ro` non limita l'API. *Senza quell'avviso chi attiva il profilo legge `:ro` e ha ogni
ragione di intenderlo come una limitazione.* Se qualcuno cancella il commento «per pulizia»,
questo test diventa rosso: il perché non può sparire in silenzio lasciando il cosa.

Stile: stdlib-only, nessuna dipendenza — gira ovunque giri Python.
Uso:  python3 tools/tests/test_docker_sock_perimetro.py     (esce 1 al primo difetto)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# 🔴 IL PATH NON È L'OGGETTO (misurato il 10/08 da abdd732a, voce `a80025f1`).
# Qui c'era `SOCK = "/var/run/docker.sock"`, una stringa sola, e il presidio era cieco
# a `- /run/docker.sock:/run/docker.sock`. Non è una variante esotica: su ogni distro
# con systemd `/var/run` È un symlink a `/run`, quindi i due path sono lo STESSO
# oggetto — provato con `stat -c '%i'`, inode identico su entrambi (1537, macchina di
# sviluppo, 10/08). Un mount scritto nella forma corta dà lo stesso accesso root
# all'host, e questo file usciva **0** dichiarando «10/12 compose NON montano il socket».
#
# ⭐ Il caso è peggiore di un guardiano muto, perché questo RENDICONTA: quella frase era
#    falsa nel momento in cui la stampava. *Un controllo che tace lascia il dubbio; uno
#    che afferma in positivo lo toglie.*
#
# 🔑 Perché era rimasto: la issue #69 ha allargato il PERIMETRO DEI FILE (1 → 10 → 12,
#    `rglob`, i template in `plugins/`) e ha lasciato invariata la CHIAVE cercata dentro
#    ogni file. L'asse allargato non era quello bucato.
#
# 🛡️ PERCHÉ IL BASENAME E NON L'INODE, visto che l'inode è la risposta giusta alla
#    domanda «è quell'oggetto?» (rilievo di b82df434, 10/08 — l'insieme dei path che
#    portano al socket non è enumerabile: `/run`, `/var/run`, il rootless sotto `~`, e
#    `DOCKER_HOST` che li rende arbitrari). Il principio è accolto, il meccanismo no:
#    **questo test gira in CI, dove il socket Docker non esiste** — `os.stat()` su un
#    path assente solleva, e la sorgente di un bind mount è comunque un path della
#    macchina di PRODUZIONE, non del runner. Un presidio statico non può risolvere un
#    inode che non ha davanti.
#    ⇒ la chiave che chiude la famiglia senza uscire dal testo è il **basename**: ogni
#      path che porta a quel socket finisce per `docker.sock`, comunque lo si prefissi.
#      Resta fuori solo `DOCKER_HOST` (e un socket rinominato a mano alla sorgente):
#      `DOCKER_HOST` è presidiato a parte in `test_gateway_non_tocca_docker.py`, il
#      rename deliberato no — ed è scritto qui invece che taciuto.
SOCK_RE = re.compile(r"docker\.sock")
SOCK = "docker.sock"           # per i messaggi all'umano; il confronto usa SOCK_RE

# 🔴 E UN ANELLO PIÙ IN LÀ: LA DIRECTORY CHE LO CONTIENE (rilievo di 71d540e6 sulla PR
# #147, misurato mentre la cura qui sopra era già scritta). Passata la chiave dal path al
# basename, restava scoperto `- /run:/host-run:ro`: **stesso accesso, e la riga non
# nomina mai `docker.sock`**. Chi monta il contenitore non nomina il contenuto.
# ⭐ È la classe che questa cura cura, riprodotta DALLA cura: l'insieme era definito da
#    una stringa, e l'oggetto no.
#
# 🔑 E LA REGOLA NON È «UN NOME IN PIÙ» (b82df434, stessa revisione): allargando il nome
#    verrebbe `path → basename → directory → symlink → …`, un anello per volta, ognuno
#    vero e nessuno ultimo. La chiave che non si aggira, sul piano di un controllo
#    statico, è **enunciabile in una riga e senza varianti**:
#
#        nessun bind con sorgente `/`, `/var`, o dentro `/run` / `/var/run`
#
#    Non è una lista di nomi: è la regione del filesystem in cui quel socket vive. Prende
#    anche `/run/alias.sock` — un symlink dal nome arbitrario — che nessun elenco di
#    basename avrebbe catturato.
RADICI = ("/run", "/var/run")
ESATTE = {"/", "/var"}


def sorgente_del_mount(riga: str) -> str | None:
    """Il lato SORGENTE di un mount, o None se la riga non è un mount.

    Copre le due sintassi di compose: la corta (`- /a:/b:ro`) e la lunga (`source: /a`).
    Una sorgente relativa o parametrica (`./data`, `${X}`) torna com'è: non è un antenato
    del socket e non fa scattare nulla.
    """
    r = senza_commento(riga)
    m = re.match(r"\s*-\s*([^:\s]+):", r) or re.match(r"\s*source:\s*(\S+)\s*$", r)
    return m.group(1) if m else None


def sorgente_pericolosa(sorgente: str) -> bool:
    """La sorgente è il socket, o vive nella regione del filesystem in cui il socket sta.

    `/run/alias.sock` non nomina Docker e non è una directory: è dentro `/run`, e tanto
    basta. È il caso che ha convinto a scrivere la regola per REGIONE invece che per nome.
    """
    p = re.sub(r"/\./", "/", sorgente).rstrip("/") or "/"
    if SOCK_RE.search(p) or p in ESATTE:
        return True
    return any(p == r or p.startswith(r + "/") for r in RADICI)

# L'eccezione, nominata: file → (ragione, aghi che DEVONO restare accanto al mount).
# Aggiungerne una significa modificare questa riga, cioè dichiararla per iscritto.
ECCEZIONI: dict[str, tuple[str, tuple[str, ...]]] = {
    "compose.ops.watchtower.yaml": (
        "profilo ops.autoupdate: opt-in, non attivo di default, Watchtower declassato",
        ("`:ro` NON LIMITA L'API", "accesso root all'host"),
    ),
    # 🔎 TROVATO DA QUESTO TEST AL PRIMO GIRO (09/08), e non era nella issue #69: quella
    # nominava solo watchtower e diceva «se un domani un ALTRO compose lo montasse, H13
    # resterebbe verde». Non era un domani — c'era già, e nessuno se n'era accorto perché
    # il gate guardava un file solo. *La proprietà che un presidio non misura non è
    # «probabilmente a posto»: è semplicemente non misurata.*
    # Portainer senza socket non esiste (è la sua funzione): l'alternativa non è montarlo
    # meglio, è non attivare il profilo. Qui non c'è nemmeno `:ro` — ed è più onesto.
    "compose.ops.portainer.yaml": (
        "profilo ops.portainer: opt-in, porta su loopback (tunnel SSH), no-new-privileges",
        ("ACCESSO ROOT ALL'HOST", "non attivare il profilo"),
    ),
}


def senza_commento(riga: str) -> str:
    """La riga senza la sua parte di commento — `x: 1  # nota` → `x: 1`.

    🔴 QUESTA FUNZIONE È NATA DA UN FALSO POSITIVO FABBRICATO DALLA CURA QUI SOPRA, e
    misurato subito: allargata la chiave al basename, la BASELINE è diventata rossa su
    `compose.ops.backup.yaml` — il file che il socket non lo monta e lo dichiara. La sua
    riga è `BACKUP_VOLUMES_DIR: /volumes   # backup.sh tara da qui → niente docker.sock`:
    commento a FINE riga, e il filtro precedente guardava solo `lstrip().startswith("#")`.

    ⭐ La forma generale, e vale oltre questo file: **curare un buco di copertura è un
    cambio di SUPERFICIE** — la domanda da farsi non è «la chiave nuova è giusta?» ma
    *«quale popolazione entra adesso in ogni filtro a valle, e su quale era tarato?»*.
    Il filtro a valle era tarato sui commenti a inizio riga, e la popolazione nuova
    arrivava con il `#` in mezzo.

    Il taglio richiede uno spazio prima del `#` (o inizio riga): è la convenzione YAML, e
    così un valore che contiene un cancelletto attaccato non viene troncato per sbaglio.
    """
    return re.sub(r"(?:^|\s)#.*$", "", riga)


def righe_di_mount(testo: str) -> list[str]:
    """Le righe che montano DAVVERO il socket, escluse quelle di commento.

    Un commento che nomina il socket per spiegare perché NON lo si monta (è il caso di
    `compose.ops.backup.yaml`: «NIENTE docker.sock (finding 2.8/H13)») non è un mount —
    ed è la ragione per cui un filtro sui `#` c'era già prima di questa cura. Quello che
    mancava era il commento a fine riga: vedi `senza_commento`.

    Due strade, e servono entrambe: la riga NOMINA il socket, oppure il suo lato sorgente
    è una directory che lo contiene — quel secondo caso non contiene mai `docker.sock`.
    """
    fuori = []
    for r in testo.splitlines():
        if SOCK_RE.search(senza_commento(r)):
            fuori.append(r)
            continue
        s = sorgente_del_mount(r)
        if s and sorgente_pericolosa(s):
            fuori.append(r)
    return fuori


def main() -> int:
    # rglob e non glob (rilievo 71d540e6, 09/08): con `glob` il perimetro era la ROOT
    # (10 file) mentre la proprietà promessa è «nessun container DI QUESTO REPO» — e i
    # compose sono 12: due stanno in `plugins/` (example-bot, example-mcp). Oggi nessuno
    # dei due monta il socket, quindi non c'era un difetto vivo — ma erano fuori dal cono
    # del presidio, ⭐ ed è la STESSA distanza fra domanda e sonda che questo test cura
    # passando da un file a tutti. Peggio: quei due sono TEMPLATE DA COPIARE, quindi il
    # codice nuovo nasce proprio dove il presidio non guardava.
    compose = sorted(p for p in ROOT.rglob("compose*.y*ml")
                     if p.is_file() and ".git" not in p.parts)
    if not compose:
        print("✗ nessun compose trovato: la sonda non sta guardando il repo giusto")
        return 1
    print(f"perimetro: {len(compose)} file compose*.y*ml")

    errori = 0
    montano = []
    for p in compose:
        testo = p.read_text(encoding="utf-8")
        # solo le righe EFFETTIVE: un commento che nomina il socket (come in
        # compose.ops.backup.yaml, che spiega perché NON lo monta) non è un mount.
        righe = righe_di_mount(testo)
        if not righe:
            continue
        montano.append(p.name)
        if p.name not in ECCEZIONI:
            errori += 1
            print(f"  ✗ {p.name} monta {SOCK} e NON è fra le eccezioni nominate.\n"
                  f"      È accesso root all'host (il `:ro` non limita l'API Docker).\n"
                  f"      Se è deliberato, aggiungilo a ECCEZIONI con la ragione: una\n"
                  f"      decisione scritta, non un controllo che tace.")
            continue
        ragione, aghi = ECCEZIONI[p.name]
        # «accanto al mount» si MISURA (rilievo 71d540e6): prima era `a not in testo`,
        # cioè in TUTTO il file — spostando l'avviso in fondo il test restava verde e la
        # garanzia dichiarata era più stretta di quella misurata. Ora la finestra sono le
        # 15 righe che precedono la riga del mount: se l'avviso si allontana, si vede.
        tutte = testo.splitlines()
        i_mount = next(i for i, r in enumerate(tutte)
                       if SOCK_RE.search(r) and not r.lstrip().startswith("#"))
        finestra = "\n".join(tutte[max(0, i_mount - 15):i_mount])
        mancanti = [a for a in aghi if a not in finestra]
        if mancanti:
            errori += 1
            print(f"  ✗ {p.name}: l'eccezione è ammessa ({ragione}) ma l'AVVISO è sparito.\n"
                  f"      Manca: {mancanti}\n"
                  f"      Chi attiva il profilo legge `:ro` e lo intende come una\n"
                  f"      limitazione: senza l'avviso, il cosa resta e il perché no.")
        else:
            print(f"  ✓ {p.name} — eccezione nominata, avviso presente ({ragione})")

    non_montano = len(compose) - len(montano)
    print(f"\n  {non_montano}/{len(compose)} compose NON montano il socket · "
          f"{len(montano)} lo montano ({', '.join(montano) or '—'})")
    # controprova positiva: se NESSUNO lo montasse, l'eccezione sarebbe morta e questo
    # test non starebbe più presidiando niente — va detto, non lasciato passare in verde.
    if not montano:
        print("  ⚠️ nessun compose monta il socket: l'eccezione in ECCEZIONI è ormai\n"
              "     senza oggetto — toglila, o questo test presidia una regola vuota.")
    return 1 if errori else 0


def test_riconosce_ogni_forma_del_mount() -> None:
    """La controprova che mancava: il sabotaggio dai DUE path, fatto dal test.

    Il 10/08 il buco è stato trovato sabotando a mano un compose e guardando l'exit —
    prima da `/var/run/docker.sock` (usciva 1, bene) poi da `/run/docker.sock` (usciva 0).
    ⭐ *Un caso provato una volta a mano è una verifica; dentro il test è una garanzia*
    (b82df434, 10/08). Senza queste righe, chi domani restringe `SOCK_RE` «per precisione»
    rimette il buco e nessun file cambia colore.

    Le forme sotto non sono immaginate: `/run` e `/var/run` sono lo stesso inode su
    systemd, il path rootless è quello che Docker usa senza root, e l'ultima è la prova
    che la chiave è il **basename** e non il prefisso.
    """
    forme = [
        "      - /var/run/docker.sock:/var/run/docker.sock",
        "      - /run/docker.sock:/run/docker.sock",
        "      - /run/docker.sock:/var/run/docker.sock:ro",
        "      - /home/utente/.docker/run/docker.sock:/var/run/docker.sock",
        "      - /qualunque/prefisso/docker.sock:/var/run/docker.sock",
        "      - /var/run/./docker.sock:/var/run/docker.sock",
        "      - /var/run/docker.sock:/tmp/altrove:ro",     # destinazione diversa
        # ⬇️ le tre che NON nominano il socket: montano la directory che lo contiene.
        #    Trovate da 71d540e6 revisionando la PR #147, sabotando ciò che io avevo
        #    appena curato — la cura vedeva il nome e non l'oggetto, un anello più in là.
        "      - /run:/host-run:ro",
        "      - /var/run:/hr:ro",
        "      - /var/run/:/host-run",                       # con lo slash finale
        "      - /var/run:/var/run",
        "      - /:/host:ro",
        "        source: /var/run",                          # sintassi lunga
        # ⬇️ e il caso che ha deciso la forma della regola: un socket dal nome
        #    arbitrario dentro /run (un symlink sull'host). Nessun elenco di basename
        #    lo prende; la REGIONE sì.
        "      - /run/alias.sock:/tmp/d.sock",
    ]
    for f in forme:
        assert righe_di_mount(f) == [f], f"forma non riconosciuta: {f}"

    # e il verso opposto, altrettanto necessario: il commento che spiega perché NON si
    # monta deve restare invisibile al presidio, o il file più corretto del repo
    # diventerebbe il primo a farlo fallire.
    innocue = [
        "      # NIENTE docker.sock (finding 2.8/H13): montare il socket dà al container",
        "  # (scan-mode) → cercabile subito, nessun restart, nessun docker.sock.",
        # ⬇️ il caso VERO che ha reso rossa la baseline appena allargata la chiave:
        #    commento a fine riga, in `compose.ops.backup.yaml`. Sta qui perché è il
        #    falso positivo che la cura ha fabbricato, non un'ipotesi di scuola.
        "      BACKUP_VOLUMES_DIR: /volumes   # backup.sh tara da qui → niente docker.sock",
        # ⬇️ IL VERSO OPPOSTO, e senza queste righe la regola per REGIONE sarebbe un
        #    guardiano che grida: i mount normali devono restare invisibili, o il
        #    presidio diventa un rumore che si impara a ignorare.
        "      - ./onboarding:/onboarding",
        "      - gateway-uploads:/uploads",          # volume nominato, non un bind
        "      - /opt/dati:/dati:ro",
        "      - ${VPS1777_DIR}/secrets:/run/secrets:ro",   # DESTINAZIONE in /run: legittima
    ]
    for r in innocue:
        assert righe_di_mount(r) == [], f"commento scambiato per mount: {r}"


def test_presidio_gira_anche_in_ci() -> None:
    """Il gancio che rende questo file un test PER PYTEST, non solo per la mano.

    Senza, `uvx pytest tools/tests/` — la riga che lo esegue in CI — RACCOGLIE il file
    (il nome combacia) e **non esegue niente**: nessuna funzione `test_*`, nessun errore,
    verde. Misurato il 09/08 sabotando questo file su `main`: eseguito a mano usciva 1,
    la suite restava «250 passed».
    """
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
