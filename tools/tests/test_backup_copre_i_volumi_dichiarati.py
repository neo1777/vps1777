"""Il backup deve salvare TUTTI i volumi del prodotto, e la lista non deve stare a mano.

IL DIFETTO CHE QUESTO FILE PROTEGGE (trovato il 10/08, prima di una formattazione della
VPS, mentre si preparava la prova del restore che @Neo aveva chiesto):

    VOLUMES=$(docker volume ls -q | grep -E '^vps1777_(sei|nomi|scritti|qui|a|mano)$' || true)

⚠️ La regex qui sopra è PARAFRASATA di proposito: i nomi veri non si citano. Uno dei volumi
di allora è sorvegliato da `test_nlm_auth_montaggi.py`, che tiene la lista dei file
autorizzati a nominarlo — e un file di test che citasse la vecchia regex verbatim finirebbe
dentro quella lista **per una ragione puramente documentale**, allargando un presidio di
sicurezza per far passare un commento.
⭐ *Documentare un difetto con la sua stringa esatta accende le sonde che quella stringa
cercano: la lapide non va scritta con le parole del morto.* (E la prima stesura di QUESTA
riga nominava il volume mentre spiegava di non nominarlo: il gate è rimasto rosso e aveva
ragione.)

Una lista di volumi **enumerata a mano**, e con `|| true` in coda. Misurato allora:

    dichiarati nei compose   8      salvati dal backup   6
    🔴 gateway-uploads   compose.yaml (BASE), montato da `gateway`   NON salvato
    🔴 nlm-artifacts     compose.yaml (BASE), montato da `nb1777-mcp` NON salvato
    ⚪ tailscale-state   nella regex e in NESSUN compose: residuo morto

`gateway-uploads` sono i file caricati dagli utenti: backup → formatta → restore, e non
tornano. **E il restore direbbe «fatto» dicendo il vero** — ha ripristinato tutto ciò che
il backup conteneva. Un backup che non trova una cosa non fallisce: la omette in silenzio.

🔑 LA REGOLA, ed è già scritta in questo repo — `restore.sh` la applica per il down:
   *«Docker sa già cosa appartiene al progetto: glielo si chiede, invece di dirglielo.»*
   `backup.sh` faceva il contrario sullo stesso oggetto. Qui si verifica che la lista
   venga CHIESTA (`docker compose config --volumes`) e non dichiarata.

⚠️ QUESTO TEST NON USA DOCKER **E NON USA PyYAML**: solo stdlib. La prima stesura aveva
   `pytest.importorskip("yaml")` — e la CI lancia `uvx pytest tools/tests/`, che è
   stdlib-only: il test veniva SALTATO, e **uno skip si legge come un pass**. Trovato da
   abdd732a provandolo con `uvx`, non leggendolo.
   ⭐ La ragione era scritta due righe sopra, da me, in questo stesso docstring («deve
   poter girare in CI, altrimenti è il presidio che si spegne proprio dove serve») — e
   subito sotto ho importato una dipendenza che in CI non c'è. *Enunciare il vincolo non
   è verificarlo: il presidio che si spegne da solo, terza volta in un giorno.*
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_BACKUP = _ROOT / "tools" / "backup.sh"

# Volumi che il prodotto NON deve salvare, con la ragione accanto. Una esclusione con un
# nome e un perché è una decisione; una lista senza motivazioni è di nuovo l'enumerazione
# a mano che questo file esiste per impedire.
ESCLUSI = {
    "portainer-data": "tool di amministrazione opzionale (compose.ops.portainer), non dati del prodotto",
}


def _volumi_dichiarati() -> dict[str, str]:
    """{nome_volume: file che lo dichiara} su tutti i compose del repo — SOLO STDLIB.

    Legge il blocco `volumes:` di primo livello: la riga `volumes:` a colonna 0, poi le
    chiavi indentate finché non si torna a colonna 0. Non è un parser YAML e non deve
    esserlo: qui serve UNA struttura nota, e la dipendenza esterna spegneva il test in CI.
    ⚠️ Se un compose scrivesse i volumi in forma non canonica (flow `{a: null}`), questo
    li mancherebbe — per questo `test_il_parser_vede_qualcosa` fissa un valore ATTESO:
    un parser che smette di trovare non deve poter passare come «nessun volume».
    """
    out: dict[str, str] = {}
    for f in sorted(_ROOT.glob("compose*.yaml")):
        dentro = False
        for riga in f.read_text().splitlines():
            if re.match(r"^volumes:\s*$", riga):
                dentro = True
                continue
            if dentro:
                if riga.strip() == "" or riga.lstrip().startswith("#"):
                    continue
                if not riga.startswith((" ", "\t")):   # tornati a colonna 0: blocco finito
                    dentro = False
                    continue
                m = re.match(r"^\s+([A-Za-z0-9_.-]+):", riga)
                if m:
                    out.setdefault(m.group(1), f.name)
    return out


def test_il_parser_vede_qualcosa():
    """Il parser stdlib deve trovare i volumi NOTI: se smette di funzionare, gli altri
    test passerebbero su un insieme vuoto — «nessun volume scoperto» perché nessun volume.
    ⭐ È la controprova positiva: la sonda sa dire di sì?"""
    v = _volumi_dichiarati()
    for atteso in ("gateway-uploads", "nlm-artifacts", "gateway-data", "archive-data"):
        assert atteso in v, f"il parser non vede più «{atteso}»: sta guardando il vuoto"


def test_backup_non_enumera_i_volumi_a_mano():
    """La lista si CHIEDE a docker compose, non si scrive nel sorgente.

    È il test che rende inutile tutti gli altri di questo file: finché la lista è chiesta,
    non può divergere dai compose. Se qualcuno torna a enumerarla, questo diventa rosso
    prima che il backup perda un volume.
    """
    src = _BACKUP.read_text()
    assert "compose config --volumes" in src, (
        "backup.sh non chiede i volumi a docker compose: se sono enumerati a mano, "
        "un volume aggiunto ai compose non entra nel backup e nessuno se ne accorge"
    )


def test_nessun_volume_del_prodotto_resta_fuori():
    """Ogni volume dichiarato nei compose o è salvato, o è escluso CON UNA RAGIONE."""
    dichiarati = _volumi_dichiarati()
    assert dichiarati, "nessun volume letto dai compose: il test non sta guardando niente"
    src = _BACKUP.read_text()
    scoperti = []
    for vol, dove in sorted(dichiarati.items()):
        if vol in ESCLUSI:
            continue
        # o compare nel sorgente (lista/eccezione esplicita), o è coperto dalla chiamata
        # a `docker compose config --volumes`, che li prende tutti per costruzione.
        if "compose config --volumes" not in src and vol not in src:
            scoperti.append(f"{vol} (dichiarato in {dove})")
    assert not scoperti, (
        "volumi dichiarati nei compose e non salvati dal backup: "
        + " · ".join(scoperti)
        + "  ⇒ backup → restore li perderebbe, e il restore direbbe «fatto»"
    )


def test_la_regex_storica_non_e_tornata():
    """Controprova sul difetto esatto: la vecchia enumerazione non deve riapparire.

    Il caso ⭐ è `tailscale-state`, che era nella regex e in NESSUN compose: un nome morto
    dentro una lista viva. Se ricompare, qualcuno ha ri-scritto l'insieme a mano.
    """
    src = _BACKUP.read_text()
    vecchia = re.search(r"\^vps1777_\((?:[a-z-]+\|){2,}[a-z-]+\)\$", src)
    assert vecchia is None, (
        f"trovata di nuovo una lista di volumi enumerata nella regex: {vecchia.group(0) if vecchia else ''}"
    )


def test_zero_volumi_trovati_non_e_un_backup_riuscito():
    """Il difetto che la PRIMA cura aveva lasciato, spostato di un anello.

    Trovato da 71d540e6 revisionando la PR #146, e provato eseguendo: `docker compose
    config` dà i nomi LOGICI, il prefisso del progetto lo mette lo script. Col prefisso
    sbagliato ogni volume risulta «non esiste ancora» — che è un avviso, non un errore —
    quindi il ciclo salvava ZERO volumi, stampava «✓ Volumi dumpati» e usciva 0.

    ⭐ Una cura può riprodurre la classe che cura, un anello più in là: lì era la lista
    enumerata, qui il nome costruito. In entrambi i casi l'insieme FINALE non veniva
    confrontato con niente.
    """
    src = _BACKUP.read_text()
    assert 'if [ -z "$(echo "$VOLUMES"' in src or "nessun volume trovato" in src, (
        "backup.sh non verifica che almeno un volume sia stato trovato: col prefisso "
        "sbagliato salverebbe zero volumi e uscirebbe 0"
    )
    assert "die" in src.split("nessun volume trovato")[0][-200:], (
        "zero volumi non fa fallire il backup: un backup vuoto che esce 0 è peggio "
        "di un backup che non parte"
    )


def test_gli_esclusi_hanno_una_ragione_scritta():
    """Un'esclusione senza motivo è indistinguibile da una dimenticanza."""
    for vol, perche in ESCLUSI.items():
        assert perche and len(perche) > 20, f"l'esclusione di {vol} non dice perché"


def _volumi_del_compose_base() -> set[str]:
    """I volumi dichiarati nel SOLO compose.yaml: quelli che esistono in ogni installazione."""
    return {v for v, dove in _volumi_dichiarati().items() if dove == "compose.yaml"}


def _volumi_montati_nel_backup() -> set[str]:
    """I `<vol>:/volumes/<vol>:ro` ATTIVI (non commentati) di compose.ops.backup.yaml."""
    out = set()
    for riga in (_ROOT / "compose.ops.backup.yaml").read_text().splitlines():
        m = re.match(r"^\s+-\s+([A-Za-z0-9_.-]+):/volumes/([A-Za-z0-9_.-]+):ro\s*$", riga)
        if m:
            assert m.group(1) == m.group(2), f"mount incoerente nel backup: {riga.strip()}"
            out.add(m.group(1))
    return out


def test_il_container_backup_monta_i_volumi_del_base():
    """Il difetto del 10/08, un anello più in là — misurato il 29/08 aprendo il primo
    core notturno a due livelli: dentro c'erano gateway-data e nlm-auth, NON
    gateway-uploads (i file degli utenti) né nlm-artifacts. `backup.sh` li salva
    tutti (la lista la CHIEDE), ma nel container vede solo ciò che il compose gli
    monta sotto /volumes — e quella lista era enumerata a mano, senza presidio.
    Ogni volume del compose BASE deve essere montato :ro nel container backup; i
    volumi degli overlay (caddy, portainer) hanno la loro riga commentata e non
    sono di questo test."""
    base = _volumi_del_compose_base()
    montati = _volumi_montati_nel_backup()
    assert base, "nessun volume letto da compose.yaml: il test non sta guardando niente"
    assert montati, "nessun mount /volumes/ letto dal backup: il parser guarda il vuoto"
    mancanti = sorted(base - montati)
    assert not mancanti, (
        "volumi del compose base NON montati nel container backup: "
        + ", ".join(mancanti)
        + "  ⇒ il core notturno li omette in silenzio (backup.sh vede solo /volumes)"
    )


def test_il_parser_dei_mount_vede_i_tre_storici():
    """Controprova positiva: la sonda dei mount deve trovare i tre che ci sono da sempre."""
    montati = _volumi_montati_nel_backup()
    for atteso in ("gateway-data", "archive-data", "nlm-auth"):
        assert atteso in montati, f"il parser dei mount non vede più «{atteso}»"
