"""
JSONL audit log writer.

Ogni evento è una riga JSON con ts, event, e attributi arbitrari. Append-only.

Due principi, imparati come findings (H17):

1. **Un audit muto è peggio di un audit assente.** Se la scrittura fallisce in
   silenzio, il pannello mostra una lista vuota e nessuno distingue "non è
   successo niente" da "non sto più registrando niente": è l'illusione della
   tracciabilità. Qui un fallimento incrementa un contatore ESPOSTO
   (`audit_health()`), finisce nei log del container, e quando la scrittura
   riparte lascia una riga `audit_write_recovered` nel log stesso.

2. **Non si legge un file dalla testa per mostrarne la coda.** `readlines()[-N:]`
   carica in RAM tutto il file per tenerne 200 righe: su un audit da centinaia di
   MB il pannello se lo porta dietro tutto. Si legge dalla FINE, a blocchi.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("gateway.audit")


def _settings() -> Any:
    """Accesso LAZY alle settings.

    Importare `.settings` a livello di modulo tira dentro pydantic (dipendenza
    pesante) e lega questo file al pacchetto `app`. Tenendolo lazy, `audit` resta
    importabile stdlib-only — la logica pura (`_tail_lines`, `_prune`) si testa
    senza il gateway, e un test può sostituire questo seam con un finto."""
    from .settings import get_settings
    return get_settings()

# sopra questa dimensione il log viene POTATO (righe oltre la retention). Il
# controllo è su st_size (economico) → la potatura è rara, non a ogni scrittura.
_PRUNE_SIZE = 5 * 1024 * 1024  # 5 MB

# Dopo una potatura, non si ri-pota finché il file non è ricresciuto di tanto.
# Senza questa isteresi, un log di 5 MB tutto DENTRO la retention (niente da
# potare) fa ripartire una riscrittura completa a OGNI evento: l'audit diventa
# O(dimensione-del-log) per richiesta — un amplificatore, non un registro.
_PRUNE_GROWTH = 1 * 1024 * 1024  # 1 MB
_next_prune_at = _PRUNE_SIZE

# ── tetto di DIMENSIONE e freno agli eventi anonimi (giro di revisione del 21/11/2026) ──
# La potatura toglieva solo le righe più vecchie della retention: dentro i 90 giorni il file
# cresceva senza limite, e ogni richiesta anonima con un segreto sbagliato ne scriveva una riga
# (`proxy_secret_mismatch`), senza freno. Una raffica riempiva il volume del gateway; sopra i
# 5 MB ogni megabyte in più faceva riscrivere il file INTERO dentro la richiesta (misurato il
# 21/11/2026 su un file di prova da 42 MB: 618 ms per una potatura, cronometrando `_prune`).
# Tre cure: (1) il file non supera `_MAX_BYTES`: oltre, si tiene la CODA (le righe più nuove) e
# si scrive quante ne sono andate; (2) gli eventi che chiunque può provocare da fuori hanno un
# tetto al minuto, e quelli in più si CONTANO in una riga sola; (3) la potatura si rifà quando
# il file è cresciuto di metà, non di 1 MB: il costo resta ammortizzato.
_MAX_BYTES = 20 * 1024 * 1024
_TIENI_DOPO_TAGLIO = 0.6            # dopo un taglio per dimensione resta il 60% del tetto
# Dentro ci sta ogni evento che si provoca SENZA credenziali valide. I tre `*_denied` sono le rotte
# native `/internal/*` del gateway: Caddy inoltra tutto, quindi da fuori si raggiungono (e cadono
# sull'IP non interno), una riga a richiesta. `oauth_refresh_revoked_client` è `/token` con un
# client_id qualunque. `proxy_upstream_busy` vuole un bearer, ma sotto carico è una riga a rifiuto.
_ANONIMI = frozenset({"proxy_secret_mismatch", "proxy_internal_blocked", "proxy_unknown_service",
                      "proxy_auth_fail", "archive_desc_denied", "archive_ruolo_denied",
                      "notifiche_denied", "oauth_refresh_revoked_client", "proxy_upstream_busy"})
_ANONIMI_AL_MINUTO = 60
_finestra_anonimi: dict[str, Any] = {"minuto": "", "visti": 0, "soppressi": 0}

# Lettura tail-like: blocchi dalla coda, e un tetto oltre il quale si smette di
# risalire (un file con righe patologicamente lunghe non deve finirci tutto in RAM).
_TAIL_BLOCK = 64 * 1024
_TAIL_MAX_BYTES = 8 * 1024 * 1024
MAX_READ_LIMIT = 1000  # tetto su `limit`: nessun chiamante può farsi dare tutto il file

# Salute del writer — un audit che smette di scrivere deve poterlo DIRE.
_write_failures = 0
_last_error = ""
_last_failure_ts = ""


def audit_health() -> dict[str, Any]:
    """Stato del writer di audit, per chi lo vuole mostrare o allarmare.

    `write_failures` è il numero di scritture fallite dall'ultimo successo: se è
    > 0, il registro NON è affidabile in questo momento e chi guarda il pannello
    deve saperlo. Vedi la nota nel report: l'aggancio alla UI vive in admin.py.
    """
    return {
        "write_failures": _write_failures,
        "last_error": _last_error,
        "last_failure_ts": _last_failure_ts,
        "healthy": _write_failures == 0,
    }


def _prune(path: Path, retention_days: int) -> None:
    """Riscrive il log tenendo solo le righe entro `retention_days` (per `ts`
    ISO, confronto lessicografico). Le righe senza ts leggibile si scartano.

    Streaming riga-per-riga su un file temporaneo: memoria costante anche su un
    log grande (prima si faceva `read_text()` dell'intero file).

    Con `retention_days` a 0 (nessuna retention) non si guarda l'età, ma il tetto di DIMENSIONE
    vale lo stesso: prima si usciva subito e il file cresceva senza limite. Le righe che non sono
    JSON si scartano e si CONTANO: una riga `audit_trimmed` dice quante.
    """
    if retention_days <= 0:
        _taglia_alla_coda(path)
        return
    corrotte = 0
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
    tmp = path.with_suffix(path.suffix + ".tmp")
    with path.open("r", encoding="utf-8", errors="replace") as src, \
            tmp.open("w", encoding="utf-8") as dst:
        for raw in src:
            line = raw.strip()
            if not line:
                continue
            try:
                ts = str(json.loads(line).get("ts", ""))
            except (json.JSONDecodeError, AttributeError):
                corrotte += 1
                continue
            if ts >= cutoff:
                dst.write(line + "\n")
        if corrotte:
            ora = datetime.now(timezone.utc).isoformat(timespec="seconds")
            dst.write(json.dumps({"ts": ora, "event": "audit_trimmed", "dropped": corrotte,
                                  "reason": "righe illeggibili"}, ensure_ascii=False) + "\n")
    _taglia_alla_coda(tmp)
    tmp.replace(path)  # atomico: un lettore concorrente vede il vecchio o il nuovo


def _taglia_alla_coda(f: Path) -> None:
    """Se `f` supera `_MAX_BYTES`, tiene le righe più NUOVE (la coda) fino a una frazione del
    tetto e mette in testa una riga che dice quante ne sono state tolte. Un audit che perde la
    testa lo deve dire: «non c'è» e «è stato tagliato» sono risposte diverse."""
    dim = f.stat().st_size
    if dim <= _MAX_BYTES:
        return
    da = dim - int(_MAX_BYTES * _TIENI_DOPO_TAGLIO)
    corto = f.with_suffix(f.suffix + ".coda")
    tolte = 0
    with f.open("rb") as src, corto.open("wb") as dst:
        for raw in src:
            if src.tell() <= da:
                tolte += 1
                continue
            if tolte is not None:
                ora = datetime.now(timezone.utc).isoformat(timespec="seconds")
                dst.write((json.dumps({"ts": ora, "event": "audit_trimmed", "dropped": tolte,
                                       "reason": "tetto di dimensione"}, ensure_ascii=False)
                           + "\n").encode("utf-8"))
                tolte = None
            dst.write(raw)
    corto.replace(f)


def _da_sopprimere(evento: Any, ora: str) -> dict[str, Any] | bool:
    """Per gli eventi che si provocano da fuori senza credenziali: True se questo va saltato;
    un dict (la riga di riepilogo del minuto appena chiuso) se prima va scritto quello."""
    if evento not in _ANONIMI:
        return False
    fin = _finestra_anonimi
    minuto = ora[:16]
    riepilogo: dict[str, Any] | bool = False
    if fin["minuto"] != minuto:
        if fin["soppressi"]:
            riepilogo = {"event": "audit_suppressed", "dropped": fin["soppressi"],
                         "reason": f"oltre {_ANONIMI_AL_MINUTO} eventi anonimi nel minuto {fin['minuto']}"}
        fin.update(minuto=minuto, visti=0, soppressi=0)
    fin["visti"] += 1
    if fin["visti"] > _ANONIMI_AL_MINUTO:
        fin["soppressi"] += 1
        return True
    return riepilogo


# ── ③ Un audit log accetta solo ciò che SA, non tutto ciò che riceve ────────────────
# `audit()` scriveva `{"ts": now, **event}`: qualunque cosa un chiamante mettesse nel dict
# finiva su disco verbatim. Il vettore concreto non è la malizia, è `{"error": str(exc)}` —
# un'eccezione che porta con sé una stringa di connessione, un header Authorization, un
# token in un URL. Basta un `except` che allarga il messaggio e il segreto è nel log.
#
# ⚠️ PERCHÉ UN'ALLOWLIST E NON UN RILEVATORE DI SEGRETI. I pattern esistono già e sono
#   curati: `security/check_no_leaks.py`, SECRET_PATTERNS. Ma il gateway gira in un
#   container il cui Dockerfile copia SOLO `app/` — `security/` non c'è a runtime, e
#   ricopiare quei pattern qui significherebbe due elenchi che divergono, cioè il difetto
#   che quel file esiste per impedire. ⇒ qui non si indovina cosa è segreto: si dichiara
#   cosa è ammesso. Fail-closed, e nessuna fonte duplicata.
#
# 🔑 LIMITE DICHIARATO, perché nessuno lo scambi per una difesa che non è: questo NON
#   rileva segreti. Contiene la SUPERFICIE. Un segreto messo in `error` (chiave ammessa,
#   contenuto libero) passa, troncato a 500 caratteri. Il rilevatore vero resta in CI.
#
# Le chiavi sono estratte con l'AST da tutte le chiamate del repo, non con un grep (il grep si
# ferma a fine riga e sulle chiamate multi-riga ne perdeva): le ricontrolla a ogni corsa
# `test_OGNI_chiave_usata_nel_repo_e_dichiarata`, che è la fonte del loro numero.
_CHIAVI_NOTE = frozenset({
    "by", "client_id", "connector", "db", "email", "email_known", "error", "event",
    "fields", "file", "files", "fmt", "i", "insecure", "ip", "jti", "latest", "len", "method",
    "notebook", "owner_configured", "path", "persisted", "reason", "rows", "running",
    "service", "status", "sub", "target", "user_id",
    # H84: dove va il permesso OAuth (l'host, mai l'URI intero) e quante registrazioni
    # mai autorizzate si sono tolte
    "destinazione", "pendenti_tolti", "redirect_host",
    # eliminazione di un DB: se con lui è stato tolto anche l'indice per senso
    "indice_tolto",
    # scritte dal modulo stesso, non dai chiamanti. `dropped`/`last_error` appartengono al
    # record di recovery, che oggi si scrive DIRETTO (r.182) e non passa di qui: sono
    # dichiarate perché il giorno che passasse non si rompa in silenzio.
    # ⚠️ qui avevo scritto "audit_write_recovered", che è un VALORE del campo `event`, non
    #    una chiave: un'allowlist di chiavi che contiene un valore non protegge nulla in più
    #    e fa credere il contrario.
    "ts", "dropped", "last_error",
    # 03/08 — `dichiarati_mb`: i MB che il client DICHIARA nel `Content-Length` quando
    # l'upload viene rifiutato prima di leggere il body (admin.py). È la dichiarazione
    # del client, non una misura nostra, e il nome lo dice: un `Content-Length` può
    # mentire, e chi legge l'audit deve poter distinguere «ci ha detto 8 GB» da «ne
    # abbiamo misurati 8». *Sta accanto a `libero_mb`, che invece è misurato da noi —
    # e la differenza fra i due nomi è l'unica cosa che impedisce di confonderli.*
    # 03/08 — `libero_mb`: i MB liberi sul disco quando un upload viene rifiutato per
    # spazio (admin.py). È un numero, non un path e non un identificativo: dice quanto
    # era stretto il disco, che è l'unica cosa utile per capire se il rifiuto era al
    # limite o abissale. **Aggiunta perché il presidio qui sopra mi ha fermata**: il test
    # `test_OGNI_chiave_usata_nel_repo_e_dichiarata` è diventato rosso appena ho scritto
    # la chiave nuova — ed è la ragione per cui quel test esiste.
    "libero_mb", "dichiarati_mb",
    # 09/08 — `name`: l'artefatto NotebookLM chiesto in download
    # (/admin/nlm/artifact/{name}). Serve, perché «chi ha scaricato COSA» è l'unica
    # domanda utile su un endpoint che fa USCIRE dati dal container che tiene i cookie.
    # ⚠️ È il path param GREZZO, non un nome già ripulito — e ci va di proposito: la
    #    normalizzazione (`safe_artifact_name`) avviene DOPO, dentro nb1777-mcp, e un
    #    audit che registrasse il nome ripulito direbbe cosa è stato SERVITO invece di
    #    cosa è stato CHIESTO. Se qualcuno prova `../../etc/passwd`, l'audit deve
    #    contenere quello, non `passwd`. Il valore è comunque troncato da `_redigi`
    #    (_MAX_VALORE), e chi legge i log sa che questa chiave viene da fuori.
    #    *Prima riga scritta qui: «nome già normalizzato da nb1777-mcp» — FALSA sul mio
    #    stesso codice, e in un ledger di sicurezza un commento falso è peggio di
    #    nessun commento: dice al lettore che il valore è ristretto quando non lo è.
    #    Trovata rileggendo dopo il rilievo di abdd732a sulla #130 («viene da FUORI»).*
    # **Aggiunta perché il presidio mi ha fermata**: la CI è diventata rossa appena ho
    # scritto la chiave nuova, esattamente come per `libero_mb` qui sopra. *Due volte lo
    # stesso test ferma due persone diverse allo stesso punto: è quello che deve fare.*
    "name",
    # 07/09 — `ruolo`: il valore scritto in `meta['ruolo']` di un archivio
    # (#278, /internal/archive/ruolo). Va nell'audit per intero e non troncato a
    # un `len`, come si fa per la `description`: lì il valore è testo libero e
    # nel log serve sapere QUANTO, qui è una parola di un vocabolario chiuso e
    # serve sapere QUALE — «chi ha promosso quale DB a primario» è l'unica
    # domanda utile su questo canale, e un conteggio di caratteri non la
    # risponde. **Terza volta che questo presidio ferma qualcuno alla stessa
    # riga** (dopo `libero_mb` e `name`): rosso appena scritta la chiave nuova.
    "ruolo",
    # 05/10 — `tool`, `ms`, `esito` della riga `proxy_tool` (S11, proxy.py). `tool` è
    # `params.name` del JSON-RPC, troncato a 80 caratteri: un nome scelto dal client, non
    # un argomento (gli argomenti non escono mai dal corpo). `ms` è misurato da noi; `esito`
    # è di un vocabolario chiuso (ok, errore_tool, timeout, interrotto, errore_stream, 502).
    # Quarta volta che questo presidio ferma qualcuno alla stessa riga.
    "tool", "ms", "esito",
    # 11/10 — P18: `giorni` del posticipo del promemoria dei secret (un intero, 0-30).
    "giorni",
    # 11/10 — P16: `lavoro`, l'id di un file messo in coda da /admin/archive (data e 8
    # caratteri esadecimali, app/coda_ingest.py: nessun dato dell'owner).
    "lavoro",
})
_MAX_VALORE = 500


def _redigi(event: dict[str, Any]) -> dict[str, Any]:
    """Chiavi ignote → il valore non si scrive (la CHIAVE resta, o si nasconde il buco).

    Tenere la chiave e togliere il valore è deliberato: un campo sparito è invisibile a chi
    legge il log, un campo `<non dichiarata>` dice che qualcuno ha provato a scrivere lì.
    """
    out: dict[str, Any] = {}
    for k, v in event.items():
        if k not in _CHIAVI_NOTE:
            out[k] = "<valore non scritto: chiave non dichiarata>"
            continue
        if isinstance(v, str) and len(v) > _MAX_VALORE:
            out[k] = v[:_MAX_VALORE] + f"…(+{len(v) - _MAX_VALORE} caratteri troncati)"
        else:
            out[k] = v
    return out


def audit(event: dict[str, Any]) -> None:
    """Append evento al log JSONL. Non solleva mai eccezioni — ma non è più MUTO."""
    global _write_failures, _last_error, _last_failure_ts, _next_prune_at

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        s = _settings()
        path = Path(s.audit_log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        freno = _da_sopprimere(event.get("event"), now)
        if freno is True:
            return                      # contato: esce nel riepilogo del minuto
        record = {"ts": now, **_redigi(event)}
        with path.open("a", encoding="utf-8") as fh:
            if isinstance(freno, dict):
                fh.write(json.dumps({"ts": now, **freno}, ensure_ascii=False) + "\n")
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001 — mai bloccare la response per un audit fail
        _write_failures += 1
        _last_error = f"{type(exc).__name__}: {exc}"
        _last_failure_ts = now
        # il canale che resta quando il file non è scrivibile: i log del container.
        log.warning("audit: scrittura FALLITA (%d dall'ultimo successo): %s",
                    _write_failures, _last_error)
        return

    # La scrittura è passata. Se veniva da una serie di fallimenti, la serie va
    # dichiarata NEL log — è lì che guarda chi indaga, non nei contatori in RAM.
    if _write_failures:
        dropped, err = _write_failures, _last_error
        _write_failures, _last_error, _last_failure_ts = 0, "", ""
        try:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(
                    {"ts": now, "event": "audit_write_recovered",
                     "dropped": dropped, "last_error": err},
                    ensure_ascii=False) + "\n")
        except OSError as exc:
            log.warning("audit: record di ripristino non scritto: %s", exc)

    # potatura opportunistica: solo quando il file è grande (raro) e solo se è
    # ricresciuto dall'ultima volta (vedi _PRUNE_GROWTH).
    try:
        size = path.stat().st_size
        if size > _next_prune_at:
            _prune(path, s.audit_retention_days)
            dopo = path.stat().st_size
            _next_prune_at = max(_PRUNE_SIZE, dopo + max(_PRUNE_GROWTH, dopo // 2))
    except (OSError, ValueError, TypeError) as exc:
        log.warning("audit: potatura fallita: %s", exc)


def _tail_lines(path: Path, limit: int) -> list[str]:
    """Ultime `limit` righe di `path`, risalendo dalla CODA a blocchi.

    Non carica mai più di `_TAIL_MAX_BYTES` (né più di quanto serva a trovare
    `limit` a-capo). Il primo blocco letto — cioè il più VECCHIO — comincia quasi
    sempre a metà riga: quella riga parziale si scarta, a meno di essere arrivati
    all'inizio del file.
    """
    with path.open("rb") as fh:
        fh.seek(0, os.SEEK_END)
        pos = fh.tell()
        chunks: list[bytes] = []
        newlines = 0
        read = 0
        while pos > 0 and newlines <= limit and read < _TAIL_MAX_BYTES:
            step = min(_TAIL_BLOCK, pos)
            pos -= step
            fh.seek(pos)
            block = fh.read(step)
            chunks.append(block)
            newlines += block.count(b"\n")
            read += step
        data = b"".join(reversed(chunks))

    lines = data.decode("utf-8", errors="replace").splitlines()
    if pos > 0 and lines:
        lines = lines[1:]  # riga tagliata a metà dal blocco più vecchio
    return lines[-limit:]


def leggi_recenti(limit: int = 200) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Gli ultimi N eventi e COSA non si è potuto leggere: `{"scartate": n, "illeggibile": str}`.

    «Nessun evento» e «il file non si legge» sono risposte diverse, e così «200 eventi» e «200
    eventi più 3 righe rotte»: chi mostra l'audit le deve poter dire (prima le righe corrotte si
    saltavano e un file illeggibile diventava una lista vuota, senza traccia).
    `limit` è clampato a MAX_READ_LIMIT: nessun chiamante (né un `?n=` in query string) può
    trasformare questa funzione in "carica tutto il file".
    """
    stato: dict[str, Any] = {"scartate": 0, "illeggibile": ""}
    try:
        limit = max(0, min(int(limit), MAX_READ_LIMIT))
    except (TypeError, ValueError):
        limit = 200
    if not limit:
        return [], stato

    path = Path(_settings().audit_log_path)
    events: list[dict[str, Any]] = []
    try:
        for line in _tail_lines(path, limit):
            line = line.strip()
            if not line:
                continue
            try:
                riga = json.loads(line)
            except json.JSONDecodeError:
                stato["scartate"] += 1
                continue
            if isinstance(riga, dict):
                events.append(riga)
            else:
                stato["scartate"] += 1
    except FileNotFoundError:   # nessun evento ancora scritto: non è un errore
        pass
    except OSError as exc:      # c'è ma non si legge: si dice, mai un'eccezione
        stato["illeggibile"] = f"{type(exc).__name__}: {exc}"
        log.warning("audit: lettura FALLITA: %s", stato["illeggibile"])
    return events, stato


def read_recent(limit: int = 200) -> list[dict[str, Any]]:
    """Solo gli eventi di `leggi_recenti` (per chi non mostra lo stato della lettura)."""
    return leggi_recenti(limit)[0]
