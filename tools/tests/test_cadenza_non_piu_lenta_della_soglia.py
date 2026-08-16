"""La cadenza di un controllo non può essere più lenta della soglia più stretta che verifica.

Il difetto che questo test esiste per fermare è stato misurato il 03/08 (rilievo
`5717df4e` del round-16, verificato da `71d540e6`):

    COSIGN_BYPASS_MAX_DAYS = 1        «la via d'emergenza cosign è scaduta» dopo 1 giorno
    vps1777-secrets-check.timer        OnCalendar=weekly
    ⇒ fino a SEI GIORNI fra «è scaduto» e «qualcuno te lo dice»

⭐ E il punto non è il ritardo: è che per quella voce si era scelto **deliberatamente**
il promemoria al posto dell'enforcement — *«qui si ALZA LA VOCE, non si gira la
chiave»*, perché un ri-armo automatico chiuderebbe fuori chi sta riparando. Ma la
voce arrivava sette volte più lentamente della sua soglia: **rinunciare
all'enforcement senza avere il promemoria.**

🔑 La causa non è distrazione, ed è la parte che vale oltre questo repo: il commento
del timer diceva *«i secret invecchiano lentamente → cadenza settimanale»* — vero per
il contenuto di allora. Poi dentro quel controllo è entrata una voce con una scala
30-180 volte più corta, e **la cadenza non l'ha seguita**. *Il presidio segue la forma
del dato di quando è nato, non di quello che ospita adesso.*

⚠️ Perché legge i file come TESTO invece di importare `vps1777`: la CI esegue questa
suite con `uvx pytest` (`ci.yml:164`), senza dipendenze installate. Un import che
tirasse dentro qualcosa di non-stdlib non darebbe rosso sul merito — **romperebbe la
RACCOLTA**, portandosi dietro gli altri test del job, e una suite che non raccoglie un
test è verde.
"""
import re
from pathlib import Path

RADICE = Path(__file__).resolve().parents[2]
TIMER = RADICE / "systemd" / "vps1777-secrets-check.timer"
CLI = RADICE / "tools" / "vps1777.py"

# Quanto dura, in giorni, ogni cadenza che systemd accetta qui. Volutamente
# incompleto: se domani qualcuno scrive `OnCalendar=Mon *-*-* 04:00:00`, il test
# NON deve indovinare — deve dire che non sa, ed è il ramo esplicito più sotto.
GIORNI_PER_CADENZA = {"hourly": 1 / 24, "daily": 1, "weekly": 7, "monthly": 30}


def _cadenza_giorni():
    testo = TIMER.read_text(encoding="utf-8")
    # Solo la direttiva vera: le righe di commento raccontano la cadenza VECCHIA e
    # la nominano per esteso. È lo stesso difetto trovato lo stesso giorno nel
    # presidio degli installer — un controllo cieco perché la cura, spiegandosi,
    # scrive la stringa che il controllo cerca.
    righe = [r.strip() for r in testo.splitlines() if not r.strip().startswith("#")]
    for r in righe:
        m = re.match(r"^OnCalendar=(.+)$", r)
        if m:
            return m.group(1).strip()
    return None


def _soglia_minima_giorni():
    """La soglia più stretta fra quelle che `secrets-status` verifica."""
    testo = CLI.read_text(encoding="utf-8")
    soglie = []
    for nome in ("COSIGN_BYPASS_MAX_DAYS", "NLM_COOKIE_MAX_DAYS"):
        m = re.search(rf"^{nome}\s*=\s*(\d+)", testo, re.M)
        if m:
            soglie.append((nome, int(m.group(1))))
    # Le voci di _SECRET_POLICY: quarto campo di ogni tupla.
    for m in re.finditer(r'\(\s*"[a-z_]+",\s*"[^"]+",\s*"[^"]+",\s*(\d+),', testo):
        soglie.append(("_SECRET_POLICY", int(m.group(1))))
    assert soglie, (
        "nessuna soglia trovata in vps1777.py — il test sta leggendo un file che non "
        "conosce, e un elenco vuoto NON è 'nessuna soglia da rispettare'"
    )
    return min(soglie, key=lambda s: s[1])


def test_la_cadenza_del_check_non_e_piu_lenta_della_soglia_piu_stretta():
    cadenza = _cadenza_giorni()
    assert cadenza is not None, f"nessun OnCalendar in {TIMER.name}"
    assert cadenza in GIORNI_PER_CADENZA, (
        f"cadenza «{cadenza}» che questo test non sa convertire in giorni. NON la "
        f"indovina: aggiungila a GIORNI_PER_CADENZA con il suo valore, o il presidio "
        f"passerebbe senza aver confrontato niente."
    )
    nome_soglia, giorni_soglia = _soglia_minima_giorni()
    giorni_cadenza = GIORNI_PER_CADENZA[cadenza]
    assert giorni_cadenza <= giorni_soglia, (
        f"il check gira «{cadenza}» ({giorni_cadenza}g) ma la soglia più stretta che "
        f"verifica è {nome_soglia} = {giorni_soglia}g ⇒ fino a "
        f"{giorni_cadenza - giorni_soglia:g} giorni fra «è scaduto» e «qualcuno lo "
        f"dice». Se la soglia è giusta, la cadenza va stretta; se è la cadenza a "
        f"essere giusta, allora quella voce non appartiene a questo controllo."
    )


def test_polarita_una_cadenza_troppo_lenta_verrebbe_PRESA():
    """Il test sa dire di no? Si ricostruisce il confronto sul caso che è successo.

    Senza questa, «passa» e «non ha guardato niente» sono lo stesso risultato — ed è
    esattamente com'era il presidio prima: `weekly` contro una soglia di 1 giorno
    passava, perché nessuno faceva il confronto.
    """
    _, giorni_soglia = _soglia_minima_giorni()
    assert GIORNI_PER_CADENZA["weekly"] > giorni_soglia, (
        "con le soglie attuali nemmeno 'weekly' risulterebbe troppo lento: il "
        "confronto non sta misurando ciò che crede"
    )


def test_le_soglie_si_leggono_davvero_e_la_piu_stretta_e_quella_del_bypass_cosign():
    """Ancora il valore, non solo la relazione: se domani qualcuno alza
    COSIGN_BYPASS_MAX_DAYS per far passare il test invece di stringere la cadenza,
    questo test lo dice — e quella sarebbe la cura girata dalla parte sbagliata."""
    nome, giorni = _soglia_minima_giorni()
    assert nome == "COSIGN_BYPASS_MAX_DAYS", (
        f"la soglia più stretta è {nome} ({giorni}g), non più il bypass cosign. Non è "
        f"un errore di per sé — ma la cadenza del timer è tarata su quella, quindi va "
        f"riconsiderata insieme."
    )
    assert giorni == 1, (
        f"COSIGN_BYPASS_MAX_DAYS è {giorni}, era 1. Una via d'emergenza che scade più "
        f"tardi è una scelta legittima, e va presa guardando anche la cadenza qui "
        f"sopra — non alzata per far tacere un test."
    )
