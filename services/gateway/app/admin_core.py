"""Revoke-list dei `jti` — pura stdlib, zero dipendenze di terze parti.

Isolata qui (fuori da admin.py, che importa starlette, e fuori da jwt_helpers.py,
che importa PyJWT) così è importabile e testabile stdlib-only, come miniapp_core /
ratelimit / logredact: la CI gira i test del gateway con `uvx pytest` senza
installare le deps pesanti.

PERCHÉ (H20). Il cookie admin è un JWT verificato *stateless*: finché la firma
regge e `exp` non è passato, VALE — anche dopo il logout, che lato server non
faceva nulla (cancellava il cookie nel browser). Un token rubato restava quindi
buono fino a 8h. Con un `jti` per token e questa lista, il logout REVOCA davvero:
`verify_admin_cookie` rifiuta un jti revocato, e la revoca sopravvive ai restart
perché sta su disco.

È la gemella della revoke-list dei refresh OAuth (oauth.py → `oauth_revoked.json`,
`_revoked_refresh`), con una differenza deliberata: qui ogni voce porta la propria
SCADENZA. Un jti conta solo finché il token non sarebbe scaduto da sé — dopo, la
verifica JWT lo rifiuta comunque per `exp` e tenerne memoria non aggiunge
sicurezza, solo byte. Quindi si pota: la lista non cresce all'infinito.
"""
from __future__ import annotations

import calendar
import json
import os
import tempfile
import time
from pathlib import Path


def prune(entries: dict[str, float], now: float) -> dict[str, float]:
    """Toglie le voci già scadute (`exp <= now`): il loro token è morto da sé."""
    return {jti: exp for jti, exp in entries.items() if exp > now}


class RevocationList:
    """`jti` revocati → epoch di scadenza del token. Persistita su JSON.

    Best-effort come la gemella OAuth: se il disco non è scrivibile la revoca
    resta in memoria (vale per questo processo) e `revoke()` ritorna False, così
    il chiamante può auditarlo invece di crederla durevole.

    Il file viene ri-letto quando cambia l'mtime: la lista resta corretta anche
    se un domani il gateway girasse con più worker (oggi è un processo solo).
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._entries: dict[str, float] = {}
        self._mtime: float = -1.0
        self.reload()

    # ───── I/O ─────

    def _stat_mtime(self) -> float:
        try:
            return self._path.stat().st_mtime
        except OSError:
            return -1.0

    def _read(self) -> dict[str, float]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(raw, dict):
            return {}
        out: dict[str, float] = {}
        for jti, exp in raw.items():
            try:
                out[str(jti)] = float(exp)
            except (TypeError, ValueError):
                continue  # voce corrotta: si scarta quella, non il file
        return out

    def reload(self, now: float | None = None) -> None:
        """Rilegge il file da zero (e pota)."""
        self._entries = prune(self._read(), time.time() if now is None else now)
        self._mtime = self._stat_mtime()

    def _sync(self, now: float | None = None) -> None:
        """Ricarica solo se il file è cambiato sotto di noi (stat, non read)."""
        if self._stat_mtime() != self._mtime:
            self.reload(now)

    def save(self) -> bool:
        """Scrive in modo atomico (tmp + replace): un crash a metà non lascia un
        JSON troncato — che, essendo illeggibile, farebbe *dimenticare* le revoche."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(self._path.parent),
                                       prefix=".revoked-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(self._entries, fh)
                os.chmod(tmp, 0o600)
                os.replace(tmp, self._path)
            except OSError:
                os.unlink(tmp)
                raise
        except OSError:
            return False
        self._mtime = self._stat_mtime()
        return True

    # ───── API ─────

    def revoke(self, jti: str, expires_at: float, now: float | None = None) -> bool:
        """Revoca `jti` fino alla scadenza del token. True se persistita su disco."""
        if not jti:
            return False
        now = time.time() if now is None else now
        self._sync(now)
        self._entries = prune(self._entries, now)
        self._entries[str(jti)] = float(expires_at)
        return self.save()

    def is_revoked(self, jti: str, now: float | None = None) -> bool:
        if not jti:
            return False
        self._sync(now)
        return str(jti) in self._entries

    def __len__(self) -> int:
        return len(self._entries)


# ───── il `next` del login: relativo vero o same-origin, niente altro (H30) ─────
# Sta QUI, e non in admin.py, perché admin.py importa starlette e la CI non può
# testarlo. Un bypass di open-redirect è tornato una volta in un rilievo che
# risultava CHIUSO: senza test, tornerà ancora.

def safe_next_url(next_url: str, public_base: str, fallback: str = "/admin/setup") -> str:
    """
    Ritorna `next_url` se è un redirect lecito, altrimenti `fallback`.

    Lecito = path relativo VERO, oppure stessa ORIGINE di public_base.

    Le tre trappole, tutte incontrate sul campo:
    - `//evil.com` e `/\\evil.com` cominciano per "/" ma sono protocol-relative:
      il browser li manda FUORI.
    - `startswith(base)` è un match di PREFISSO, non di ORIGINE: con base
      `https://host`, l'URL `https://host.evil.com/` lo supera. Dopo la base ci
      DEVE essere la fine dell'URL o un separatore (`/`, `?`, `#`).
    - I browser CANCELLANO tab/CR/LF dagli URL: `/\\t/evil.com` ridiventa
      `//evil.com` DOPO il nostro controllo. Un `next` con caratteri di controllo
      non è comunque un URL lecito.
    """
    if not next_url:
        return fallback
    if any(ord(c) < 0x20 or ord(c) == 0x7f for c in next_url):
        return fallback
    if next_url.startswith("/") and not next_url.startswith(("//", "/\\")):
        return next_url
    base = (public_base or "").rstrip("/")
    if base and next_url.startswith(base):
        rest = next_url[len(base):]
        if rest == "" or rest[0] in "/?#":
            return next_url
    return fallback


def ore_da(iso_utc: str, now: float | None = None) -> int | None:
    """Ore intere trascorse da un timestamp «%Y-%m-%dT%H:%M:%SZ», o None.

    Sta qui e non in admin.py per la ragione dichiarata in testa a questo modulo:
    in admin.py non sarebbe testabile (la CI gira i test stdlib-only, admin.py
    importa starlette e pydantic) — e una logica che decide COSA LEGGE L'UTENTE
    non può stare dove nessun test la guarda.

    `None` è un TERZO stato e non va confuso con zero: «non so quando è stato
    controllato» ha un rimedio diverso da «è appena stato controllato», e chi
    chiama deve poterli distinguere. È il motivo per cui il fallimento non
    ritorna 0 — che si leggerebbe come «adesso».

    Un istante nel futuro (orologi non allineati fra host e container) dà 0, mai
    un numero negativo: «-3 ore fa» in una pagina è un difetto che si nota, ma
    ci si arriva solo in produzione.
    """
    try:
        t = time.strptime(str(iso_utc), "%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError):
        return None
    return max(0, int(((now if now is not None else time.time()) - calendar.timegm(t)) // 3600))


# Soglia oltre la quale «l'avviso è vecchio» diventa «il controllo non sta
# girando». NON è un numero scelto a occhio: viene da systemd/vps1777-check-
# update.timer, che dichiara `OnCalendar=daily` + `RandomizedDelaySec=4h` ⇒
# l'intervallo MASSIMO LEGITTIMO fra due controlli è 24+4 = 28h. 30 aggiunge un
# margine per `Persistent=true`, che dopo un riavvio recupera un giro saltato.
#
# 🔴 La prima versione aveva 26 e fabbricava un falso allarme su un timer SANO
# (misurato sulla VPS: LAST 02:25 → NEXT 00:20 = 21h55m, il delay varia davvero).
# Un presidio che grida quando non c'è niente è quello che si impara a ignorare:
# è il modo più affidabile di disattivarne uno. Trovato da abdd732a leggendo
# l'unità, non il codice.
#
# ⚠️ Se qualcuno cambia `RandomizedDelaySec` nel .timer, questa soglia va rivista:
# il numero vive qui, la sua ragione vive in un file che nessuno rilegge. Il test
# `test_soglia_stale_copre_il_ritardo_massimo_del_timer` lega i due valori, così
# la traccia non si perde.
CHECK_TIMER_MAX_H = 28          # daily (24h) + RandomizedDelaySec (4h)
CHECK_STALE_H = 30


def stato_dopo_refresh_fallito(prev: dict, spiega: str, dettaglio: str,
                               now_iso: str) -> dict:
    """Cosa scrive il gateway in update_status.json quando il SUO refresh fallisce.

    Il refresh dal gateway è best-effort e dal fix H50 fallisce PER PROGETTO
    (niente egress): quel fallimento non è un check avvenuto. La prima versione
    scriveva `error` + `checked_at=now` nello stesso file del check host — e
    siccome `classe_verdetto_update` fa vincere errore-check su tutto, un
    «aggiornamento disponibile» fresco e valido spariva dalla card al primo
    Ricontrolla (misurato al collaudo vergine, 27/08: il bottone update c'era,
    un refresh dopo non c'era più — H70). Doppio danno: ri-datare `checked_at`
    su un check MAI avvenuto azzerava anche l'anti-stantio (timer-fermo).

    Qui: campi separati (`refresh_error`/`refresh_error_at`), il verdetto del
    check host — `error`, `checked_at`, `latest` — resta suo. Sta in admin_core
    per la stessa ragione di classe_verdetto_update: in admin.py nessun test
    stdlib-only la guarderebbe."""
    out = dict(prev)
    out["refresh_error"] = spiega + dettaglio
    out["refresh_error_at"] = now_iso
    return out


def classe_verdetto_update(current: str, latest: str | None, checked_at: str,
                           error: str | None, now: float | None = None,
                           piu_recente=None) -> tuple[str, int | None]:
    """Quale VERDETTO mostra la card degli aggiornamenti, e con che età.

    Restituisce (classe, ore) — la resa HTML resta in admin.py, la DECISIONE sta
    qui perché in admin.py nessun test la guarderebbe (starlette+pydantic: la CI
    gira i test stdlib-only). Misurato il 26/07: zero test nominavano
    update_check/update_status/_fetch in tutto il repo, cioè il ramo che l'utente
    legge a ogni visita non era coperto da niente.

    `piu_recente(a, b)` è iniettato (in produzione: version_gt) per non tirare
    dentro un altro modulo: il confronto è SEMPRE per versione e mai `!=`, perché
    /releases/latest può servire una risposta stantia dalla cache di GitHub e un
    `!=` proporrebbe un downgrade.

    Le classi, e perché sono distinte:
      errore-check          il check è fallito: il dato è stantio e si sa perché
      aggiornamento         c'è una versione più nuova
      latest-piu-vecchia    GitHub ha risposto con una release più VECCHIA della
                            corrente (cache stantia): non è un aggiornamento
      aggiornato            sei all'ultima, e l'età del controllo sta nel range
      timer-fermo           sei all'ultima SECONDO un controllo più vecchio del
                            suo stesso ciclo ⇒ il problema non è il dato, è che
                            il controllo potrebbe non girare più: rimedio diverso
      data-illeggibile      non si sa QUANDO è stato controllato (≠ «adesso»)
      mai-controllato       non è mai girato
    """
    if error:
        return ("errore-check", None)
    cmp_ = piu_recente or (lambda a, b: str(a) > str(b))
    if latest and cmp_(str(latest), current):
        # L'ETÀ SERVE QUI PIÙ CHE ALTROVE, e la prima versione non la dava.
        # Trovato dall'artefatto del round-6 (27/07): avevo messo il perimetro sul
        # ramo tranquillo («sei aggiornato — controllato N ore fa») e non su quello
        # che porta a un'AZIONE. Ma è qui che l'operatore preme «aggiorna» su un
        # dato che può avere fino a 28h: nel frattempo può essere uscita una
        # versione più nuova, o quella release può essere stata ritirata.
        # Un'asimmetria che dava il contesto dove non decide nulla e lo toglieva
        # dove decide.
        return ("aggiornamento", ore_da(checked_at, now=now))
    if latest and str(latest) != current:
        return ("latest-piu-vecchia", None)
    if not latest:
        return ("mai-controllato", None)
    ore = ore_da(checked_at, now=now)
    if ore is None:
        return ("data-illeggibile", None)
    return ("timer-fermo" if ore >= CHECK_STALE_H else "aggiornato", ore)


def testo_verdetto_update(classe: str, ore: int | None, current: str,
                          latest: str | None, errore: str | None) -> str:
    """Il TESTO che l'operatore legge nella card aggiornamenti. Niente HTML.

    Sta qui e non in admin.py per la ragione che l'artefatto del round-6 ha
    formulato meglio di noi: «applica prima il rimedio di COPERTURA, poi quello
    di INTERFACCIA — se inverti, scrivi una frase corretta che sfuggirebbe
    comunque ai test». Stanotte abbiamo fatto esattamente l'errore descritto:
    corretto il tempo del verbo («al controllo di N ore fa ERI…» invece di «SEI»)
    dentro admin.py, che i test non attraversano — misurato allo 0% con
    sys.settrace. La logica era presidiata, la frase no: il difetto poteva
    tornare il giorno dopo e nessun controllo se ne sarebbe accorto.

    Le regole che queste stringhe DEVONO rispettare, e che ora un test può
    pretendere invece di sperarci:
      · un verdetto sul mondo esterno sta al PASSATO e porta la propria età —
        datare una frase non la rende condizionale, lo fa il tempo del verbo;
      · il ramo che porta a un'AZIONE (c'è un aggiornamento) porta l'età come e
        più degli altri: è lì che si preme il pulsante;
      · «non so quando» non si scrive mai come «adesso».
    """
    if classe == "errore-check":
        return (f"Ultimo check fallito ({errore}) — dato stantio.")
    if classe == "aggiornamento":
        eta = (f" — rilevato da un controllo di {ore} ore fa" if ore is not None
               else " — data del controllo non leggibile")
        return f"Aggiornamento disponibile: v{latest} (sei alla {current}){eta}."
    if classe == "latest-piu-vecchia":
        return (f"Sei alla v{current} — l'ultima release nota (v{latest}) è più "
                "vecchia: check stantio, nessun aggiornamento.")
    if classe == "data-illeggibile":
        return ("All'ultimo controllo eri alla versione più recente "
                "(quando sia stato fatto, non è leggibile).")
    if classe == "timer-fermo":
        return (f"Ultimo controllo {ore} ore fa, più del ciclo giornaliero: il "
                "controllo automatico potrebbe non essere attivo "
                "(systemctl status vps1777-check-update.timer). A quel momento "
                f"eri alla v{current}, l'ultima.")
    if classe == "aggiornato":
        return f"Al controllo di {ore} ore fa eri alla versione più recente."
    return "Nessun check ancora eseguito (il timer gira una volta al giorno)."
