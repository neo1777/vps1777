"""Un campo di config con default VUOTO che governa un controllo va DICHIARATO.

Nasce dalla voce `691d6fea` (`71d540e6`, 02/08): *«se il dato manca, il controllo non
scatta»* — sei istanze misurate su sei oggetti diversi, e la conclusione fu che **non
sono sei difetti: è una regola di progetto che manca.**

    la forma:  `if <dato> and <condizione>: rifiuta`
    quando <dato> è vuoto il ramo di rifiuto NON viene mai preso, e il sistema PASSA.
    Nessuno se ne accorge perché l'esito è «riuscito», non «errore».

🔴 **E il punto che vale non è il grep**: quella lente produce ~57 match di cui ~51
   legittimi, quindi come gate bloccante sarebbe rumore. Il punto è **la coerenza**, e
   sta in due righe CONSECUTIVE dello stesso file:

       oauth_allowed_emails: CSVList = Field(default_factory=list)          ← vuoto
       oauth_cors_origins:   CSVList = Field(default_factory=lambda: [...]) ← sicuro

   *Due campi vicini, due filosofie opposte, nessuna delle due dichiarata.* Il secondo
   è stato scelto; il primo probabilmente è nato così. **Non si distinguono guardando.**

🛡️ **COSA FA QUESTO TEST, e cosa NON fa.** Non giudica se un default è giusto: giudicare
   richiede il contesto d'uso, ed è il lavoro che ha ridimensionato il rilievo su
   `oauth_allowed_emails` da difetto a nota (con la lista vuota il login è comunque
   bloccato da `admin_email == ""`, verificato). **Obbliga a DIRE quale scelta è stata
   fatta.** Un campo nuovo con default permissivo, aggiunto fra un anno da chi non ha
   letto questa voce, diventa rosso finché qualcuno non scrive la ragione.

⚠️ Legge `settings.py` con `ast`, senza importarlo: la CI esegue questa suite con
   dipendenze installate, ma un test che dipende da pydantic per leggere una scelta di
   progetto si rompe per un motivo che non c'entra con ciò che verifica.
"""
from __future__ import annotations

import ast
from pathlib import Path

SETTINGS = Path(__file__).resolve().parents[1] / "app" / "settings.py"

# I campi con default VUOTO che governano (o possono governare) un controllo, e la
# ragione per cui il vuoto è accettabile. ⚠️ La ragione NON è decorativa: è ciò che
# distingue «scelto» da «nato così», e senza di essa i due casi si assomigliano.
DEFAULT_VUOTO_DICHIARATI: dict[str, str] = {
    "gateway_upstreams": (
        "Vuoto = nessun upstream da instradare, e il vuoto FALLISCE CHIUSO: "
        "mcp_client.py:40 fa `s.gateway_upstreams.get(service)` ⇒ con il dict vuoto "
        "il servizio non si trova e la richiesta non parte. Non è un controllo che si "
        "disattiva: è una tabella di routing che non ha voci. "
        "⇒ Dichiarato per DISTINGUERLO dagli altri, non perché sia un rischio: la "
        "lente `691d6fea` cerca i default vuoti che DISATTIVANO un controllo, e questo "
        "è il caso opposto. Senza la riga, il prossimo che legge l'elenco non saprebbe "
        "che qualcuno l'ha già guardato e ha concluso che va bene."
    ),
    "oauth_allowed_emails": (
        "Vuoto = nessun vincolo sul legame token→proprietario in proxy.py:83. "
        "ACCETTATO e non curato, con la misura accanto: con la lista vuota "
        "`admin_email` torna '' (settings.py:240) e admin.py rifiuta ogni email "
        "diversa da '' ⇒ nessun token nuovo può nascere, e tutti e tre gli installer "
        "chiedono ADMIN_EMAIL come obbligatoria. Resta una finestra teorica: token già "
        "emessi che sopravvivono a uno svuotamento successivo della config. "
        "⇒ NOTA, non rilievo — e la nota sta qui perché il prossimo che legge quella "
        "riga non debba rifare la misura per scoprire che era già stata fatta."
    ),
}


def _campi_con_default_vuoto() -> dict[str, str]:
    """I campi di `Settings` il cui default è una collezione vuota.

    Riconosce le due forme che il file usa: `Field(default_factory=list)` e
    l'annotazione con `= []`. Volutamente NON riconosce
    `Field(default_factory=lambda: [...])` — quello è un default POPOLATO, cioè una
    scelta già visibile a chi legge.
    """
    albero = ast.parse(SETTINGS.read_text(encoding="utf-8"), filename=str(SETTINGS))
    # 🔴 SOLO I CAMPI DELLA CLASSE, non le costanti di modulo. La prima versione usava
    #   `ast.walk` sul file intero e prendeva `UPSTREAMS_SCARTATI` — che è un
    #   ACCUMULATORE di diagnostica (le voci di GATEWAY_UPSTREAMS scartate dal parser),
    #   non una configurazione. *Un rilevatore che chiede di dichiarare una variabile
    #   di lavoro riempie l'elenco di righe inutili, e un elenco pieno di rumore
    #   smette di essere letto — cioè si disattiva da solo.*
    classe = next((n for n in albero.body
                   if isinstance(n, ast.ClassDef) and n.name == "Settings"), None)
    assert classe is not None, (
        "classe Settings non trovata in settings.py — non è «nessun campo», è che "
        "questo test sta leggendo un file che non conosce più"
    )
    trovati: dict[str, str] = {}
    for nodo in classe.body:
        if not isinstance(nodo, ast.AnnAssign) or not isinstance(nodo.target, ast.Name):
            continue
        nome = nodo.target.id
        v = nodo.value
        if v is None:
            continue
        # `= []` oppure `= set()`
        if isinstance(v, ast.List) and not v.elts:
            trovati[nome] = "lista vuota letterale"
        # `Field(default_factory=list)` — la factory è un NOME, non una lambda
        elif isinstance(v, ast.Call) and getattr(v.func, "id", "") == "Field":
            for kw in v.keywords:
                if kw.arg == "default_factory" and isinstance(kw.value, ast.Name):
                    if kw.value.id in ("list", "set", "dict"):
                        trovati[nome] = f"Field(default_factory={kw.value.id})"
    return trovati


def test_ogni_default_vuoto_e_dichiarato_con_la_sua_ragione():
    trovati = _campi_con_default_vuoto()
    assert trovati, (
        "nessun campo con default vuoto trovato in settings.py — non è «sono tutti "
        "sicuri», è che questo test non sta più leggendo ciò che crede (il file è "
        "cambiato struttura, o l'annotazione non è più AnnAssign)"
    )
    non_dichiarati = {n: c for n, c in trovati.items() if n not in DEFAULT_VUOTO_DICHIARATI}
    assert not non_dichiarati, (
        f"campi con default VUOTO non dichiarati: {sorted(non_dichiarati)}.\n"
        f"    Un default vuoto che governa un controllo lo DISATTIVA in silenzio: la "
        f"forma `if <dato> and <cond>: rifiuta` non prende mai il ramo di rifiuto, e "
        f"l'esito è «riuscito», non «errore».\n"
        f"    Questo test NON chiede di cambiare il default: chiede di DICHIARARE la "
        f"scelta in DEFAULT_VUOTO_DICHIARATI, con la misura dell'impatto accanto. "
        f"«Scelto» e «nato così» non si distinguono guardando il codice — solo "
        f"leggendo la ragione, se qualcuno l'ha scritta."
    )


def test_nessuna_dichiarazione_ORFANA():
    """Una dichiarazione per un campo che non esiste più è peggio di nessuna.

    Resta lì a rassicurare chi legge l'elenco, e nasconde che la scelta non è più in
    vigore. *È la forma del limite dichiarato che nessuno riverifica.*
    """
    trovati = _campi_con_default_vuoto()
    orfane = [n for n in DEFAULT_VUOTO_DICHIARATI if n not in trovati]
    assert not orfane, (
        f"dichiarazioni senza campo: {sorted(orfane)} — o il campo è stato rinominato "
        f"(e la ragione va spostata), o il default non è più vuoto (e la ragione va "
        f"tolta, perché descrive uno stato che non c'è più)"
    )


def test_polarita_un_campo_con_default_POPOLATO_non_viene_contato():
    """Il test sa distinguere? Si verifica sul caso che sta due righe sotto.

    `oauth_cors_origins` ha `default_factory=lambda: ["https://claude.ai"]` — un
    default SICURO. Se il rilevatore lo contasse fra i vuoti, chiederebbe di dichiarare
    una scelta già visibile, e l'elenco si riempirebbe di righe inutili finché nessuno
    lo leggerebbe più.
    """
    trovati = _campi_con_default_vuoto()
    assert "oauth_cors_origins" not in trovati, (
        "oauth_cors_origins ha un default POPOLATO (lambda con una lista non vuota) ed "
        "è stato contato fra i vuoti: il rilevatore non distingue una scelta fatta da "
        "un default nato così, che è l'unica cosa che questo test deve saper fare"
    )
