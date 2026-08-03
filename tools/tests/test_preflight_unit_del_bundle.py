"""Un bundle non deve poter ANNULLARE una cura che è già sul disco.

🔓 PERCHÉ ESISTE. Il 03/08 la cura all'auto-update (#104) è entrata in `main` DOPO che
   la release 0.41.0 era già stata tagliata. La macchina è stata curata a mano — e un
   `vps1777 update` a 0.41.0, o una pressione del pulsante del pannello
   (`vps1777-update.path` → `update.service`), avrebbe reinstallato la unit del bundle
   **cancellando la cura**, in silenzio e con exit 0. L'unica difesa era ricordarsene:
   *un presidio che per essere applicato richiede un gesto umano è un presidio che nel
   giorno del guasto non esiste* (release.yml lo dice già di sé).

🔑 IL GIUDIZIO È RELATIVO, E LA PRIMA VERSIONE NON LO ERA — è la ragione per cui questo
   file esiste in questa forma. Avevo scritto il controllo come assoluto: «la unit in
   arrivo dichiara `NoNewPrivileges=no` e porta sandboxing → blocca». Misurato **prima**
   di scrivere il codice:

       unit di origin/main (curata)      -> passa    ✅ giusto
       unit di v0.40.14  (l'INSTALLATA)  -> PASSA    🔴 non dichiara NNP: il ramo salta
       unit di v0.41.0   (il BUNDLE)     -> PASSA    🔴 idem

   Cioè il controllo era **cieco proprio sul caso da cui doveva difendere**: cercavo una
   condizione che esiste solo nello stato CURATO. *Guardavo dove sono io, non da dove
   arriva il pericolo.* La domanda giusta è l'altra — **questo bundle annulla una cura
   che ho già?** — e i quattro casi qui sotto sono quelli veri.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

RADICE = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("vps1777_cli", RADICE / "tools" / "vps1777.py")
_cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cli)

# Le sei direttive che sulla VPS hanno acceso NoNewPrivileges (e rotto sudo) quando la
# unit gira con User= non-root. Riprodotte verbatim da `v0.41.0`.
_LE_SEI = """\
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectClock=true
ProtectHostname=true
RestrictRealtime=true
LockPersonality=true
"""
NOMI_DELLE_SEI = {"ProtectKernelTunables", "ProtectKernelModules", "ProtectClock",
                  "ProtectHostname", "RestrictRealtime", "LockPersonality"}

# ① la unit CURATA, come sta in main dopo la #104 e come è stata messa a mano sulla VPS
CURATA = """\
[Service]
User=vps1777
# Serve sudo (install/chown): NIENTE hardening che riaccenda NNP.
NoNewPrivileges=no
ExecStart=/usr/local/bin/vps1777 update --yes
"""

# ② la unit dei TAG v0.40.14 e v0.41.0: le sei, e NESSUNA riga NoNewPrivileges
DEI_TAG = f"""\
[Service]
User=vps1777
# Perciò NIENTE NoNewPrivileges (romperebbe sudo/setuid)
{_LE_SEI}ExecStart=/usr/local/bin/vps1777 update --yes
"""

# ③ lo stato prodotto dalla cura sbagliata (#101): la riga C'È, e le sei pure
CON_LA_RIGA_E_LE_SEI = f"""\
[Service]
User=vps1777
NoNewPrivileges=no
{_LE_SEI}ExecStart=/usr/local/bin/vps1777 update --yes
"""


def test_il_bundle_che_annulla_la_cura_viene_BLOCCATO() -> None:
    """Il caso vero: macchina curata a mano, bundle 0.41.0 che rimette le sei."""
    aggiunte = _cli.unit_regredisce(CURATA, DEI_TAG)
    assert aggiunte == NOMI_DELLE_SEI, (
        f"le sei direttive non sono state viste come regressione: {aggiunte}"
    )


def test_lo_STATUS_QUO_non_e_una_regressione() -> None:
    """Installata rotta + bundle rotto uguale: non c'è niente da annullare.

    Serve perché il contrario sarebbe un LOCK-OUT: su una macchina non ancora curata
    ogni update verrebbe rifiutato, compreso quello che porta la cura.
    """
    assert _cli.unit_regredisce(DEI_TAG, DEI_TAG) == set()


def test_l_update_normale_passa() -> None:
    assert _cli.unit_regredisce(CURATA, CURATA) == set()


def test_se_l_installata_NON_dichiara_di_elevare_non_giudico() -> None:
    """Fail-open sul dubbio: `set()` vuol dire «non lo so», non «va bene».

    Se il servizio non dichiara `NoNewPrivileges=no` non sappiamo che debba elevare, e
    un `die` qui impedirebbe di installare proprio la release che sistemerebbe le cose.
    """
    assert _cli.unit_regredisce(DEI_TAG, CURATA) == set()


def test_la_cura_SBAGLIATA_non_inganna_il_controllo() -> None:
    """`NoNewPrivileges=no` insieme alle sei: la riga c'è e non basta.

    Se la macchina fosse ferma allo stato prodotto dalla #101, un bundle che porta le
    stesse sei non aggiunge nulla — nessuna regressione da segnalare. Ma partendo dalla
    unit curata, quello stato È una regressione: sono due domande diverse e il test le
    tiene separate.
    """
    assert _cli.unit_regredisce(CON_LA_RIGA_E_LE_SEI, DEI_TAG) == set()
    assert _cli.unit_regredisce(CURATA, CON_LA_RIGA_E_LE_SEI) == NOMI_DELLE_SEI


def test_i_COMMENTI_non_contano_come_direttive() -> None:
    """La cura, spiegandosi, scrive la stringa che il controllo cerca.

    Una unit curata che *nomina* le sei nel commento per dire perché non ci sono non
    deve risultare piena di sandboxing.
    """
    curata_che_si_spiega = CURATA.replace(
        "# Serve sudo",
        "# Tolte LockPersonality, ProtectClock e le altre quattro: riaccendono NNP.\n# Serve sudo")
    assert _cli.unit_regredisce(CURATA, curata_che_si_spiega) == set()


# ── L'ANELLO CHE LA FUNZIONE PURA NON PROVA: chi la CHIAMA, e con quale ordine ────────
# I test qui sopra dicono che `unit_regredisce` giudica bene. Non dicono che il flusso
# le passi gli argomenti nel verso giusto — e scambiarli è l'errore che ci si aspetta:
# passerebbe tutti i test di sopra restando invisibile. Qui si esercita
# `regressioni_del_bundle` su DUE DIRECTORY VERE, che è il gesto che l'update fa.

def _scrivi(dove, nome: str, testo: str):
    dove.mkdir(parents=True, exist_ok=True)
    (dove / nome).write_text(testo, encoding="utf-8")


def test_il_giro_sui_file_vede_la_regressione(tmp_path) -> None:
    bundle, installate = tmp_path / "bundle", tmp_path / "etc"
    _scrivi(bundle / "systemd", "vps1777-auto-update.service", DEI_TAG)
    _scrivi(installate, "vps1777-auto-update.service", CURATA)
    fuori = _cli.regressioni_del_bundle(bundle, tmp_path, installate)
    assert set(fuori) == {"vps1777-auto-update.service"}
    assert set(fuori["vps1777-auto-update.service"]) == NOMI_DELLE_SEI


def test_ARGOMENTI_SCAMBIATI_darebbero_un_altro_esito(tmp_path) -> None:
    """La controprova che rende utile il test qui sopra.

    Se il flusso passasse il bundle come «installata» e viceversa, il verdetto sarebbe
    VUOTO — cioè un verde. Questo test fissa l'asimmetria: se un giorno qualcuno
    inverte i due argomenti, sopra diventa rosso e qui si legge perché.
    """
    bundle, installate = tmp_path / "bundle", tmp_path / "etc"
    _scrivi(bundle / "systemd", "vps1777-auto-update.service", CURATA)
    _scrivi(installate, "vps1777-auto-update.service", DEI_TAG)
    assert _cli.regressioni_del_bundle(bundle, tmp_path, installate) == {}


def test_unit_NUOVA_nel_bundle_non_e_una_regressione(tmp_path) -> None:
    bundle, installate = tmp_path / "bundle", tmp_path / "etc"
    _scrivi(bundle / "systemd", "vps1777-nuova.service", DEI_TAG)
    installate.mkdir(parents=True, exist_ok=True)  # esiste, ma vuota
    assert _cli.regressioni_del_bundle(bundle, tmp_path, installate) == {}


def test_un_bundle_SENZA_systemd_non_e_un_verde_inventato(tmp_path) -> None:
    """Zero unit da confrontare dà `{}` — e va detto che significa «niente da dire».

    È lo stesso avvertimento di `test_ci_sono_unit_da_controllare`: un ciclo su zero
    elementi passa in silenzio. Qui il `{}` è corretto (il die non scatta), ma chi
    legge deve sapere che quel verde non copre nulla.
    """
    assert _cli.regressioni_del_bundle(tmp_path / "vuoto", tmp_path, tmp_path / "etc") == {}


def test_il_preflight_gira_PRIMA_del_self_update() -> None:
    """La posizione è la parte non ovvia, e un riordino la perderebbe in silenzio.

    Il controllo deve girare con la CLI **installata**, prima che il self-update ceda
    il posto a quella del bundle: l'oggetto da cui difendersi è proprio un bundle che
    porta indietro una unit, e se il giudizio toccasse alla CLI del bundle **un bundle
    vecchio disattiverebbe il proprio controllo**.

    ⚠️ È un test sulla FORMA, e lo dichiara: verifica l'ordine di due chiamate nel
    sorgente, non che il flusso funzioni. Il `die` che sta in mezzo non è coperto da
    nessun test — quel pezzo lo prova solo un update vero.
    """
    import ast
    albero = ast.parse((RADICE / "tools" / "vps1777.py").read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(albero)
              if isinstance(n, ast.FunctionDef) and n.name == "cmd_update")
    riga_preflight = min(
        (n.lineno for n in ast.walk(fn) if isinstance(n, ast.Call)
         and isinstance(n.func, ast.Name) and n.func.id == "regressioni_del_bundle"),
        default=None)
    riga_exec = min(
        (n.lineno for n in ast.walk(fn) if isinstance(n, ast.Call)
         and isinstance(n.func, ast.Attribute) and n.func.attr == "execv"),
        default=None)
    assert riga_preflight is not None, (
        "cmd_update non chiama regressioni_del_bundle: il pre-flight non gira più"
    )
    assert riga_exec is not None, (
        "non trovo os.execv in cmd_update — il self-update è cambiato forma: "
        "questo test non sa più dove sta il confine e va riscritto, non ignorato"
    )
    assert riga_preflight < riga_exec, (
        f"il pre-flight (r.{riga_preflight}) gira DOPO il self-update (r.{riga_exec}).\n"
        "  Così a giudicare il bundle sarebbe la CLI del bundle stesso: un bundle che "
        "reintroduce le direttive porta con sé anche la versione del controllo che non "
        "le vede. Il giudizio deve restare alla CLI installata."
    )
