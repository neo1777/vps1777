"""Guardie sul download degli artefatti NotebookLM — il gateway INOLTRA, non possiede.

Perché esiste questo file, per intero — serve a chi lo vedrà fallire.

H6 ha tolto al gateway il volume dei cookie Google: è l'unico servizio esposto su
Internet, e non deve poter leggere quel filesystem. Gli artefatti Studio (audio, video,
pdf) nascono nello stesso container che possiede i cookie, in un volume SEPARATO — e
per portarli fuori il gateway li chiede a `nb1777-mcp` su rete interna, esattamente
come fa per lo stato del profilo.

**La scorciatoia che questo file impedisce** è quella che chiunque proporrebbe in buona
fede guardando il codice fra un anno: *«perché passare da nb1777-mcp? montiamo anche
qui il volume degli artefatti e serviamo il file con FileResponse, è più semplice e più
veloce»*. Lo è. Ed è il primo passo per rimettere il gateway a leggere un volume del
container che tiene la sessione Google — la distanza fra `nlm-artifacts` e `nlm-auth`
è una riga di `compose.yaml` scritta distrattamente.

Stile: stdlib-only, nessuna app in piedi (come `test_proxy_internal_404` e
`test_internal_archive_description`). Le proprietà presidiate sono STRUTTURALI —
chi possiede il file, e in che ORDINE stanno i controlli.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
ADMIN = (APP / "admin.py").read_text(encoding="utf-8")
ROUTES = (APP / "routes.py").read_text(encoding="utf-8")
CLIENT = (APP / "nlm_client.py").read_text(encoding="utf-8")


def _funzione(sorgente: str, nome: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for nodo in ast.walk(ast.parse(sorgente)):
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)) and nodo.name == nome:
            return nodo
    raise AssertionError(f"funzione '{nome}' non trovata: rinominata? allora aggiorna il test")


def _solo_codice(nodo: ast.AST, sorgente: str) -> str:
    """Le righe eseguibili di una funzione, senza commenti né docstring.

    Non è pignoleria: i commenti di `admin.py` NOMINANO le cose che il codice non fa
    («il gateway non monta il volume»). Un test ingenuo leggerebbe quelle parole e
    concluderebbe il contrario di ciò che voleva misurare — la prosa al posto del
    programma. Stessa tecnica di `test_proxy_internal_404._solo_codice`.
    """
    corpo = list(nodo.body)                                   # type: ignore[attr-defined]
    if (corpo and isinstance(corpo[0], ast.Expr)
            and isinstance(corpo[0].value, ast.Constant)
            and isinstance(corpo[0].value.value, str)):
        corpo = corpo[1:]                                     # via la docstring
    righe = sorgente.splitlines()
    fuori = []
    for stmt in corpo:
        for n in range(stmt.lineno, (stmt.end_lineno or stmt.lineno) + 1):
            testo = righe[n - 1]
            fuori.append(testo.split("#", 1)[0] if "#" in testo else testo)
    return "\n".join(fuori)


# ── la rotta esiste, ed è sotto admin ────────────────────────────────────────

def test_la_rotta_e_registrata() -> None:
    assert 'Route("/admin/nlm/artifact/{name}"' in ROUTES, \
        "la rotta di download non è registrata: il link nella pagina porterebbe a un 404"
    assert "admin.nlm_artifact" in ROUTES


def test_auth_PRIMA_di_qualunque_cosa() -> None:
    """`_require_admin` deve stare in cima: un file scaricabile senza sessione è il difetto."""
    codice = _solo_codice(_funzione(ADMIN, "nlm_artifact"), ADMIN)
    righe = [r.strip() for r in codice.splitlines() if r.strip()]
    posizione = next(i for i, r in enumerate(righe) if "_require_admin" in r)
    assert posizione == 0, f"_require_admin non è il primo gesto (riga {posizione}): {righe[:3]}"
    # e il redirect si onora: senza questo, `_require_admin` sarebbe decorativo
    assert "return redirect" in codice


# ── la proprietà che vale davvero: il gateway NON tocca il filesystem ────────

def test_il_gateway_NON_apre_file_dal_disco() -> None:
    """La scorciatoia vietata: `FileResponse`/`open()` qui significherebbe volume montato."""
    codice = _solo_codice(_funzione(ADMIN, "nlm_artifact"), ADMIN)
    for vietato in ("FileResponse", "open(", "Path(", "os.path", "aiofiles"):
        assert vietato not in codice, (
            f"`{vietato}` in nlm_artifact: il gateway sta leggendo un file suo. "
            "Gli artefatti li possiede nb1777-mcp (H6) — qui si inoltra e basta.")
    assert "nlm_client.artifact_stream" in codice, \
        "il file deve arrivare da nb1777-mcp sul canale interno"


def _volumi_montati(compose: str, servizio: str, prossimo: str) -> list[str]:
    """Le righe `- x:/y` sotto `volumes:` di un servizio. Commenti esclusi.

    ⚠️ Scritto DOPO averlo sbagliato: la prima versione cercava la stringa `nlm-auth`
    nel blocco del gateway e falliva sul COMMENTO che dice «NIENTE nlm-auth (H6)».
    Cioè misurava la prosa al posto del programma — l'errore che la docstring di
    `_solo_codice`, due funzioni più sopra, descrive per esteso. *Avere la lezione
    scritta nel file non protegge: va applicata al gesto, non riletta dopo.*
    """
    blocco = compose[compose.index(f"  {servizio}:"):compose.index(f"  {prossimo}:")]
    dentro, montati = False, []
    for riga in blocco.splitlines():
        nuda = riga.split("#", 1)[0].rstrip()
        if not nuda.strip():
            continue
        if re.fullmatch(r"\s{4}volumes:", nuda):
            dentro = True
            continue
        if dentro:
            m = re.fullmatch(r"\s{6}-\s*(\S+)", nuda)
            if m:
                montati.append(m.group(1))
            elif re.match(r"\s{4}\w", nuda):      # chiave successiva allo stesso livello
                dentro = False
    return montati


def test_nessun_volume_di_nb1777_montato_nel_gateway() -> None:
    """Controprova sul compose: la riga sbagliata sarebbe una sola, e silenziosa."""
    compose = (Path(__file__).resolve().parents[3] / "compose.yaml").read_text(encoding="utf-8")
    montati = _volumi_montati(compose, "gateway", "archive-mcp")
    assert montati, "nessun volume letto: il parser non ha guardato (o il compose è cambiato)"
    for m in montati:
        assert not m.startswith(("nlm-auth:", "nlm-artifacts:")), (
            f"il gateway monta `{m}`: è esattamente ciò che H6 ha tolto. "
            "Il file si chiede a chi lo possiede, non si legge.")
    # controprova positiva: il volume ESISTE ed è montato da chi deve
    nb = _volumi_montati(compose, "nb1777-mcp", "nb1777-bot")
    assert "nlm-artifacts:/var/lib/nlm-artifacts:rw" in nb, nb


# ── i tre stati: «sconosciuto» non è «nessuno» ───────────────────────────────

def test_la_lista_distingue_VUOTO_da_IRRAGGIUNGIBILE() -> None:
    """Un `None` reso come lista vuota direbbe «non hai artefatti» mentre il servizio è giù.

    È il difetto già pagato due volte in casa: la sonda che non ha potuto guardare e
    risponde «non c'è». Qui si misura che i due rami esistano e siano DIVERSI.
    """
    fn = _funzione(ADMIN, "_nlm_artifacts_html")
    codice = _solo_codice(fn, ADMIN)
    assert "is None" in codice, "manca il ramo «non raggiungibile»: resterebbero due stati su tre"
    ramo_none = codice[codice.index("is None"):]
    assert "sconosciut" in ramo_none.lower(), \
        "il ramo None non dice che l'elenco è sconosciuto"
    assert re.search(r"if not items", codice), "manca il ramo «nessun artefatto»"


def test_il_nome_finisce_nell_html_ESCAPED_e_nell_url_QUOTED() -> None:
    """Il nome viene dal container: nell'href va `quote`, nel testo `html.escape`."""
    codice = _solo_codice(_funzione(ADMIN, "_nlm_artifacts_html"), ADMIN)
    assert 'quote(i["name"])' in codice, "nome non URL-encoded nell'href"
    assert 'html.escape(i["name"])' in codice, "nome non escapato nel testo del link"


def test_l_audit_registra_il_nome_CHIESTO_non_quello_servito() -> None:
    """Nell'audit va il path param GREZZO: se qualcuno prova `../../etc/passwd`, si vede.

    La cura «ovvia» che questo test impedisce è ripulire il nome prima di scriverlo nel
    log — sembra igiene, ed è perdita di prove: un audit che registra il nome ripulito
    dice cosa è stato SERVITO, mentre la domanda a cui deve rispondere è cosa è stato
    CHIESTO. `name` è dichiarato in `_CHIAVI_NOTE` proprio come valore che viene da fuori.
    """
    fn = _funzione(ADMIN, "nlm_artifact")
    codice = _solo_codice(fn, ADMIN)
    assert 'request.path_params.get("name"' in codice, "il nome non arriva più dal path"
    # gli audit devono citare la variabile grezza, non una sua versione ripulita
    for chiamata in re.findall(r"audit\(\{[^}]*\}\)", codice, re.S):
        if '"name"' in chiamata:
            assert re.search(r'"name":\s*name\b', chiamata), (
                f"l'audit non registra il nome grezzo: {chiamata.strip()[:120]}")


# ── il canale interno ────────────────────────────────────────────────────────

def test_artifact_stream_usa_lo_STESSO_segreto_degli_altri_interni() -> None:
    codice = _solo_codice(_funzione(CLIENT, "artifact_stream"), CLIENT)
    assert "_base_and_headers()" in codice, \
        "header interno non riusato: senza segreto nb1777-mcp risponde 403 (fail-closed)"
    assert "/internal/nlm/artifact" in codice


def test_artifact_stream_NON_bufferizza(  # noqa: D103
) -> None:
    """`stream=True`: un video letto in RAM nel gateway è un file intero per download."""
    codice = _solo_codice(_funzione(CLIENT, "artifact_stream"), CLIENT)
    assert "stream=True" in codice, "risposta bufferizzata: cambia il costo in memoria"
    assert "build_request" in codice
