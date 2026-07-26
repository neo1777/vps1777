"""Test della revoke-list della sessione admin (H20) — stdlib-only, offline.

Il fix che questi test proteggono: il logout deve REVOCARE il token, non solo
cancellare il cookie nel browser. Se la revoca non sopravvive a un restart, o se
la lista cresce all'infinito, il fix è finto.
"""
from __future__ import annotations

import calendar
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import admin_core  # noqa: E402
import pytest  # noqa: E402


# ───── prune ─────

def test_prune_toglie_le_voci_scadute_e_tiene_le_vive():
    now = 1000.0
    entries = {"vecchio": 999.0, "adesso": 1000.0, "vivo": 1001.0}
    assert admin_core.prune(entries, now) == {"vivo": 1001.0}


def test_prune_su_lista_vuota():
    assert admin_core.prune({}, time.time()) == {}


# ───── revoca ─────

def test_revoca_e_controllo(tmp_path):
    rl = admin_core.RevocationList(tmp_path / "admin_revoked.json")
    assert rl.is_revoked("abc") is False
    assert rl.revoke("abc", time.time() + 3600) is True
    assert rl.is_revoked("abc") is True
    assert rl.is_revoked("altro") is False


def test_jti_vuoto_non_revoca_nulla(tmp_path):
    rl = admin_core.RevocationList(tmp_path / "admin_revoked.json")
    assert rl.revoke("", time.time() + 3600) is False
    assert rl.is_revoked("") is False


def test_la_revoca_sopravvive_al_restart(tmp_path):
    """Il caso che conta: gateway riavviato, il token rubato deve restare morto."""
    path = tmp_path / "admin_revoked.json"
    admin_core.RevocationList(path).revoke("rubato", time.time() + 3600)

    dopo_il_restart = admin_core.RevocationList(path)  # nuovo processo → rilegge il file
    assert dopo_il_restart.is_revoked("rubato") is True


def test_il_file_e_json_leggibile_jti_to_exp(tmp_path):
    path = tmp_path / "admin_revoked.json"
    rl = admin_core.RevocationList(path)
    rl.revoke("j1", 4000.0)
    data = json.loads(path.read_text())
    assert data == {"j1": 4000.0}
    assert len(rl) == 1


# ───── potatura: la lista non cresce all'infinito ─────

def test_le_voci_scadute_spariscono_alla_ricarica(tmp_path):
    path = tmp_path / "admin_revoked.json"
    now = 1_000_000.0
    rl = admin_core.RevocationList(path)
    rl.revoke("scaduto_presto", now + 10, now=now)
    rl.revoke("lunga_vita", now + 10_000, now=now)
    assert len(rl) == 2

    # un'ora dopo: il token "scaduto_presto" è morto da sé (exp passata) → la
    # verifica JWT lo rifiuta comunque, ricordarne il jti è solo peso.
    rl.reload(now=now + 3600)
    assert rl.is_revoked("scaduto_presto") is False
    assert rl.is_revoked("lunga_vita") is True
    assert len(rl) == 1


def test_la_potatura_finisce_su_disco_alla_prima_scrittura(tmp_path):
    path = tmp_path / "admin_revoked.json"
    now = 1_000_000.0
    rl = admin_core.RevocationList(path)
    rl.revoke("vecchio", now + 10, now=now)

    rl.revoke("nuovo", now + 10_000, now=now + 3600)  # `now` avanzato → pota
    assert json.loads(path.read_text()) == {"nuovo": now + 10_000}


# ───── robustezza ─────

def test_file_corrotto_non_fa_esplodere_nulla(tmp_path):
    path = tmp_path / "admin_revoked.json"
    path.write_text("{non json")
    rl = admin_core.RevocationList(path)
    assert len(rl) == 0
    assert rl.is_revoked("x") is False
    # e si riparte da un file valido
    assert rl.revoke("x", time.time() + 60) is True
    assert json.loads(path.read_text())["x"] > 0


def test_voce_corrotta_scarta_la_voce_non_il_file(tmp_path):
    path = tmp_path / "admin_revoked.json"
    path.write_text(json.dumps({"buono": 9_999_999_999, "rotto": "domani"}))
    rl = admin_core.RevocationList(path)
    assert rl.is_revoked("buono") is True
    assert rl.is_revoked("rotto") is False


def test_disco_non_scrivibile_revoca_in_memoria_e_lo_dichiara(tmp_path):
    """Se non riesce a persistere lo DICE (False) — chi chiama lo audita invece
    di credere a una revoca durevole che non c'è."""
    occupato = tmp_path / "file"
    occupato.write_text("non sono una directory")
    rl = admin_core.RevocationList(occupato / "sub" / "admin_revoked.json")
    assert rl.revoke("abc", time.time() + 60) is False  # persistenza fallita
    assert rl.is_revoked("abc") is True                 # ma la revoca vale QUI e ORA


def test_la_scrittura_non_lascia_file_temporanei(tmp_path):
    path = tmp_path / "admin_revoked.json"
    rl = admin_core.RevocationList(path)
    rl.revoke("j1", time.time() + 60)
    rl.revoke("j2", time.time() + 60)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["admin_revoked.json"]


def test_rilegge_se_il_file_cambia_sotto(tmp_path):
    """Due istanze sullo stesso file (domani: più worker): la revoca fatta da una
    la vede anche l'altra, senza restart."""
    path = tmp_path / "admin_revoked.json"
    a = admin_core.RevocationList(path)
    b = admin_core.RevocationList(path)
    a.revoke("nuovo", time.time() + 3600)
    assert b.is_revoked("nuovo") is True


# ───── H30: l'open-redirect è già tornato una volta in un rilievo "chiuso" ─────


BASE = "https://vps1777-1.tail0c1f07.ts.net"


@pytest.mark.parametrize("hostile", [
    "https://vps1777-1.tail0c1f07.ts.net.evil.com/",  # IL BYPASS: prefisso ≠ origine
    "https://vps1777-1.tail0c1f07.ts.netEVIL.com",     # prefisso senza separatore
    "//evil.com",                                       # protocol-relative
    "/\\evil.com",                                      # backslash
    "/\t/evil.com",                                     # tab: il browser la cancella → //evil.com
    "/\r\n//evil.com",                                  # CRLF
    "https://evil.com",                                 # esterno secco
    "http://vps1777-1.tail0c1f07.ts.net/x",             # schema diverso da public_base
])
def test_next_ostile_viene_scartato(hostile):
    assert admin_core.safe_next_url(hostile, BASE) == "/admin/setup"


@pytest.mark.parametrize("legit", [
    "/admin/audit",
    "/admin/setup?msg=ok",
    "https://vps1777-1.tail0c1f07.ts.net/admin/nlm",
    "https://vps1777-1.tail0c1f07.ts.net",
    "https://vps1777-1.tail0c1f07.ts.net?x=1",
])
def test_next_legittimo_passa(legit):
    # se questi non passano, il login legittimo è rotto
    assert admin_core.safe_next_url(legit, BASE) == legit


def test_next_vuoto_va_al_fallback():
    assert admin_core.safe_next_url("", BASE) == "/admin/setup"


def test_senza_public_base_solo_i_relativi_passano():
    assert admin_core.safe_next_url("/admin/audit", "") == "/admin/audit"


# ── ore_da: l'età del verdetto «sei alla versione più recente» ───────────────
# Nasce da una misura di abdd732a (26/07): la card diceva «Sei alla versione più
# recente» al presente, con la data del check stampata sotto in grigio. Le due
# righe insieme dicevano il vero; la prima da sola diceva il falso — ed è quella
# che si legge. Da H50 il gateway non ha più uscita Internet, quindi non esiste
# più un pulsante per rinfrescare: il verdetto DEVE portare la propria età.

def test_ore_da_conta_le_ore_intere():
    base = calendar.timegm(time.strptime("2026-07-26T12:00:00Z", "%Y-%m-%dT%H:%M:%SZ"))
    assert admin_core.ore_da("2026-07-26T12:00:00Z", now=base) == 0
    assert admin_core.ore_da("2026-07-26T09:00:00Z", now=base) == 3
    assert admin_core.ore_da("2026-07-25T10:00:00Z", now=base) == 26     # oltre il ciclo del timer
    assert admin_core.ore_da("2026-07-26T11:01:00Z", now=base) == 0      # 59' non è «un'ora fa»


def test_ore_da_distingue_NON_SO_da_ADESSO():
    # Il terzo stato: se il fallimento tornasse 0, «data illeggibile» si
    # leggerebbe come «appena controllato» — cioè il verde più bugiardo possibile.
    for rotto in ("", "mai", "2026-07-26 21:00", "ieri", None, 12345):
        assert admin_core.ore_da(rotto) is None, f"«{rotto}» doveva dare None, non un numero"


def test_ore_da_non_torna_mai_negativo():
    # host e container con orologi non allineati: «-3 ore fa» si vede solo in
    # produzione, e a quel punto la pagina ha già mentito.
    base = calendar.timegm(time.strptime("2026-07-26T12:00:00Z", "%Y-%m-%dT%H:%M:%SZ"))
    assert admin_core.ore_da("2026-07-26T14:00:00Z", now=base) == 0


# ── classe_verdetto_update: cosa legge l'admin nella card aggiornamenti ──────
# Misurato il 26/07 (71d540e6): ZERO test in tutto il repo nominavano
# update_check / update_status / _fetch / «Refresh». Il ramo che l'utente vede
# a ogni visita non era coperto da niente — ed è quello che dice se il sistema
# è aggiornato. La decisione vive qui apposta per poter essere provata.

def _vg(a, b):
    """version_gt semplificato per i test: confronto per tuple numeriche."""
    pa = tuple(int(x) for x in str(a).split("."))
    pb = tuple(int(x) for x in str(b).split("."))
    return pa > pb


def _adesso(delta_h=0.0):
    base = calendar.timegm(time.strptime("2026-07-26T12:00:00Z", "%Y-%m-%dT%H:%M:%SZ"))
    return base, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(base - delta_h * 3600))


def test_verdetto_aggiornato_porta_l_eta():
    now, checked = _adesso(5)
    assert admin_core.classe_verdetto_update("0.40.4", "0.40.4", checked, None,
                                             now=now, piu_recente=_vg) == ("aggiornato", 5)


def test_verdetto_oltre_il_ciclo_del_timer_cambia_natura():
    # 26h+: non «dato vecchio» ma «il controllo potrebbe non girare» — rimedio diverso.
    now, checked = _adesso(35)
    classe, ore = admin_core.classe_verdetto_update("0.40.4", "0.40.4", checked, None,
                                                    now=now, piu_recente=_vg)
    assert (classe, ore) == ("timer-fermo", 35)
    # il confine si comporta: sotto la soglia è ancora «aggiornato».
    now, sotto = _adesso(admin_core.CHECK_STALE_H - 1)
    assert admin_core.classe_verdetto_update("0.40.4", "0.40.4", sotto, None,
                                             now=now, piu_recente=_vg)[0] == "aggiornato"


def test_verdetto_non_dice_aggiornato_quando_ce_un_aggiornamento():
    # la controprova che conta: il caso in cui un verde sarebbe una bugia.
    now, checked = _adesso(1)
    assert admin_core.classe_verdetto_update("0.40.3", "0.40.4", checked, None,
                                             now=now, piu_recente=_vg)[0] == "aggiornamento"


def test_verdetto_errore_vince_su_tutto():
    # con un check fallito il dato è stantio: non si dichiara nulla sulla versione.
    now, checked = _adesso(1)
    assert admin_core.classe_verdetto_update("0.40.4", "0.40.4", checked, "boom",
                                             now=now, piu_recente=_vg)[0] == "errore-check"


def test_verdetto_latest_piu_vecchia_non_e_un_downgrade():
    # cache stantia di GitHub: latest < current. Non è «aggiornamento disponibile».
    now, checked = _adesso(1)
    assert admin_core.classe_verdetto_update("0.40.4", "0.39.1", checked, None,
                                             now=now, piu_recente=_vg)[0] == "latest-piu-vecchia"


def test_verdetto_data_illeggibile_non_si_spaccia_per_appena_controllato():
    now, _ = _adesso(0)
    classe, ore = admin_core.classe_verdetto_update("0.40.4", "0.40.4", "mai", None,
                                                    now=now, piu_recente=_vg)
    assert (classe, ore) == ("data-illeggibile", None)


def test_verdetto_mai_controllato_quando_non_ce_una_latest():
    now, checked = _adesso(1)
    assert admin_core.classe_verdetto_update("0.40.4", None, checked, None,
                                             now=now, piu_recente=_vg)[0] == "mai-controllato"


def _ritardo_massimo_dal_timer() -> int:
    """Legge l'UNITÀ VERA e ne deriva il ritardo massimo legittimo, in ore.

    Non una costante: il file. Prima versione di questo test (rilievo di
    abdd732a): confrontava CHECK_STALE_H con CHECK_TIMER_MAX_H — due costanti
    dello STESSO modulo. Se qualcuno alza RandomizedDelaySec nel .timer, quel
    test resta VERDE mentre la pagina ricomincia ad accusare un timer sano:
    legava due cose che si muovono insieme, non il codice alla sua ragione.
    Un presidio deve leggere la fonte che sorveglia, non una sua copia.
    """
    unit = Path(__file__).resolve().parents[3] / "systemd" / "vps1777-check-update.timer"
    testo = unit.read_text()
    assert "OnCalendar=daily" in testo, (
        f"{unit.name} non è più `OnCalendar=daily`: questo test e la soglia "
        "CHECK_STALE_H vanno rivisti insieme al timer."
    )
    m = re.search(r"^RandomizedDelaySec=(\d+)h", testo, re.M)
    assert m, f"{unit.name}: RandomizedDelaySec non leggibile o non in ore"
    return 24 + int(m.group(1))


def test_soglia_stale_copre_il_ritardo_massimo_DELL_UNITA_VERA():
    """La soglia non può stare SOTTO il ritardo legittimo del timer REALE.

    Il valore non è preso da una costante ma dal file systemd che governa il
    check: se il timer cambia, questo test lo vede e lo dice. Con una soglia
    più bassa la pagina accuserebbe un timer sano di non funzionare — e un
    allarme che suona senza motivo è quello che si impara a ignorare, cioè il
    modo più affidabile di disattivare un presidio.
    """
    massimo = _ritardo_massimo_dal_timer()
    assert admin_core.CHECK_STALE_H > massimo, (
        f"soglia {admin_core.CHECK_STALE_H}h ≤ ritardo massimo legittimo {massimo}h "
        "(OnCalendar=daily + RandomizedDelaySec letti dall'unità)"
    )
    # e la costante nel modulo deve combaciare con l'unità: se divergono, è la
    # copia ad aver smesso di dire il vero — la fonte è il file.
    assert admin_core.CHECK_TIMER_MAX_H == massimo, (
        f"CHECK_TIMER_MAX_H={admin_core.CHECK_TIMER_MAX_H} ma l'unità dice {massimo}: "
        "la costante è una copia stantia del timer"
    )


def test_un_timer_sano_al_suo_ritardo_massimo_non_fa_scattare_l_allarme():
    # il caso concreto: 28h esatte — il peggior ritardo LEGITTIMO.
    now, checked = _adesso(_ritardo_massimo_dal_timer())
    classe, _ = admin_core.classe_verdetto_update("0.40.4", "0.40.4", checked, None,
                                                  now=now, piu_recente=_vg)
    assert classe == "aggiornato", "28h è il ritardo massimo NORMALE: niente allarme"
