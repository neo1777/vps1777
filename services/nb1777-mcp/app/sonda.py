"""La sonda viva della sessione Google (S8, 05/10/2026).

Fino alla 0.71 «stato ok» voleva dire «il file dei cookie c'è» (`profile_status`), e il
promemoria dei 14 giorni guardava una data che nlm riscrive da solo a ogni refresh. Il
02/10 la sessione è morta e ce ne siamo accorti 12,7 ore dopo, a metà di un lavoro.

Qui, ogni `NB1777_SONDA_ORE` ore (default 4; 0 = spenta), una chiamata vera e leggera
(`notebook list`) dice com'è la sessione. Si registra SOLO l'esito e l'ora, mai un
contenuto, in `nb1777-state/sonda-nlm.jsonl` sul volume (sopravvive agli update). Alla
transizione verso `auth_scaduta` parte UN avviso su Telegram, per la coda che il bot già
preleva (`memoria`); un altro quando la sessione torna. La rete giù non è un'auth scaduta
e non suona.

⚠️ Una sonda riuscita fa riscrivere a nlm il file dei cookie: la sua data di modifica non
misura più niente (lo dice anche docs/NB1777.md). L'età della sessione si legge altrove.
⚠️ Non sta in /health: un health che dipende da Google riavvierebbe il container per i
guasti degli altri.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from . import core, memoria
from .settings import get_settings

log = logging.getLogger(__name__)

_RIGHE_MAX = 500            # ~80 giorni a una sonda ogni 4 ore
_PRIMA_DOPO_S = 300         # la prima sonda 5 minuti dopo l'avvio, non durante
_LOCK = threading.Lock()


def _dir_stato() -> Path:
    return Path(get_settings().nlm_home) / "nb1777-state"


def _registro() -> Path:
    return _dir_stato() / "sonda-nlm.jsonl"


def ultimo() -> dict | None:
    """L'ultimo esito registrato, {quando, esito}, o None se la sonda non ha mai girato."""
    try:
        righe = _registro().read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for riga in reversed(righe):
        try:
            return json.loads(riga)
        except ValueError:
            continue
    return None


def _registra(voce: dict) -> None:
    p = _registro()
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        righe = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        righe = []
    righe = (righe + [json.dumps(voce, ensure_ascii=False)])[-_RIGHE_MAX:]
    tmp = p.with_suffix(".tmp")
    tmp.write_text("\n".join(righe) + "\n", encoding="utf-8")
    tmp.replace(p)


def quota_usata() -> float | None:
    """La percentuale usata della finestra più piena (`nlm usage`), o None se non si legge."""
    try:
        finestre = core.usage_get().get("windows") or []
        usate = [float(f["percent_used"]) for f in finestre
                 if isinstance(f, dict) and f.get("percent_used") is not None]
    except Exception:                              # noqa: BLE001 — la sonda non deve morire
        return None
    return max(usate) if usate else None


def sonda_una_volta() -> dict:
    """Una sonda: chiamata vera, esito classificato, registro, avviso alla transizione."""
    with _LOCK:
        prima = (ultimo() or {}).get("esito")
        try:
            core.nb_list()
            esito = "ok"
        except core.NLMAuthError:
            esito = "auth_scaduta"
        except core.NLMError as exc:
            esito = core.classifica_errore(str(exc))
            if esito == "altro" and "timeout" in str(exc).lower():
                esito = "rete"
        except Exception:                          # noqa: BLE001 — la sonda non deve morire
            esito = "altro"
        voce = {"quando": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "esito": esito}
        if esito != "auth_scaduta":
            # La quota accanto all'esito (05/10/2026): un «altro» con la quota al 100% è
            # una quota finita, non un guasto. Con la sessione scaduta non si legge.
            usata = quota_usata()
            if usata is not None:
                voce["quota_usata"] = usata
        _registra(voce)
        if esito == "auth_scaduta" and prima != "auth_scaduta":
            log.warning("sonda: sessione Google scaduta (prima: %s)", prima)
            memoria.accoda({"kind": "nlm_auth", "text": (
                "🔴 vps1777: la sessione Gemini Notebook sulla VPS è scaduta (sonda delle "
                f"{voce['quando']}).\nCura: sul PC `nlm login`, poi carica il profilo da "
                "/admin/nlm. Fino ad allora nb1777 non risponde.")})
        elif esito == "ok" and prima == "auth_scaduta":
            log.info("sonda: sessione Google tornata valida")
            memoria.accoda({"kind": "nlm_auth", "text": (
                "🟢 vps1777: la sessione Gemini Notebook sulla VPS è di nuovo valida "
                f"(sonda delle {voce['quando']}).")})
        else:
            log.info("sonda: %s", esito)
        return voce


def _giro(intervallo_s: float) -> None:
    time.sleep(_PRIMA_DOPO_S)
    while True:
        try:
            sonda_una_volta()
        except Exception as exc:                   # noqa: BLE001
            log.warning("sonda non riuscita: %s", exc)
        time.sleep(intervallo_s)


def avvia() -> bool:
    """Avvia la sonda in un thread demone. False se spenta (NB1777_SONDA_ORE=0)."""
    ore = float(get_settings().nb1777_sonda_ore)
    if ore <= 0:
        log.info("sonda della sessione spenta (NB1777_SONDA_ORE=0)")
        return False
    threading.Thread(target=_giro, args=(ore * 3600,), name="sonda-nlm", daemon=True).start()
    log.info("sonda della sessione: ogni %s ore", ore)
    return True
