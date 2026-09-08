"""Guardie sull'endpoint D9 — `set_description` inoltrata al gateway.

Stile dei test del gateway: stdlib-only, niente app in piedi. Per le proprietà
di SICUREZZA si ispeziona il sorgente, come fa già `test_oauth_consent` con la
guardia H32 sul `compare_digest`. Non è un ripiego: queste proprietà sono
*strutturali* (l'ordine dei controlli, il codice di risposta scelto), e un test
che le legge nel sorgente resiste anche a un refactoring che le riscriverebbe
in buona fede.
"""
from __future__ import annotations

import re
from pathlib import Path

SRC = (Path(__file__).resolve().parents[1] / "app" / "routes.py").read_text(encoding="utf-8")


def _corpo(nome: str) -> str:
    """Il testo di UNA funzione, dalla sua `def` alla `def` successiva.

    ⚠️ Prima del 07/09/2026 questa fetta era `SRC[index(la funzione):index("\\nroutes = [")]`,
    ed era corretta **per un accidente di ordine**: la funzione era l'ultima del file
    prima del registro delle rotte. La #278 ne ha aggiunta una seconda subito sotto, e
    con la vecchia fetta le guardie di QUESTA funzione avrebbero letto anche QUELLA —
    per esempio `count("set_meta") == 1` sarebbe diventato 2 e il test sarebbe
    diventato rosso senza che la proprietà che difende fosse cambiata di una virgola.
    *Un test che si tara sull'ordine del file misura il file, non la proprietà.*
    """
    i = SRC.index(f"def {nome}")
    resto = SRC[i:]
    tagli = [x for x in (resto.find("\nasync def ", 1), resto.find("\ndef ", 1),
                         resto.find("\nroutes = [")) if x > 0]
    return resto[:min(tagli)] if tagli else resto


def _solo_codice(testo: str) -> str:
    """Le righe eseguibili, senza commenti né docstring.

    Serve perché una guardia che cerca una stringa nel sorgente non deve
    inciampare nella PROSA che spiega la scelta: il commento di questa funzione
    dice «risponde 404, non 403», e un test ingenuo lo leggerebbe come la
    presenza di un 403 nel codice. Un test-guardia deve distinguere ciò che il
    programma FA da ciò che il programma RACCONTA — che è, in piccolo, la stessa
    distinzione su cui abbiamo passato la giornata.
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

CODICE = _solo_codice(_corpo("internal_archive_description"))
RUOLO = _solo_codice(_corpo("internal_archive_ruolo"))
GUARDIA = _solo_codice(_corpo("_guardia_interna"))
PATH_DB = _solo_codice(_corpo("_path_del_db"))

# Le rotte interne dell'archivio, per nome della funzione: le guardie di CLASSE
# qui sotto girano su tutte, così la prossima non nasce scoperta. Dal 07/09 sono
# due — ed è la ragione per cui queste guardie sono diventate cicli.
ROTTE_INTERNE = ("internal_archive_description", "internal_archive_ruolo")


def test_ogni_rotta_interna_passa_dalla_guardia_come_prima_cosa():
    """La proprietà di CLASSE, non della singola rotta.

    Fino al 07/09 c'era una rotta sola e i controlli stavano dentro di lei; la
    #278 ne ha aggiunta una seconda, e copiare quei due gradini sarebbe stato più
    breve. Ma due copie di un controllo di sicurezza divergono, e a divergere è
    quella che nessuno rilegge. Qui si pretende che ogni rotta CHIAMI la guardia,
    e che la chiami PRIMA di leggere il corpo della richiesta: un parsing fatto
    prima del portone è lavoro svolto per conto di chi non è ancora entrato.
    """
    for nome in ROTTE_INTERNE:
        codice = _solo_codice(_corpo(nome))
        assert "_guardia_interna(request" in codice, f"{nome} non passa dalla guardia"
        assert codice.index("_guardia_interna") < codice.index("await request.json"), \
            f"{nome} legge il corpo prima di aver verificato chi chiama"


def test_risponde_404_e_mai_403():
    """Un 403 confermerebbe che la rotta esiste a chi la sta cercando.

    Le rotte sono raggiungibili dall'esterno per costruzione (Caddy fa
    reverse_proxy catch-all sul gateway), quindi il codice di risposta è esso
    stesso un'informazione: si nega l'esistenza, non il permesso.
    """
    for nome, codice in (("guardia", GUARDIA), ("path del db", PATH_DB),
                         *((n, _solo_codice(_corpo(n))) for n in ROTTE_INTERNE)):
        assert "403" not in codice, f"{nome}: un 403 rivela che la rotta esiste"
    assert GUARDIA.count("404") >= 2, \
        "sia il controllo di rete sia quello del segreto negano con 404"


def test_il_controllo_di_rete_viene_prima_del_segreto():
    """Ordine non negoziabile: chi arriva da fuori non deve nemmeno arrivare al
    confronto del segreto. Se l'ordine si invertisse, un attaccante esterno
    potrebbe misurare i tempi di risposta del confronto."""
    assert GUARDIA.index("ip_is_internal") < GUARDIA.index("compare_digest")


def test_il_segreto_e_constant_time_e_fail_closed():
    assert "hmac.compare_digest" in GUARDIA, "confronto non constant-time"
    assert "not atteso or" in GUARDIA, "segreto non configurato deve NEGARE (fail-closed)"


def test_il_path_lo_costruisce_il_gateway_non_il_chiamante():
    """Path traversal impossibile per costruzione: il chiamante manda un NOME,
    il percorso lo compone il gateway a partire dalla sua directory."""
    assert 'Path(get_settings().archive_db_dir)' in PATH_DB
    assert re.search(r'fullmatch\(r"\[A-Za-z0-9\._-\]', PATH_DB), "nome del db non validato"
    # e nessuna rotta si costruisce il path per conto suo, scavalcando la guardia
    for nome in ROTTE_INTERNE:
        codice = _solo_codice(_corpo(nome))
        assert "_path_del_db(db)" in codice, f"{nome} non usa il compositore comune"
        assert "archive_db_dir" not in codice, f"{nome} si costruisce il path da sé"


def test_d17_la_description_e_trattata_come_dato_non_fidato():
    """D17, che Neo ha voluto DENTRO la D9: quel campo finisce nel contesto di
    un LLM con l'autorevolezza di un metadato di sistema."""
    assert "_MAX_DESCRIZIONE" in CODICE, "manca il cap di lunghezza"
    assert "control_chars" in CODICE, "i caratteri di controllo vanno rifiutati"


def test_ogni_scrittura_lascia_un_audit():
    """Un canale di scrittura senza log è un canale di cui non sai se è stato usato."""
    assert GUARDIA.count("audit(") >= 2, "servono audit sui due rifiuti"
    for nome in ROTTE_INTERNE:
        codice = _solo_codice(_corpo(nome))
        assert "audit(" in codice, f"{nome} scrive senza lasciare traccia"
    assert "archive_desc_set" in CODICE
    assert "archive_ruolo_set" in RUOLO


def test_ogni_rotta_scrive_UN_campo_e_nulla_altro():
    """Nessuna rotta interna è una scrittura generica sulla tabella `meta`.

    Il rischio non è teorico: `set_meta(db_path, key, value)` prende la CHIAVE
    come parametro, quindi una rotta che si facesse passare `key` dal chiamante
    diventerebbe un canale per scrivere qualunque metadato — e il perimetro di
    questo canale non sarebbe più leggibile in nessun posto. Ogni rotta nomina
    la sua chiave nel sorgente, e ne scrive una sola.
    """
    assert 'set_meta(db_path, "description", desc)' in CODICE
    assert CODICE.count("set_meta") == 1
    assert 'set_meta(db_path, "ruolo", ruolo)' in RUOLO
    assert RUOLO.count("set_meta") == 1


def test_il_ruolo_ha_un_vocabolario_chiuso():
    """#278 — il campo esiste per essere LETTO DA UNA MACCHINA: se accettasse
    testo libero sarebbe una seconda description, cioè il problema che cura."""
    assert "_RUOLI_AMMESSI" in RUOLO, "il valore non è confrontato con un vocabolario"
    assert "bad_ruolo" in RUOLO, "un valore fuori vocabolario deve essere RIFIUTATO"
    # e il rifiuto è parlante: un vocabolario chiuso che non dice quali sono le
    # parole ammesse costringe chi sbaglia a indovinare (o a leggere il sorgente).
    assert "ammessi" in RUOLO, "il rifiuto deve portare l'elenco dei valori ammessi"


def test_il_vocabolario_dei_ruoli_e_lo_STESSO_dei_due_servizi():
    """I due gemelli devono concordare, e nessun linguaggio può obbligarli.

    `gateway` e `archive-mcp` hanno contesti di build separati: non possono
    importarsi a vicenda, quindi il vocabolario è scritto DUE volte. Una lista
    duplicata senza un presidio invecchia da un lato solo — e il lato che
    invecchia sarebbe il gateway, che è quello che RIFIUTA: un valore aggiunto
    solo in archive-mcp verrebbe respinto con «bad_ruolo» e nessuno saprebbe
    perché. (È la stessa classe della divergenza fra servizi gemelli che ci.yml
    dichiara scoperta per i lock.)
    """
    src_mcp = (Path(__file__).resolve().parents[3] / "services" / "archive-mcp"
               / "app" / "db.py").read_text(encoding="utf-8")
    def _valori(testo: str, ago: str) -> list[str]:
        riga = testo[testo.index(ago):]
        return re.findall(r'"([a-z]+)"', riga[:riga.index("\n")])
    assert _valori(src_mcp, "RUOLI: tuple") == _valori(SRC, "_RUOLI_AMMESSI: tuple") != [], \
        "il vocabolario dei ruoli è divergente fra archive-mcp e gateway"


def test_le_rotte_sono_registrate():
    for rotta in ("/internal/archive/description", "/internal/archive/ruolo"):
        assert f'"{rotta}"' in SRC, f"{rotta} non è registrata"
        assert 'methods=["POST"]' in SRC[SRC.index(f'"{rotta}"'):][:120]


def test_usa_un_segreto_DEDICATO_e_non_quello_del_canale_nlm():
    """La proprietà che il design vietava e che l'implementazione ha violato lo stesso.

    `gateway_secret` apre anche `/internal/nlm/*`, cioè stato E INSTALLAZIONE dei
    profili-cookie Google. Montarlo su archive-mcp — per una feature che scrive un
    campo di testo — significa che un archive-mcp compromesso eredita QUEI poteri.
    Il design consolidato lo escludeva a lettere chiare; la prima implementazione
    l'ha fatto comunque, e nessun test poteva accorgersene perché **nessun test
    copriva la scelta del segreto**: la suite verificava che il confronto fosse
    constant-time e fail-closed, cioè COME si confronta, mai QUALE segreto.
    Trovato da setaccio confrontando il compose col design. Questa guardia esiste
    perché non serva più un umano per accorgersene.

    ⚠️ 07/09 — la scelta del segreto sta ora nella GUARDIA condivisa (#278 ha
    aggiunto la seconda rotta). La proprietà non è cambiata, il posto sì: e
    d'ora in poi vale per tutte le rotte interne dell'archivio invece che per
    quella sola. Si guarda ANCHE dentro le rotte, perché una di loro potrebbe
    rifare il controllo per conto suo col segreto sbagliato dopo essere passata
    dalla guardia — un privilegio che si allarga in un posto dove nessuno lo
    cerca più.
    """
    assert "effective_archive_desc_secret" in GUARDIA, "deve usare il segreto dedicato"
    for nome, codice in (("guardia", GUARDIA),
                         *((n, _solo_codice(_corpo(n))) for n in ROTTE_INTERNE)):
        assert "effective_gateway_secret" not in codice, \
            f"{nome}: gateway_secret apre anche /internal/nlm/*, è un ampliamento di privilegio"


def test_il_segreto_dedicato_non_ha_fallback_silenzioso():
    """Un `or self.gateway_secret` in fondo alla property rimetterebbe in piedi
    l'ampliamento di privilegio senza che nessuno lo noti: fail-closed, non
    fail-back."""
    src = (Path(__file__).resolve().parents[1] / "app" / "settings.py").read_text(encoding="utf-8")
    prop = src[src.index("def effective_archive_desc_secret"):]
    prop = prop[:prop.index("\n\n")] if "\n\n" in prop else prop
    assert "gateway_secret" not in prop.split('"""')[-1], "nessun fallback su gateway_secret"


# ── pre-flight dei segreti: guardia sulla CLASSE, non sul singolo segreto ──

def test_update_ha_un_preflight_sui_segreti():
    """Il fix di questo caso (generare archive_desc_secret in setup.sh) copriva
    solo l'installazione DA ZERO: l'update di una macchina viva non esegue
    setup.sh e `secrets/` è preservato, quindi un segreto NUOVO non arriverebbe
    mai. Proposto da b82df434 come fix di classe: il prossimo segreto che
    aggiungeremo avrebbe ripetuto lo stesso guasto.

    ⚠️ 20/07 — QUESTO TEST PROTEGGEVA UN DIFETTO. Pretendeva la stringa `st_size == 0`
    nel sorgente, cioè **un'implementazione** invece della proprietà che il suo stesso
    commento dichiarava («un segreto VUOTO deve contare come mancante»). E `st_size == 0`
    non implementa quella proprietà: un file con solo «\n» è 1 byte, quindi PIENO per il
    codice e vuoto per chiunque altro (riprodotto su banco da b82df434). Un test che
    asserisce la forma della riga rende quella riga **immodificabile** e quindi rende il
    difetto permanente: chi l'avesse corretta avrebbe visto un test rosso e concluso di
    aver sbagliato. Ora si asserisce la proprietà, e il comportamento è verificato
    davvero — eseguendo la funzione — in `tools/tests/test_vps1777.py`, che dal 20/07 gira
    in CI (prima non lo faceva: dieci test verdi che nessuno lanciava).
    """
    src = (Path(__file__).resolve().parents[3] / "tools" / "vps1777.py").read_text(encoding="utf-8")
    assert "_secrets_mancanti" in src, "manca il pre-flight dei segreti nell'update"
    assert "preflight-secrets" in src, "il pre-flight non è uno step tracciato"
    # Il controllo FATALE guarda il compose che si sta INSTALLANDO, non quello attuale:
    # è il rosso del 20/07 (la 0.40.0 è fallita perché il pre-flight girava uno step
    # prima che il compose nuovo esistesse sul disco).
    assert "preflight-secrets-bundle" in src, "manca il pre-flight sul compose del bundle"
    assert "_secrets_mancanti(sorgenti, repo)" in src, \
        "il controllo fatale deve leggere le sorgenti del BUNDLE e cercare i file nel repo"
    # legge il compose, NON una lista scritta a mano: una lista andrebbe
    # aggiornata a ogni segreto nuovo, ed è proprio la dimenticanza che previene.
    fn = src[src.index("def _compose_sorgenti"):src.index("def cmd_update")]
    assert "compose.yaml" in fn, "la lista dei segreti va letta dal compose, non hardcodata"
    # PROPRIETÀ, non implementazione: «vuoto» deve essere vuoto-dopo-strip. Se un giorno
    # lo si scrive in un altro modo corretto, questo test non deve ostacolarlo — ma
    # `st_size == 0` da solo non basta più, ed è quello che va impedito.
    assert ".strip()" in fn, "un segreto con solo spazi/newline deve contare come VUOTO"
    # il rimedio non deve rimandare all'installatore completo su una macchina viva
    assert "NON lanciare `setup.sh`" in src, "il rimedio non deve consigliare setup.sh"
