"""Il backup deve salvare TUTTI i volumi del prodotto, e la lista non deve stare a mano.

IL DIFETTO CHE QUESTO FILE PROTEGGE (trovato il 10/08, prima di una formattazione della
VPS, mentre si preparava la prova del restore che @Neo aveva chiesto):

    VOLUMES=$(docker volume ls -q | grep -E '^vps1777_(gateway-data|archive-data|nlm-auth|
                                     tailscale-state|caddy-data|caddy-config)$' || true)

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

⚠️ QUESTO TEST NON USA DOCKER: legge i compose col parser yaml e il sorgente di
   `backup.sh`. Deve poter girare in CI senza demone, altrimenti è il presidio che si
   spegne proprio dove serve.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

_ROOT = Path(__file__).resolve().parents[2]
_BACKUP = _ROOT / "tools" / "backup.sh"

# Volumi che il prodotto NON deve salvare, con la ragione accanto. Una esclusione con un
# nome e un perché è una decisione; una lista senza motivazioni è di nuovo l'enumerazione
# a mano che questo file esiste per impedire.
ESCLUSI = {
    "portainer-data": "tool di amministrazione opzionale (compose.ops.portainer), non dati del prodotto",
}


def _volumi_dichiarati() -> dict[str, str]:
    """{nome_volume: file che lo dichiara} su tutti i compose del repo."""
    out: dict[str, str] = {}
    for f in sorted(_ROOT.glob("compose*.yaml")):
        d = yaml.safe_load(f.read_text()) or {}
        for v in (d.get("volumes") or {}):
            out.setdefault(v, f.name)
    return out


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
