"""Guardie sul rifiuto di `internal/` nel proxy del gateway.

Perché esiste questo file, per intero — serve a chi lo vedrà fallire.

`docs/ARCHITECTURE.md` (#65, 03/08) ha scritto nero su bianco una distinzione che
prima viveva solo in due commenti: *da dentro* la rete `backend`, senza segreto,
`nb1777-mcp` risponde **403** (fail-closed dichiarato); *da fuori*, attraverso il
proxy, ogni sotto-path `internal/` riceve **404**, perché un 403 confermerebbe
l'esistenza della rotta a chi la sta cercando.

La PR ha allineato la documentazione al codice. **Non ha toccato la ragione per
cui il disallineamento era stato possibile**: la scelta di sicurezza viveva solo
in un commento, e un commento non ferma nessuno. Chiunque, domani, può
"correggere" quel 404 in 403 — perché per «non autorizzato» il 403 *sembra* la
risposta giusta — e non trova niente che lo fermi. La riga appena scritta in
`ARCHITECTURE.md` diventerebbe falsa e il difetto tornerebbe dall'altro verso.
Rilievo di `b82df434` nella revisione della #65.

Stile: stdlib-only, nessuna app in piedi, come `test_internal_archive_description`.
Le proprietà presidiate qui sono *strutturali* — quale codice di risposta si
sceglie, e in che ORDINE stanno i controlli — e un test che le legge nel sorgente
resiste anche a un refactoring fatto in buona fede.
"""
from __future__ import annotations

from pathlib import Path

SRC = (Path(__file__).resolve().parents[1] / "app" / "proxy.py").read_text(encoding="utf-8")
FUNC = SRC[SRC.index("async def proxy(request: Request)"):SRC.index("def _constant_eq")]


def _solo_codice(testo: str) -> str:
    """Le righe eseguibili, senza commenti né docstring.

    Non è pignoleria: il commento di `proxy.py` che spiega questa scelta *nomina*
    il 403 per dire che NON lo si usa. Un test ingenuo leggerebbe quella parola e
    concluderebbe che il codice risponde 403 — misurando la prosa al posto del
    programma. Stessa tecnica di `test_internal_archive_description._solo_codice`.
    """
    fuori, dentro = [], False
    for riga in testo.splitlines():
        spoglia = riga.strip()
        if spoglia.count('"""') == 1:
            dentro = not dentro
            continue
        if dentro or spoglia.startswith("#") or spoglia.startswith('"""'):
            continue
        fuori.append(riga.split("  #")[0])
    return "\n".join(fuori)


CODICE = _solo_codice(FUNC)


def test_ogni_rifiuto_del_proxy_nega_con_404_e_mai_con_403():
    """Il codice di risposta è esso stesso un'informazione.

    Il proxy è raggiungibile dall'esterno per costruzione. Un 403 dice *la rotta
    esiste, non hai il permesso*; un 404 dice *questa superficie, per te, non
    esiste*. Chi cerca una superficie da attaccare impara qualcosa dal primo e
    niente dal secondo — e vale per TUTTA la catena di rifiuto, non solo per
    `internal/`: segreto sbagliato, servizio sconosciuto e path interno devono
    essere indistinguibili da fuori.
    """
    assert "403" not in CODICE, (
        "un 403 in proxy() rivela l'esistenza di ciò che sta negando: "
        "la scelta è 404 su ogni rifiuto (ARCHITECTURE.md, e routes.py:109)"
    )
    assert CODICE.count("status_code=404") >= 2, (
        "i rifiuti che negano l'esistenza sono almeno due — il path `internal/` "
        "e il segreto che non torna — e devono negarla entrambi allo stesso modo"
    )


def test_il_rifiuto_di_internal_viene_prima_del_confronto_del_segreto():
    """Ordine non negoziabile, ed è la ragione scritta a `proxy.py`: «Rifiuto
    PRIMA di ogni altro check → non rivela nulla».

    Se l'ordine si invertisse, una richiesta esterna verso un endpoint interno
    arriverebbe al confronto del segreto: il rifiuto resterebbe un 404, quindi
    NESSUN test sul codice di risposta se ne accorgerebbe, ma il chiamante
    avrebbe comunque guadagnato un oracolo sul segreto (i tempi del confronto).
    Una proprietà che nessuna delle due guardie ovvie protegge da sola.
    """
    assert CODICE.index('startswith("internal/")') < CODICE.index("effective_gateway_secret"), (
        "il blocco di `internal/` deve precedere il controllo del segreto: "
        "chi arriva da fuori non deve nemmeno raggiungere il confronto"
    )


def test_il_blocco_copre_il_path_esatto_e_i_sotto_path():
    """Due forme, non una.

    `startswith("internal/")` da solo lascerebbe passare `/<secret>/<svc>/internal`
    — senza barra finale — che è esattamente il path che un catch-all `{path:path}`
    produce quando l'URL non ha lo slash. Il caso limite è la metà del controllo
    che si dimentica per prima, perché la forma "normale" è l'altra.
    """
    assert 'sub_path == "internal"' in CODICE, (
        "manca il path esatto: `/<secret>/<servizio>/internal` (senza slash) passerebbe"
    )
    assert 'sub_path.startswith("internal/")' in CODICE, (
        "manca il prefisso: ogni sotto-path di internal/ deve essere rifiutato"
    )


def test_il_rifiuto_lascia_una_traccia_di_audit():
    """Un canale di rifiuto senza log è un canale di cui non sai se è stato
    tentato. È l'unico segnale che dice che qualcuno ha provato a passare da lì."""
    assert '"proxy_internal_blocked"' in CODICE, (
        "il rifiuto di internal/ deve emettere l'evento di audit `proxy_internal_blocked`"
    )
