"""Test di logica pura per tools/vps1777.py (nessun docker/systemd richiesto).

Copre i fix H14 (esclusione nlm-auth dallo snapshot in chiaro) e H43
(templatizzazione delle unit systemd). Solo stdlib; eseguibile sia con pytest
sia direttamente: `python3 tools/tests/test_vps1777.py`.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pwd
import re
import tempfile
from pathlib import Path

import pytest   # usato dai casi H55: `pytest.raises` sul rifiuto da root

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("vps1777_cli", _ROOT / "tools" / "vps1777.py")
v = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v)


# ─────────────────────────────── H14: snapshot pre-update ───────────────────

def test_nlm_auth_excluded_from_snapshot_but_known_to_restore():
    # nlm-auth NON entra nello snapshot in chiaro…
    assert "nlm-auth" not in v.SNAPSHOT_VOLUMES
    assert v.SNAPSHOT_EXCLUDED_VOLUMES == ["nlm-auth"]
    assert v.SNAPSHOT_VOLUMES == ["gateway-data", "archive-data"]
    # …ma resta in DATA_VOLUMES: backup.sh (age, cifrato) e restore.sh lo trattano.
    assert "nlm-auth" in v.DATA_VOLUMES


def test_snapshot_stale_excluded_finds_only_excluded_tars():
    with tempfile.TemporaryDirectory() as d:
        base = Path(d) / "backups" / "pre-update"
        s1 = base / "0.31.0-a"
        s1.mkdir(parents=True)
        (s1 / "gateway-data.tar").write_text("x")
        (s1 / "archive-data.tar").write_text("x")
        (s1 / "nlm-auth.tar").write_text("SECRET")  # residuo di una CLI pre-fix
        s2 = base / "0.30.0-b"
        s2.mkdir(parents=True)
        (s2 / "gateway-data.tar").write_text("x")   # snapshot già pulito
        stale = v.snapshot_stale_excluded(base)
        assert stale == [s1 / "nlm-auth.tar"]


def test_snapshot_purge_removes_only_excluded():
    with tempfile.TemporaryDirectory() as d:
        base = Path(d) / "backups" / "pre-update"
        s1 = base / "0.31.0-a"
        s1.mkdir(parents=True)
        (s1 / "gateway-data.tar").write_text("keep")
        (s1 / "nlm-auth.tar").write_text("SECRET")
        removed = v.snapshot_purge_excluded(Path(d))
        assert removed == 1
        assert not (s1 / "nlm-auth.tar").exists()
        assert (s1 / "gateway-data.tar").exists()


def test_snapshot_stale_missing_base_is_empty():
    with tempfile.TemporaryDirectory() as d:
        assert v.snapshot_stale_excluded(Path(d) / "nope") == []


def test_snapshot_prune_with_keep_latest_survives_when_all_are_stale():
    # round-5 (audio e1cff3b1): con keep=None il check giornaliero cancella
    # TUTTI gli snapshot se sono tutti oltre il cutoff — incluso quello della
    # versione in esecuzione. cmd_check ora passa keep=snapshot_latest(repo):
    # anche se il più recente è vecchio quanto gli altri, resta.
    with tempfile.TemporaryDirectory() as d:
        repo = Path(d)
        base = repo / "backups" / "pre-update"
        older = base / "0.40.1-a"
        newer = base / "0.40.2-b"
        older.mkdir(parents=True)
        newer.mkdir(parents=True)
        (older / "gateway-data.tar").write_text("x")
        (newer / "gateway-data.tar").write_text("x")
        stale_ts = __import__("time").time() - 200 * 3600  # oltre il cutoff di 72h
        os.utime(older, (stale_ts, stale_ts))
        os.utime(newer, (stale_ts + 60, stale_ts + 60))  # più recente, ma comunque stale
        v.snapshot_prune(repo, keep=v.snapshot_latest(repo))
        assert not older.exists()
        assert newer.exists()


# ─────────────────────────────── H43: render_unit ──────────────────────────

def test_render_unit_substitutes_all_placeholders():
    pw = pwd.getpwuid(os.getuid())
    txt = ("User=@OPERATOR_USER@\nGroup=@OPERATOR_USER@\n"
           "Environment=VPS1777_HOME=@REPO@\nWorkingDirectory=@REPO@\n"
           "ExecStart=/usr/local/bin/vps1777 update "
           "--from-intent @REPO@/onboarding/update_pending_update.json\n")
    out = v.render_unit(txt, Path("/opt/vps1777"))
    assert "@OPERATOR_USER@" not in out
    assert "@REPO@" not in out
    assert f"User={pw.pw_name}" in out
    assert "VPS1777_HOME=/opt/vps1777" in out
    assert "/opt/vps1777/onboarding/update_pending_update.json" in out


def test_render_unit_idempotent_on_placeholderless_text():
    plain = "[Timer]\nOnCalendar=daily\nPersistent=true\n"
    assert v.render_unit(plain, Path("/opt/vps1777")) == plain


# ─────────────────────── H55: l'operatore NON è chi lancia ──────────────────
# 🔴 IL DIFETTO (01/08): `render_unit` deduceva l'utente da `getpwuid(getuid())`.
#   Un install lanciato da root rendeva le unit con `User=root` — l'updater
#   automatico con i privilegi pieni della macchina, a ogni avvio, e in silenzio.
#   Il registro attribuiva il fatto a «la unit gira come root», che nel repo non
#   era vero: le unit portano `@OPERATOR_USER@`. Il fatto reggeva, la causa no.
# ⭐ La policy esisteva già in UN installer su tre (`installer/engine.py:30`,
#   `OPERATOR_USER = "vps1777"`): qui non se ne inventa una, si applica dove
#   mancava. La via d'uscita `OPERATOR_USER` è quella che `deploy.sh:218` usa già.
# ⚠️ I test NON cambiano uid (non si può, e non si deve): sostituiscono `getuid`
#   e `getpwuid` nel modulo. È un doppio dello STATO del sistema, non della
#   funzione che si prova — la logica sotto esame resta quella vera.

class _Pw:
    def __init__(self, name, home):
        self.pw_name, self.pw_dir = name, home


def test_render_unit_rifiuta_root_e_dice_come_uscirne(monkeypatch):
    """Il caso che il difetto produceva in silenzio: install da root."""
    monkeypatch.delenv("OPERATOR_USER", raising=False)
    monkeypatch.setattr(v.os, "getuid", lambda: 0)
    monkeypatch.setattr(v.pwd, "getpwuid", lambda _uid: _Pw("root", "/root"))

    with pytest.raises(SystemExit) as e:
        v.render_unit("User=@OPERATOR_USER@\n", Path("/opt/vps1777"))

    msg = str(e.value)
    # non basta che rifiuti: deve dire COSA succederebbe, PERCHÉ, e il COMANDO.
    # Un rifiuto senza via d'uscita viene aggirato, e allora non protegge più.
    assert "User=root" in msg
    assert "OPERATOR_USER=vps1777" in msg, "manca il comando da incollare"
    assert "senza sudo" in msg, "manca la seconda strada"


def test_render_unit_da_root_con_operator_user_dichiarato(monkeypatch):
    """La via d'uscita deve FUNZIONARE, o il rifiuto è solo un muro."""
    monkeypatch.setenv("OPERATOR_USER", "vps1777")
    monkeypatch.setattr(v.os, "getuid", lambda: 0)
    monkeypatch.setattr(v.pwd, "getpwuid", lambda _uid: _Pw("root", "/root"))
    monkeypatch.setattr(v.pwd, "getpwnam", lambda n: _Pw(n, f"/home/{n}"))

    out = v.render_unit("User=@OPERATOR_USER@\nHome=@OPERATOR_HOME@\n",
                        Path("/opt/vps1777"))
    assert "User=vps1777" in out
    assert "Home=/home/vps1777" in out
    assert "root" not in out


def test_render_unit_operator_user_inesistente_SI_FERMA(monkeypatch):
    """🔺 QUESTO CASO È STATO ROVESCIATO IL 01/08, ed è la storia che vale.

    Prima verificava l'opposto — «non inventa la home, usa la convenzione degli
    altri installer» — e passava. Il codice sotto accettava un utente inesistente
    e lo scriveva nelle unit, motivato con «potrebbe non esistere ANCORA».

    ⭐ In astratto regge. Applicato a una macchina VIVA no: systemd rifiuta una
    unit con un utente che non sa risolvere («Failed to determine user
    credentials») e il servizio NON PARTE. Un difetto di privilegi sarebbe
    diventato un'INTERRUZIONE — e con `User=root` il servizio, male, funziona.

    Trovato da @abdd732a mentre il comando era già nella casella di Neo, sulla
    cui macchina le quattro unit giravano davvero come root. Il test vecchio non
    era sbagliato: rispondeva alla domanda giusta in un mondo in cui l'installer
    crea l'utente DOPO. Negli installer veri lo crea PRIMA (engine.py:306-314,
    unit a :583+) ⇒ se non esiste, qualcosa è già fuori posto e fermarsi è la
    risposta.
    🔑 Un test che passa non dice che il comportamento sia GIUSTO: dice che è
    QUELLO CHE VOLEVAMO quando l'abbiamo scritto. Quando cambia il mondo attorno,
    va rovesciato — e la traccia di com'era resta qui, o la prossima lo riscrive."""
    monkeypatch.setenv("OPERATOR_USER", "nuovo1777")
    monkeypatch.setattr(v.os, "getuid", lambda: 0)
    monkeypatch.setattr(v.pwd, "getpwnam", _kaboom)

    with pytest.raises(SystemExit) as e:
        v.render_unit("User=@OPERATOR_USER@\n", Path("/opt/vps1777"))

    msg = str(e.value)
    assert "nuovo1777" in msg, "deve dire QUALE utente manca"
    assert "useradd" in msg, "deve dare il comando per crearlo, o è solo un muro"
    assert "non partirebbero" in msg, "deve dire COSA succederebbe, non «errore»"


@pytest.mark.parametrize("valore", ["", "   ", "\t\n"])
def test_render_unit_operator_user_vuoto_non_e_una_dichiarazione(monkeypatch, valore):
    """`OPERATOR_USER=""` NON deve valere come «te l'ho detto».

    ⭐ Caso trovato da @abdd732a sul pezzo bash (`4cc25eb`): là sarebbe passato con
    un utente VUOTO — cioè `User=` nella unit, che systemd rifiuta o interpreta a
    modo suo. Il ramo python è protetto da uno `.strip()` + test di verità, ma
    **non aveva un caso che lo provasse**: una riscrittura che toglie lo `.strip()`
    non farebbe fallire niente. Il test esiste perché il buco è stato trovato
    ALTROVE — la stessa regola in due linguaggi si controlla in due posti."""
    monkeypatch.setenv("OPERATOR_USER", valore)
    monkeypatch.setattr(v.os, "getuid", lambda: 0)
    monkeypatch.setattr(v.pwd, "getpwuid", lambda _uid: _Pw("root", "/root"))

    with pytest.raises(SystemExit):
        v.render_unit("User=@OPERATOR_USER@\n", Path("/opt/vps1777"))


def test_render_unit_non_root_resta_come_prima(monkeypatch):
    """CONTROPROVA: il fix non deve cambiare il percorso normale — un presidio
    che rompe il caso legittimo si finisce per disattivarlo."""
    monkeypatch.delenv("OPERATOR_USER", raising=False)
    monkeypatch.setattr(v.os, "getuid", lambda: 1000)
    monkeypatch.setattr(v.pwd, "getpwuid", lambda _uid: _Pw("operatore", "/home/operatore"))

    out = v.render_unit("User=@OPERATOR_USER@\n", Path("/opt/vps1777"))
    assert out == "User=operatore\n"


def _kaboom(_n):
    raise KeyError("utente non ancora creato")


# ─────────────────────────────── H37: secret policy ────────────────────────

def test_secret_policy_covers_cloudflared_token():
    names = {row[0] for row in v._SECRET_POLICY}
    assert "cloudflared_token" in names
    # i 4 storici restano coperti
    assert {"oauth_signing_secret", "admin_password",
            "gateway_secret", "telegram_bot_token"} <= names


def test_nlm_cookie_constants_present():
    assert v.NLM_COOKIE_MAX_DAYS > 0
    assert callable(v.nlm_cookie_status)


# ─────────────────────── stato-feature dichiarato (anti-perdita-silenziosa) ──

def _repo_env(text: str) -> Path:
    d = Path(tempfile.mkdtemp())
    (d / ".env").write_text(text)
    return d


def test_enabled_features_default_explicit_none():
    # .env senza VPS1777_FEATURES → i default (backup + auto-update SICURO)
    assert v.enabled_features(_repo_env("INGRESS_PROFILE=ingress.tailscale\n")) == {"backup", "autoupdate"}
    assert v.enabled_features(_repo_env("VPS1777_FEATURES=backup,portainer\n")) == {"backup", "portainer"}
    # 'none' → tutto spento: lo stato dichiarato può anche disattivare
    assert v.enabled_features(_repo_env("VPS1777_FEATURES=none\n")) == set()


def test_compose_cmd_reflects_declared_state():
    # default → overlay backup presente; l'auto-update sicuro NON è un profilo (è un timer)
    j = " ".join(v.compose_cmd(_repo_env("INGRESS_PROFILE=ingress.tailscale\n")))
    assert "compose.ops.backup.yaml" in j and "--profile ops.backup" in j
    assert "compose.ops.autoupdate.yaml" not in j
    # watchtower (auto-update CRUDO) → il FILE giusto è ops.watchtower, il PROFILO ops.autoupdate
    # (regressione: derivare il file dal profilo referenziava compose.ops.autoupdate.yaml, inesistente)
    j = " ".join(v.compose_cmd(_repo_env("VPS1777_FEATURES=watchtower\n")))
    assert "compose.ops.watchtower.yaml" in j and "--profile ops.autoupdate" in j
    assert "compose.ops.autoupdate.yaml" not in j
    # none → nessun overlay ops
    assert not any("ops." in x for x in v.compose_cmd(_repo_env("VPS1777_FEATURES=none\n")))


# ────────────── pre-flight dei segreti: il ROSSO del 20/07 (release 0.40.1) ──
#
# Il difetto: `_secrets_mancanti` girava allo step 4 leggendo i compose ATTUALI,
# mentre il compose della release arriva col bundle allo step 5 — **quando girava,
# il file che doveva controllare non era ancora sul disco**. La 0.40.0 è fallita
# così: stack non partito, rollback riuscito. Non guardava la riga sbagliata, stava
# nel posto sbagliato: ed è per questo che letta da sola sembrava corretta.

def _installazione(env: str = "INGRESS_PROFILE=ingress.tailscale\n",
                   segreti: dict[str, str] | None = None) -> Path:
    """Un finto repo installato: `.env` + `secrets/` popolata."""
    d = Path(tempfile.mkdtemp())
    (d / ".env").write_text(env)
    (d / "secrets").mkdir()
    for nome, contenuto in (segreti or {}).items():
        (d / "secrets" / nome).write_text(contenuto)
    return d


def _compose_con(*nomi: str) -> str:
    corpo = "services:\n  x:\n    image: y\n\nsecrets:\n"
    for n in nomi:
        corpo += f"  {n}:\n    file: ./secrets/{n}.txt\n"
    return corpo


def test_secrets_dichiarazione_dallo_staging_file_dal_repo():
    # LA TRAPPOLA (vista da setaccio sul codice, prima che fosse scritto): i due
    # argomenti servono a scopi diversi. Passare il bundle anche come radice dei
    # FILE cercherebbe i segreti in bundle/secrets/ — che non esiste — e direbbe
    # che mancano TUTTI: un rosso totale, credibilissimo, su una funzione nata per
    # essere creduta. Qui si dimostra che dichiarazione e file restano separati.
    repo = _installazione(segreti={"alfa.txt": "v"})
    bundle = Path(tempfile.mkdtemp())
    (bundle / "compose.yaml").write_text(_compose_con("alfa"))
    # dichiarazione dal bundle, file dal repo → il segreto c'è, nessuna mancanza
    assert v._secrets_mancanti([bundle / "compose.yaml"], repo) == []
    # la trappola: stessa dichiarazione, ma radice-file sbagliata. NON deve uscire un
    # rosso credibile sui nomi: deve dire che la RADICE è sbagliata. b82df434 ci è caduta
    # al primo tentativo scrivendo il caso che la documenta — la firma rende l'errore
    # visibile, questa guardia lo rende dicibile.
    fuori = v._secrets_mancanti([bundle / "compose.yaml"], bundle)
    assert len(fuori) == 1 and "RADICE è sbagliata" in fuori[0]


def test_radice_sbagliata_non_si_confonde_con_segreti_davvero_mancanti():
    # La guardia non deve mangiarsi il caso vero: se `secrets/` ESISTE e i file non ci
    # sono, mancano davvero e i nomi vanno detti. Altrimenti avrei chiuso N9 creando un
    # falso verde — il difetto (d) in un'altra forma.
    repo = _installazione()                       # crea secrets/ ma vuota
    (repo / "compose.yaml").write_text(_compose_con("a", "b"))
    fuori = v._secrets_mancanti([repo / "compose.yaml"], repo)
    assert len(fuori) == 2 and all("RADICE" not in f for f in fuori)


def test_secrets_release_che_introduce_un_segreto_e_fatale():
    # IL CASO CHE HA FATTO FALLIRE LA 0.40.0, in miniatura: il compose ATTUALE non
    # dichiara `nuovo`, quello del BUNDLE sì, e il file non c'è. Il vecchio controllo
    # (compose attuale) diceva verde; questo lo vede.
    repo = _installazione(segreti={"vecchio.txt": "v"})
    (repo / "compose.yaml").write_text(_compose_con("vecchio"))
    bundle = Path(tempfile.mkdtemp())
    (bundle / "compose.yaml").write_text(_compose_con("vecchio", "nuovo"))
    assert v._secrets_mancanti(v._compose_sorgenti(repo, repo), repo) == []      # il vecchio: verde
    fuori = v._secrets_mancanti(v._compose_sorgenti(bundle, repo), repo)         # il nuovo: rosso
    assert len(fuori) == 1 and "nuovo" in fuori[0]


def test_secrets_release_che_toglie_un_segreto_passa():
    # N10 (b82df434) / caso-limite di setaccio: una release che RIMUOVE un segreto il
    # cui file è già sparito deve poter essere installata. Se il codice la blocca è
    # rotto: sarebbe il falso positivo speculare al falso verde del 20/07 — l'unica
    # release che elimina il problema diventa l'unica che non puoi installare.
    repo = _installazione(segreti={"resta.txt": "v"})          # `orfano.txt` NON c'è
    (repo / "compose.yaml").write_text(_compose_con("resta", "orfano"))
    bundle = Path(tempfile.mkdtemp())
    (bundle / "compose.yaml").write_text(_compose_con("resta"))
    assert v._secrets_mancanti(v._compose_sorgenti(bundle, repo), repo) == []    # update legittimo
    # …ma il 4-bis lo dice lo stesso, perché la rete di rollback è davvero bucata:
    assert len(v._secrets_mancanti(v._compose_sorgenti(repo, repo), repo)) == 1


def test_secrets_file_vuoto_conta_come_mancante():
    # Un file vuoto è peggio di uno assente: lo stack parte e il canale resta
    # fail-closed — un difetto di provisioning travestito da bug della feature.
    repo = _installazione(segreti={"a.txt": ""})
    (repo / "compose.yaml").write_text(_compose_con("a"))
    assert len(v._secrets_mancanti([repo / "compose.yaml"], repo)) == 1


def test_secrets_guarda_gli_overlay_non_solo_il_compose_base():
    # DIFETTO (c), b82df434: il pre-flight guardava UN file, lo stack ne monta DUE.
    # `compose.ingress.cloudflared.yaml` dichiara davvero un segreto (r.44 del reale).
    repo = _installazione(env="INGRESS_PROFILE=ingress.cloudflared\nVPS1777_FEATURES=none\n")
    (repo / "compose.yaml").write_text(_compose_con("base"))
    (repo / "compose.ingress.cloudflared.yaml").write_text(_compose_con("cloudflared_token"))
    (repo / "secrets" / "base.txt").write_text("v")            # `cloudflared_token.txt` manca
    fuori = v._secrets_mancanti(v._compose_sorgenti(repo, repo), repo)
    assert len(fuori) == 1 and "cloudflared_token" in fuori[0]


def test_secrets_guarda_anche_gli_overlay_delle_feature_attive():
    # QUARTO DIFETTO (71d540e6): `compose_cmd` monta anche un overlay per ogni feature
    # attiva, e `backup` è in DEFAULT_FEATURES ⇒ montato ORA su questa macchina. Lo
    # step 8 ne passa due soli: prendere la sua lista come modello ne eredita il difetto.
    # Perciò la lista si DERIVA da `_compose_sorgenti`, che è l'unico posto che la sa.
    repo = _installazione(env="INGRESS_PROFILE=ingress.tailscale\nVPS1777_FEATURES=backup\n")
    (repo / "compose.yaml").write_text(_compose_con("base"))
    (repo / "compose.ops.backup.yaml").write_text(_compose_con("chiave_backup"))
    (repo / "secrets" / "base.txt").write_text("v")
    fuori = v._secrets_mancanti(v._compose_sorgenti(repo, repo), repo)
    assert len(fuori) == 1 and "chiave_backup" in fuori[0]
    # …e con la feature SPENTA quell'overlay non conta più: nessun falso rosso.
    spento = _installazione(env="VPS1777_FEATURES=none\n", segreti={"base.txt": "v"})
    (spento / "compose.yaml").write_text(_compose_con("base"))
    (spento / "compose.ops.backup.yaml").write_text(_compose_con("chiave_backup"))
    assert v._secrets_mancanti(v._compose_sorgenti(spento, spento), spento) == []


def test_secrets_stesso_segreto_in_due_compose_si_dice_una_volta():
    repo = _installazione(env="INGRESS_PROFILE=ingress.cloudflared\nVPS1777_FEATURES=none\n")
    (repo / "compose.yaml").write_text(_compose_con("doppio"))
    (repo / "compose.ingress.cloudflared.yaml").write_text(_compose_con("doppio"))
    assert len(v._secrets_mancanti(v._compose_sorgenti(repo, repo), repo)) == 1


def test_secrets_formato_illeggibile_segnala_invece_di_tacere():
    # La guardia contro il falso verde: sezione presente e piena, ma non ne esce
    # nemmeno un nome ⇒ il formato è cambiato sotto di noi. Restituire [] sarebbe il
    # falso verde in un'altra forma. (È anche la ragione per cui il controllo fatale
    # sta DOPO il re-exec: questa guardia, messa prima, diventerebbe un lock-out —
    # il parser vecchio non capirebbe il compose nuovo e impedirebbe di installare
    # proprio la release che contiene il parser che lo capirebbe.)
    repo = _installazione()
    (repo / "compose.yaml").write_text("secrets:\n  qualcosa_che_non_capiamo: [1,2]\n")
    fuori = v._secrets_mancanti([repo / "compose.yaml"], repo)
    assert len(fuori) == 1 and "non ha saputo leggere" in fuori[0]


def test_secrets_indentazione_a_quattro_spazi_resta_vista():
    # Regressione del falso verde di b82df434: la prima versione pretendeva esattamente
    # due spazi; con quattro — YAML altrettanto valido — non vedeva nulla e diceva
    # «tutto a posto». Non falliva: diceva di sì.
    repo = _installazione()
    (repo / "compose.yaml").write_text(
        "secrets:\n    tanto_indentato:\n        file: ./secrets/tanto_indentato.txt\n")
    assert len(v._secrets_mancanti([repo / "compose.yaml"], repo)) == 1


def test_secrets_vuoto_e_vuoto_dopo_strip_non_zero_byte():
    # N5 / difetto (e), riprodotto su banco da b82df434 sulla base: `st_size == 0`
    # lasciava passare un file con solo «\n» (1 byte) o con soli spazi. Chi riempie un
    # segreto a mano con un editor lascia il newline. Lo stack parte, il canale resta
    # fail-closed, e il sintomo sembra un bug della feature: cioè esattamente ciò che
    # la docstring del pre-flight dichiarava di prevenire senza averlo mai fatto.
    for contenuto, atteso_mancante in (("\n", True), ("   \n", True),
                                       ("  \t \n", True), ("abc\n", False)):
        repo = _installazione(segreti={"a.txt": contenuto})
        (repo / "compose.yaml").write_text(_compose_con("a"))
        fuori = v._secrets_mancanti([repo / "compose.yaml"], repo)
        assert bool(fuori) is atteso_mancante, f"contenuto {contenuto!r}"


def test_ogni_segreto_reale_ha_una_natura_dichiarata():
    # IL PATTO CHE RENDE ACCETTABILE UNA LISTA SCRITTA A MANO: può invecchiare, ma non
    # in silenzio. Se una release aggiunge un segreto e nessuno lo classifica, il
    # messaggio d'errore non saprebbe se suggerire di generarlo — e suggerirlo a caso è
    # il modo in cui un rimedio fabbrica un guasto peggiore di quello che cura
    # (openssl rand su un token: file pieno, sbagliato, pre-flight verde).
    # Stesso patto del ledger features.yaml: non «ricordarsi», ma non poter dimenticare.
    classificati = v.SEGRETI_GENERABILI | set(v.SEGRETI_NON_GENERABILI)
    reali = set()
    for nome_file in ("compose.yaml", "compose.ingress.cloudflared.yaml"):
        righe = (_ROOT / nome_file).read_text(encoding="utf-8").splitlines()
        try:
            start = next(n for n, r in enumerate(righe) if r.rstrip() == "secrets:")
        except StopIteration:
            continue
        for r in righe[start + 1:]:
            if r.strip() and not r[:1].isspace():
                break
            s = r.strip()
            if s.endswith(":") and not s.startswith("#") and "file:" not in s:
                reali.add(s[:-1])
    assert reali, "nessun segreto letto dai compose: il test non sta misurando nulla"
    non_classificati = reali - classificati
    assert not non_classificati, (
        f"segreti senza natura dichiarata: {sorted(non_classificati)} — vanno aggiunti a "
        f"SEGRETI_GENERABILI o SEGRETI_NON_GENERABILI, altrimenti il rimedio del "
        f"pre-flight non sa se può suggerire di generarli")


def test_il_rimedio_non_suggerisce_mai_di_generare_un_segreto_non_generabile():
    # N13 (b82df434), metà collaudabile: il messaggio non deve MAI accostare un comando
    # generativo al nome di un segreto che non si può generare.
    src = (_ROOT / "tools" / "vps1777.py").read_text(encoding="utf-8")
    blocco = src[src.index("        righe = []"):src.index("    ok(f\"segreti richiesti")]
    for nome in v.SEGRETI_NON_GENERABILI:
        assert f"openssl rand -hex 32 > {nome}" not in blocco
    # e il ramo generativo esiste solo dentro il caso `in SEGRETI_GENERABILI`
    assert blocco.index("SEGRETI_NON_GENERABILI.get(nome)") < blocco.index("openssl rand"), \
        "il caso non-generabile deve essere valutato PRIMA di stampare un comando"


def test_assente_e_illeggibile_sono_due_stati_distinti():
    # 0.40.2 — il rimedio per «manca» (crealo, il `>` è sicuro) DISTRUGGE un segreto che
    # c'è ma non si legge. Fino alla 0.40.1 un `or` appiattiva i due casi e il messaggio
    # suggeriva il comando col `>` su un file integro. Misurato: 3 segreti pieni,
    # chmod 000 su uno ⇒ segnalato come «manca o è VUOTO».
    # ⚠️ Si distingue col dato che il codice HA GIÀ (`is_file()`), non enumerando le
    # cause: permessi, ACL, mount, immutable, symlink rotto — quella lista sarebbe
    # incompleta dal primo giorno.
    repo = _installazione(segreti={"pieno.txt": "v", "vuoto.txt": "  \n"})
    (repo / "compose.yaml").write_text(_compose_con("pieno", "vuoto", "sparito"))
    fuori = v._secrets_mancanti([repo / "compose.yaml"], repo)
    per_nome = {f.split(" → ")[0].strip(): f for f in fuori}
    assert "ASSENTE" in per_nome["sparito"], "un file che non c'è deve dirsi ASSENTE"
    assert "VUOTO" in per_nome["vuoto"], "un file di soli spazi deve dirsi VUOTO"
    assert "pieno" not in per_nome, "un segreto valido non si segnala"


def test_illeggibile_non_si_confonde_con_assente():
    # Il caso che il chmod 000 riproduce, senza dipendere dai permessi (che come root
    # non morderebbero): un percorso che esiste ma la cui lettura fallisce.
    import os
    if os.geteuid() == 0:
        return                                    # da root chmod non blocca: caso non riproducibile
    repo = _installazione(segreti={"chiuso.txt": "valore-vero-da-non-perdere"})
    (repo / "compose.yaml").write_text(_compose_con("chiuso"))
    (repo / "secrets" / "chiuso.txt").chmod(0o000)
    try:
        fuori = v._secrets_mancanti([repo / "compose.yaml"], repo)
        assert len(fuori) == 1, "un segreto illeggibile deve comunque fermare l'update"
        assert "NON LEGGIBILE" in fuori[0], f"deve distinguersi da ASSENTE: {fuori[0]}"
        assert "ASSENTE" not in fuori[0]
        # e il contenuto NON è stato toccato: è tutto il punto del fix
        (repo / "secrets" / "chiuso.txt").chmod(0o600)
        assert (repo / "secrets" / "chiuso.txt").read_text() == "valore-vero-da-non-perdere"
    finally:
        (repo / "secrets" / "chiuso.txt").chmod(0o600)


def test_directory_secrets_illeggibile_non_fa_crashare():
    # REGRESSIONE introdotta separando i rami e trovata da b82df434 sui due sha: prima
    # un unico `except OSError` copriva tutto (PermissionError ne è sottoclasse);
    # separando le diagnosi è caduto il caso in cui a non essere leggibile è il
    # CONTENITORE invece del contenuto. Il pre-flight moriva con uno stack trace, senza
    # scrivere lo step failed ⇒ pannello appeso su «running».
    # Stessa forma già chiusa per il bundle: **si protegge la porta che si conosce.**
    import os
    if os.geteuid() == 0:
        return
    repo = _installazione(segreti={"a.txt": "v", "b.txt": "v"})
    (repo / "compose.yaml").write_text(_compose_con("a", "b"))
    (repo / "secrets").chmod(0o000)
    try:
        fuori = v._secrets_mancanti([repo / "compose.yaml"], repo)   # non deve sollevare
        assert len(fuori) == 2
        assert all("DIRECTORY NON LEGGIBILE" in f for f in fuori), fuori
    finally:
        (repo / "secrets").chmod(0o700)


def test_il_rimedio_per_directory_illeggibile_non_tocca_i_file():
    src = (_ROOT / "tools" / "vps1777.py").read_text(encoding="utf-8")
    i = src.index('if "DIRECTORY NON LEGGIBILE" in m:')
    ramo = src[i:src.index("continue", i)]
    assert "ls -ld" in ramo, "deve far guardare la CARTELLA"
    assert "openssl rand" not in ramo and "> secrets/" not in ramo, \
        "nessun comando che scriva: i segreti sono intatti, è l'accesso a essere rotto"
    assert "NON ricreare" in ramo


def test_il_rimedio_per_illeggibile_non_contiene_mai_una_ridirezione():
    # N13 esteso: per «c'è ma non si legge» il messaggio non deve suggerire NESSUN
    # comando che scriva sul file — `>` troncherebbe il segreto che si vuole salvare.
    src = (_ROOT / "tools" / "vps1777.py").read_text(encoding="utf-8")
    i = src.index('if "NON LEGGIBILE" in m:')
    ramo = src[i:src.index("continue", i)]
    assert ">" not in ramo.split("ls -l")[0].split("chmod")[0] or "NON usare un comando con" in ramo
    assert "chmod" in ramo and "ls -l" in ramo, "deve indicare come riparare l'ACCESSO"
    assert "openssl rand" not in ramo, "non deve suggerire di rigenerare un file che esiste"


def test_stage_check_valida_gli_stessi_compose_che_lo_stack_monta():
    # 0.40.2 — lo step 8 costruiva la lista a mano (base + ingress) mentre `compose_cmd`
    # monta anche un overlay per feature attiva (`backup` è di default): validava MENO
    # compose di quanti ne sarebbero stati usati. Un `compose config` verde su un
    # sottoinsieme non dice nulla sull'insieme reale.
    src = (_ROOT / "tools" / "vps1777.py").read_text(encoding="utf-8")
    blocco = src[src.index('step(8, "stage-check")'):src.index("# 9 — pull")]
    assert "_compose_sorgenti(bundle, repo)" in blocco, \
        "lo stage-check deve DERIVARE la lista, non riscriverla"
    assert 'bundle / f"compose.{profile}.yaml"' not in blocco, \
        "la lista scritta a mano è il difetto: se torna, torna in silenzio"


def test_compose_sorgenti_base_assente_solleva_invece_di_dire_verde():
    # N6 / difetto (d): sulla base, nessun compose.yaml → [] = VERDE SILENZIOSO. Il ramo
    # non scattava mai perché repo/compose.yaml esiste sempre — ma puntando ai path del
    # BUNDLE (che è il fix) un fetch parziale lo rende raggiungibile: il fix
    # introdurrebbe un nuovo modo di avere lo stesso falso verde che sta riparando.
    vuota = Path(tempfile.mkdtemp())
    repo = _installazione()
    try:
        v._compose_sorgenti(vuota, repo)
        raise AssertionError("un bundle senza compose.yaml NON deve passare per verde")
    except FileNotFoundError as exc:
        assert "NON è un verde" in str(exc)


def test_compose_sorgenti_ignora_i_file_che_non_esistono():
    # Una release può non avere l'overlay di una feature attiva: non è una mancanza
    # di segreti, è un file che non c'è. Deve essere saltato, non farci esplodere.
    repo = _installazione(env="INGRESS_PROFILE=ingress.tailscale\nVPS1777_FEATURES=backup\n")
    (repo / "compose.yaml").write_text(_compose_con("base"))
    assert v._compose_sorgenti(repo, repo) == [repo / "compose.yaml"]


# ───────── H51: la sonda che guarda il gateway da FUORI del container ─────────
# Nasce dall'incidente del 27/07/2026: tutte le sonde dell'health-gate
# interrogavano il gateway dall'interno, dove la porta risponde sempre. Il gate
# ha dato verde per 1h28m su un servizio irraggiungibile, senza fare rollback.
# Questi test coprono i rami UNO PER UNO, incluso quello che il gate non vedeva.

def test_porta_esterna_il_caso_dell_incidente_nessuna_porta_e_nessun_proxy():
    """Il gateway non pubblica nulla e non c'è chi riceva al posto suo → ROSSO.

    È esattamente lo stato del 27/07: gateway su una sola rete `internal: true`,
    `ports:` accettata da docker e non applicata. Senza questo ramo l'intera
    funzione sarebbe decorativa — è l'unico caso per cui è stata scritta.
    """
    ok, perche = v.valuta_porta_esterna("", ["gateway", "archive-mcp"], None)
    assert ok is False
    assert "internal" in perche          # dice la causa, non solo l'esito
    assert "nessuno può ricevere traffico" in perche


def test_porta_esterna_pubblicata_e_risponde():
    ok, perche = v.valuta_porta_esterna("127.0.0.1:8080", ["gateway"], 200)
    assert ok is True
    assert "127.0.0.1:8080" in perche


def test_porta_esterna_pubblicata_ma_dietro_non_risponde_nessuno():
    """Pubblicata ≠ servita: docker-proxy tiene il listener anche a vuoto."""
    ok, perche = v.valuta_porta_esterna("127.0.0.1:8080", ["gateway"], 0)
    assert ok is False
    assert "non c'è nessuno" in perche


def test_porta_esterna_pubblicata_ma_risponde_male():
    ok, perche = v.valuta_porta_esterna("127.0.0.1:8080", ["gateway"], 503)
    assert ok is False
    assert "503" in perche


def test_porta_esterna_non_si_applica_quando_riceve_un_proxy_in_container():
    """Con caddy/cloudflared il gateway NON deve pubblicare: qui zero porte è
    lo stato corretto, e un rosso sarebbe un rollback provocato dal presidio."""
    for proxy in ("caddy", "cloudflared"):
        ok, perche = v.valuta_porta_esterna("", ["gateway", proxy], None)
        assert ok is True, f"{proxy}: falso rosso → rollback non necessario"
        assert proxy in perche


def test_porta_esterna_non_misurata_non_e_un_fallimento():
    """Fail solo con evidenza POSITIVA del guasto: «non ho misurato» non è
    «è rotto» — un falso rosso qui costa un rollback."""
    ok, perche = v.valuta_porta_esterna("127.0.0.1:8080", ["gateway"], None)
    assert ok is True
    assert "non misurata" in perche


def test_health_gate_interroga_davvero_la_porta_dall_esterno():
    """Il collegamento è cablato: se qualcuno togliesse la chiamata da
    health_gate, i test qui sopra resterebbero verdi su codice morto."""
    import inspect
    sorgente = inspect.getsource(v.health_gate)
    assert "porta_esterna_ok" in sorgente


# ───── H49 ③: l'interruttore d'emergenza cosign lasciato aperto e dimenticato ─────
# La voce H49 dichiarava il buco dal 04/07 e diceva "non ancora implementato".
# Questi test coprono i rami uno per uno, compresa la sparizione automatica della
# voce quando l'operatore rimette la verifica — che è la parte che nessuno
# ricontrolla mai, e senza la quale l'avviso resterebbe acceso per sempre.

def _repo_con_env(tmp: Path, contenuto: str) -> Path:
    (tmp / ".env").write_text(contenuto)
    return tmp


def test_cosign_bypass_assente_non_produce_nessuna_voce():
    """Il caso normale: nessuna flag, nessun rumore sulla pagina."""
    with tempfile.TemporaryDirectory() as td:
        repo = _repo_con_env(Path(td), "VPS1777_REQUIRE_COSIGN=1\n")
        assert v.cosign_bypass_status(repo) is None


def test_cosign_bypass_env_mancante_non_e_un_errore():
    """Repo senza .env (macchina non ancora configurata): best-effort, non crash."""
    with tempfile.TemporaryDirectory() as td:
        assert v.cosign_bypass_status(Path(td)) is None


def test_cosign_bypass_attivo_arma_il_marcatore_e_parte_da_zero_giorni():
    """Prima volta che il CLI la vede: la voce compare, l'età è 0, e NON è
    ancora scaduta — mettere la flag durante una crisi non deve subito
    suonare l'allarme che riguarda il dimenticarsela."""
    with tempfile.TemporaryDirectory() as td:
        repo = _repo_con_env(Path(td), "VPS1777_REQUIRE_COSIGN=0\n")
        it = v.cosign_bypass_status(repo)
        assert it is not None
        assert it["age_days"] == 0 and it["overdue"] is False
        assert (repo / "onboarding" / v._COSIGN_BYPASS_MARKER).is_file()


def test_cosign_bypass_dimenticato_diventa_scaduto():
    """Il caso per cui la voce esiste: la flag è lì da più giorni della soglia."""
    with tempfile.TemporaryDirectory() as td:
        repo = _repo_con_env(Path(td), "VPS1777_REQUIRE_COSIGN=0\n")
        v.cosign_bypass_status(repo)                      # arma il marcatore
        marker = repo / "onboarding" / v._COSIGN_BYPASS_MARKER
        import datetime as _dt
        vecchio = v.datetime.now(v.timezone.utc) - _dt.timedelta(days=9)
        marker.write_text(vecchio.strftime("%Y-%m-%dT%H:%M:%SZ") + "\n")
        it = v.cosign_bypass_status(repo)
        assert it["age_days"] == 9 and it["overdue"] is True


def test_cosign_bypass_rimosso_fa_sparire_la_voce_e_il_marcatore():
    """CONTROPROVA: l'operatore rimette la verifica → la voce sparisce da sola.
    Senza questo ramo l'avviso, una volta acceso, non si spegnerebbe più — e un
    avviso che non si spegne smette di essere letto."""
    with tempfile.TemporaryDirectory() as td:
        repo = _repo_con_env(Path(td), "VPS1777_REQUIRE_COSIGN=0\n")
        v.cosign_bypass_status(repo)
        marker = repo / "onboarding" / v._COSIGN_BYPASS_MARKER
        assert marker.is_file()
        _repo_con_env(repo, "VPS1777_REQUIRE_COSIGN=1\n")
        assert v.cosign_bypass_status(repo) is None
        assert not marker.exists(), "il marcatore resta e l'età ripartirebbe sbagliata"


def test_cosign_bypass_marcatore_illeggibile_non_fa_crashare_il_check():
    """Non crashare NON vuol dire sparire: il bypass è attivo e va detto lo stesso.

    🔴 QUESTO TEST PRETENDEVA `is None`, E CRISTALLIZZAVA UN DIFETTO. `None` per
    contratto significa «la via d'emergenza NON è attiva» — mentre qui il `.env`
    dice `VPS1777_REQUIRE_COSIGN=0`, cioè il contrario. `cmd_secrets_status` fa
    `if cosign is not None`, quindi con un marcatore corrotto la riga spariva da
    /admin/secrets, dal JSON e dal Telegram settimanale, e l'ultima parola era
    «tutti i secret entro la soglia».
    ⭐ «Non so DA QUANDO» e «non è attivo» erano lo stesso valore. Il test copriva
    solo la metà innocua della domanda («non crasha?») e la sua motivazione scritta
    rendeva l'altra metà invisibile.
    🛡️ `overdue=True`: non sapere da quanto dura una via d'emergenza è PEGGIO che
    saperlo, non meglio.
    """
    with tempfile.TemporaryDirectory() as td:
        repo = _repo_con_env(Path(td), "VPS1777_REQUIRE_COSIGN=0\n")
        v.cosign_bypass_status(repo)
        (repo / "onboarding" / v._COSIGN_BYPASS_MARKER).write_text("ieri sera\n")
        it = v.cosign_bypass_status(repo)
        assert it is not None, (
            "il bypass è ATTIVO nel .env: sparire dalla pagina è peggio che "
            "mostrare un'età sconosciuta"
        )
        assert it["age_days"] is None, "l'età non è nota: non si inventa uno zero"
        assert it["overdue"] is True, "non sapere da quando dura è peggio, non meglio"
        assert "ILLEGGIBILE" in it["note"], it["note"]


def test_cosign_bypass_non_attivo_resta_None():
    """Il verso opposto: la cura non deve far comparire la voce quando il bypass
    non c'è — sarebbe un promemoria per una cosa che nessuno ha fatto."""
    with tempfile.TemporaryDirectory() as td:
        repo = _repo_con_env(Path(td), "VPS1777_REQUIRE_COSIGN=1\n")
        assert v.cosign_bypass_status(repo) is None


def test_cosign_bypass_ha_le_chiavi_che_le_pagine_leggono_davvero():
    """La trappola del consumatore: /admin/secrets e la Mini App iterano sulle
    voci e leggono chiavi FISSE. Una chiave con un altro nome non dà errore da
    nessuna parte — la riga esce semplicemente vuota, o la voce non conta come
    scaduta. Qui la forma si confronta con quella di una voce già in pagina."""
    with tempfile.TemporaryDirectory() as td:
        repo = _repo_con_env(Path(td), "VPS1777_REQUIRE_COSIGN=0\n")
        it = v.cosign_bypass_status(repo)
    lette_dalle_pagine = {"name", "label", "age_days", "max_age_days",
                          "overdue", "auto_rotatable", "note", "last_rotated"}
    assert lette_dalle_pagine <= set(it), f"mancano: {lette_dalle_pagine - set(it)}"


def test_cosign_bypass_e_cablato_nel_check_settimanale():
    """Il collegamento: senza la chiamata dentro cmd_secrets_status i test qui
    sopra resterebbero verdi su una funzione che nessuno invoca — e il timer
    settimanale, l'unico che gira da solo, non direbbe niente."""
    import inspect
    sorgente = inspect.getsource(v.cmd_secrets_status)
    assert "cosign_bypass_status" in sorgente


def test_cosign_bypass_non_e_fatale_e_non_riarma_da_solo():
    """Scelta deliberata contro il suggerimento del round-7bis (TTL che forza il
    ri-armo): la via d'emergenza deve restare percorribile finché la crisi dura.
    Se un domani qualcuno la rendesse fatale, questo test glielo ricorda."""
    import inspect
    sorgente = inspect.getsource(v.cosign_bypass_status)
    assert "die(" not in sorgente
    assert "env_set(" not in sorgente, "il check non deve RISCRIVERE il .env dell'operatore"


# ───── H51 (b): la porta guardata da fuori anche quando NON si aggiorna ─────
# Il gate esterno della 0.40.6 guarda solo durante un update. Il 27/07 il guasto
# è durato 1h27m50s e ad accorgersene è stata una persona che apriva l'indirizzo.
# Questi test coprono le TRANSIZIONI, che sono la cosa che si sbaglia: non notificare
# ogni giorno lo stesso guasto, e non tacere quando torna su.

class _Spia:
    """Sostituisce telegram_notify: raccoglie i messaggi invece di spedirli."""

    def __init__(self):
        self.messaggi = []

    def __call__(self, repo, testo):
        self.messaggi.append(testo)


def _con_sonda(monkey_ok: bool, perche: str = ""):
    """Installa una porta_esterna_ok finta e una spia sulle notifiche.
    Ritorna (spia, ripristina)."""
    spia = _Spia()
    orig_sonda, orig_notify = v.porta_esterna_ok, v.telegram_notify
    v.porta_esterna_ok = lambda repo, env=None: (monkey_ok, perche)
    v.telegram_notify = spia

    def ripristina():
        v.porta_esterna_ok, v.telegram_notify = orig_sonda, orig_notify

    return spia, ripristina


def test_raggiungibilita_caduta_segna_l_istante_e_avvisa_una_volta():
    spia, ripristina = _con_sonda(False, "nessuna porta pubblicata")
    try:
        st = {}
        v._sorveglia_raggiungibilita(Path("/non/serve"), st, True)
        assert st.get("irraggiungibile_da"), "senza l'istante la durata non si può misurare"
        assert len(spia.messaggi) == 1
        primo_istante = st["irraggiungibile_da"]
        # secondo giro con lo stesso guasto: NON deve rinotificare né spostare l'istante
        v._sorveglia_raggiungibilita(Path("/non/serve"), st, True)
        assert len(spia.messaggi) == 1, "una notifica al giorno per lo stesso guasto è rumore"
        assert st["irraggiungibile_da"] == primo_istante, (
            "spostare l'istante a ogni giro farebbe misurare 0 di durata al ritorno")
    finally:
        ripristina()


def test_raggiungibilita_ritorno_misura_la_durata_fra_i_due_istanti():
    """CONTROPROVA della caduta: senza questo ramo l'avviso resterebbe acceso e
    nessuno saprebbe quanto è durato — che è esattamente il numero che il 27/07
    abbiamo dedotto sbagliando di dodici minuti."""
    import datetime as _dt
    spia, ripristina = _con_sonda(True, "raggiungibile")
    try:
        giu = (v.datetime.now(v.timezone.utc) - _dt.timedelta(hours=1, minutes=27, seconds=50))
        st = {"irraggiungibile_da": giu.strftime("%Y-%m-%dT%H:%M:%SZ")}
        v._sorveglia_raggiungibilita(Path("/non/serve"), st, True)
        assert "irraggiungibile_da" not in st, "il marcatore resta e il prossimo guasto misura male"
        assert len(spia.messaggi) == 1
        # 🔴 QUI C'ERA `assert "1h27m50s" in ...`, ED ERA FLAKY (trovato il 02/08
        # aggiungendo due test altrove, che hanno rallentato la suite di un secondo).
        # Il test costruisce l'istante con `now()` e il codice ne legge un ALTRO:
        # se fra le due letture scatta un secondo, la durata è 1h27m**51**s e
        # l'assert cade. ⭐ Misurava la velocità della macchina, non la durata.
        # 🛡️ Adesso pretende il valore ENTRO UNA FINESTRA DICHIARATA: la cosa che
        # questo test esiste per provare è che la durata sia MISURATA fra i due
        # istanti e non stimata — e due secondi di tolleranza non la indeboliscono,
        # mentre un secondo di rigidità la rendeva rossa a caso.
        import re as _re
        m = _re.search(r"(\d+)h(\d+)m(\d+)s", spia.messaggi[0])
        assert m, f"la durata non è nemmeno nel messaggio: {spia.messaggi[0]}"
        secondi = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        atteso = 1 * 3600 + 27 * 60 + 50
        assert atteso <= secondi <= atteso + 2, (
            f"durata {secondi}s fuori dalla finestra [{atteso}, {atteso + 2}]: "
            f"{spia.messaggi[0]}"
        )
    finally:
        ripristina()


def test_raggiungibilita_servizio_sano_non_dice_niente():
    """Il caso normale: nessun rumore. Un avviso che arriva anche quando va tutto
    bene è un avviso che si impara a ignorare."""
    spia, ripristina = _con_sonda(True, "raggiungibile")
    try:
        st = {}
        v._sorveglia_raggiungibilita(Path("/non/serve"), st, True)
        assert st == {} and spia.messaggi == []
    finally:
        ripristina()


def test_raggiungibilita_non_misurata_non_e_un_allarme():
    """`porta_esterna_ok` torna True quando non ha potuto misurare: la regola è
    fallire solo con evidenza POSITIVA del guasto. Qui un falso rosso sveglia una
    persona di notte per niente, e la volta dopo non la sveglia più."""
    spia, ripristina = _con_sonda(True, "porta pubblicata, risposta non misurata")
    try:
        st = {}
        v._sorveglia_raggiungibilita(Path("/non/serve"), st, True)
        assert spia.messaggi == []
    finally:
        ripristina()


def test_raggiungibilita_senza_notify_non_spedisce_ma_segna_lo_stesso():
    """`vps1777 check` a mano non deve mandare Telegram — ma l'istante va segnato
    comunque, o il giro successivo del timer crederebbe che sia appena caduto."""
    spia, ripristina = _con_sonda(False, "giù")
    try:
        st = {}
        v._sorveglia_raggiungibilita(Path("/non/serve"), st, False)
        assert spia.messaggi == []
        assert st.get("irraggiungibile_da")
    finally:
        ripristina()


def test_funnel_non_applicabile_solo_se_NESSUN_indirizzo_pubblico_e_dichiarato():
    """«Non applicabile» è onesto solo quando non c'è NIENTE da sondare.

    🔴 QUESTO TEST CRISTALLIZZAVA IL DIFETTO (corretto il 02/08). Il suo docstring
    diceva che con caddy/cloudflared «non applicabile» era «lo stato corretto su quel
    profilo» — e su quella frase la sorveglianza giornaliera restava con **zero sonde
    su due profili d'ingresso su tre**: `porta_esterna_ok` esce al primo `if` per i
    proxy, `funnel_ok` usciva qui. Un caddy morto non mandava nessuna notifica.
    ⭐ Il test passava, ed era il test a essere sbagliato: descriveva come voluto un
    comportamento che nessuno aveva scelto. *Un caso a risposta nota vale quanto la
    risposta che ci si è scritti accanto.*
    """
    orig_nome, orig_env = v.nome_pubblico_funnel, v.env_read
    v.nome_pubblico_funnel = lambda: ""
    v.env_read = lambda repo: {}                  # nessun PUBLIC_BASE: davvero niente
    try:
        raggiungibile, perche = v.funnel_ok(Path("/non/serve"))
        assert raggiungibile is True
        assert "non applicabile" in perche
    finally:
        v.nome_pubblico_funnel, v.env_read = orig_nome, orig_env


def test_con_caddy_la_sonda_USA_public_base_invece_di_arrendersi():
    """IL caso che il difetto lasciava scoperto: niente Tailscale, ma un indirizzo
    pubblico c'è ed è nel `.env` (`deploy.sh` lo scrive come `https://$CADDY_DOMAIN`).
    La sonda deve interrogare QUELLO, non dichiararsi inapplicabile."""
    chiamate = []
    orig_nome, orig_env = v.nome_pubblico_funnel, v.env_read
    orig_urlopen, orig_sleep = v.urllib.request.urlopen, v.time.sleep
    v.nome_pubblico_funnel = lambda: ""
    v.env_read = lambda repo: {"PUBLIC_BASE": "https://esempio.invalid/"}
    def _rifiuta(req, timeout=0):
        chiamate.append(req.full_url)
        raise v.urllib.error.URLError("rete assente")
    v.urllib.request.urlopen = _rifiuta
    v.time.sleep = lambda s: None
    try:
        raggiungibile, perche = v.funnel_ok(Path("/non/serve"), tentativi=1)
        assert chiamate, "con PUBLIC_BASE la sonda DEVE uscire: non l'ha fatto"
        assert chiamate[0] == "https://esempio.invalid/health", chiamate[0]
        assert raggiungibile is False
        assert "non applicabile" not in perche
    finally:
        v.nome_pubblico_funnel, v.env_read = orig_nome, orig_env
        v.urllib.request.urlopen, v.time.sleep = orig_urlopen, orig_sleep


def test_un_public_base_malformato_non_diventa_un_bersaglio():
    """Un URL inventato non si sonda — ma «non applicabile» NON copre tutti i casi.

    🔴 IL DOCSTRING DI QUESTO TEST GIUSTIFICAVA UN BUCO, e l'avevo scritto io col
    fix `3600b07`: diceva «meglio "non applicabile" di un falso rosso», e su quella
    frase **`cloudflared` restava senza NESSUNA sonda** — `setup.sh:117` scrive
    `PUBLIC_BASE=""` per quel profilo, quindi ricadeva sempre qui. La cura copriva
    `caddy` (che il `PUBLIC_BASE` ce l'ha, deploy.sh:440) e si fermava lì.
    ⭐ Cioè: nel test della cura di un difetto di questa classe avevo scritto la
    frase che protegge il pezzo di difetto rimasto. Vedi il test qui sotto.
    """
    orig_nome, orig_env = v.nome_pubblico_funnel, v.env_read
    v.nome_pubblico_funnel = lambda: ""
    try:
        for valore in ("", "   ", "esempio.invalid", "ftp://esempio.invalid"):
            v.env_read = lambda repo, _v=valore: {"PUBLIC_BASE": _v}
            raggiungibile, perche = v.funnel_ok(Path("/non/serve"))
            assert raggiungibile is True and "non applicabile" in perche, valore
    finally:
        v.nome_pubblico_funnel, v.env_read = orig_nome, orig_env


def test_funnel_giu_e_un_rosso_dopo_piu_di_un_tentativo():
    """Un singolo errore di rete verso Internet è comune: la sonda riprova, e solo
    se insiste dichiara giù. Il conteggio delle chiamate è la prova che riprova
    davvero — senza, «tentativi=2» sarebbe un parametro decorativo."""
    chiamate = []
    orig_nome, orig_urlopen = v.nome_pubblico_funnel, v.urllib.request.urlopen
    v.nome_pubblico_funnel = lambda: "esempio.invalid"
    def _rifiuta(req, timeout=0):
        chiamate.append(1)
        raise v.urllib.error.URLError("rete assente")
    v.urllib.request.urlopen = _rifiuta
    orig_sleep = v.time.sleep
    v.time.sleep = lambda s: None
    try:
        raggiungibile, perche = v.funnel_ok(Path("/non/serve"), tentativi=2)
        assert raggiungibile is False
        assert len(chiamate) == 2, f"un solo tentativo: {len(chiamate)}"
        assert "non risponde" in perche
    finally:
        v.nome_pubblico_funnel, v.urllib.request.urlopen = orig_nome, orig_urlopen
        v.time.sleep = orig_sleep


def test_funnel_la_sorveglianza_lo_interroga_dopo_la_porta_non_al_posto_suo():
    """L'ordine è il fix: prima la porta sull'host (il guasto del 27/07), POI il
    tunnel. Sostituire l'una con l'altro lascerebbe scoperto il caso misurato."""
    import inspect
    src = inspect.getsource(v._sorveglia_raggiungibilita)
    assert "porta_esterna_ok" in src and "funnel_ok" in src
    assert src.index("porta_esterna_ok") < src.index("funnel_ok")


def test_le_prove_empiriche_viaggiano_nel_pacchetto_di_rilascio():
    """H51 (d): sono l'unico strumento che misura sul SISTEMA VIVO ciò che gli altri
    gate verificano leggendo file, e restavano nel repo di sviluppo — sulla macchina
    andavano copiate a mano, quindi non c'erano. Un presidio che per essere usato
    richiede un gesto manuale, nel giorno del guasto non esiste.

    ⚠️ LIMITE DICHIARATO: questo test legge una stringa nel workflow, non costruisce
    il pacchetto. È esattamente la classe che H52 denuncia — un'etichetta di testo al
    posto del comportamento — e la sola cosa verificabile senza far girare la CI.
    Prende «qualcuno ha tolto la riga», non «il tar è arrivato completo»."""
    wf = (_ROOT / ".github" / "workflows" / "release.yml").read_text()
    assert "cp -r tools/prove-empiriche bundle/tools/" in wf, (
        "le prove non entrano più nel bundle: sulla macchina tornerebbero assenti")
    # e devono esistere davvero: una riga che copia una cartella vuota è verde e inutile
    prove = sorted((_ROOT / "tools" / "prove-empiriche").glob("prova-*.sh"))
    assert len(prove) >= 8, f"solo {len(prove)} prove trovate"


def test_funnel_non_e_nel_cancello_dell_update():
    """SCELTA DELIBERATA, e un test la tiene ferma: l'health-gate giudica ciò che
    l'update può rompere. Il tunnel non lo tocca un update — e un suo singhiozzo
    farebbe tornare indietro una versione sana. Se un domani qualcuno lo aggiunge
    lì, questo test glielo ricorda."""
    import inspect
    assert "funnel_ok" not in inspect.getsource(v.health_gate)


def test_raggiungibilita_e_cablata_in_check_e_prima_del_fetch():
    """Il collegamento, e l'ORDINE: dev'essere chiamata prima di `latest_release`,
    perché quando GitHub è irraggiungibile `cmd_check` esce subito — e quel giorno
    è proprio il più probabile per un guasto."""
    import inspect
    src = inspect.getsource(v.cmd_check)
    assert "_sorveglia_raggiungibilita" in src
    assert src.index("_sorveglia_raggiungibilita") < src.index("latest_release("), (
        "chiamata dopo il fetch: su GitHub irraggiungibile non verrebbe mai eseguita")


# ───── H55: la telemetria non fa cadere una riparazione ─────
# Misurato sulla VPS il 27/07 aggiornando davvero: `update_progress.json` era di
# root (lo lascia così il timer automatico, che gira da root) mentre il resto di
# onboarding/ è dell'utente del servizio. Il comando manuale che sta nella
# documentazione moriva allo step 4 con un traceback Python — un aggiornamento,
# cioè una riparazione, abortito da un file che serve solo a DISEGNARE una barra.

def _onboarding_non_scrivibile(tmp: Path) -> Path:
    """Un repo finto la cui `onboarding/` non si può scrivere. Se il test gira da
    root il permesso non morde: in quel caso si salta invece di dare un verde
    falso — un test che non può fallire è la classe che H53 denuncia."""
    (tmp / "compose.yaml").write_text("services: {}\n")
    ob = tmp / "onboarding"
    ob.mkdir()
    ob.chmod(0o500)          # r-x: si entra, non si scrive
    return ob


def test_progress_write_non_uccide_l_update_se_non_puo_scrivere():
    if os.geteuid() == 0:
        return  # da root il chmod non morde: il caso non è riproducibile qui
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        ob = _onboarding_non_scrivibile(repo)
        try:
            v._TELEMETRIA_MUTA = False
            v.progress_write(repo, "0.0.1", 4, "preflight-secrets", "running")
            v.status_write(repo, current="0.0.1")
        finally:
            ob.chmod(0o700)
        # nessuna eccezione: è tutto il punto. Prima moriva con PermissionError.


def test_progress_write_avvisa_una_volta_sola_e_non_quindici():
    """Un update ha quindici step: quindici righe identiche seppelliscono il resto
    dell'output proprio quando serve leggerlo."""
    if os.geteuid() == 0:
        return
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        ob = _onboarding_non_scrivibile(repo)
        avvisi = []
        orig_warn = v.warn
        v.warn = lambda m: avvisi.append(m)
        try:
            v._TELEMETRIA_MUTA = False
            for n in range(1, 16):
                v.progress_write(repo, "0.0.1", n, f"step-{n}", "running")
        finally:
            v.warn = orig_warn
            ob.chmod(0o700)
        assert len(avvisi) == 1, f"{len(avvisi)} avvisi per lo stesso guasto"
        assert "prosegue" in avvisi[0], avvisi[0]


def test_progress_write_scrive_davvero_quando_puo():
    """CONTROPROVA: senza questa, «non solleva mai» sarebbe soddisfatto anche da
    una funzione che non scrive nulla — il verde perfetto di chi non fa niente."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / "compose.yaml").write_text("services: {}\n")
        v._TELEMETRIA_MUTA = False
        v.progress_write(repo, "0.40.7", 4, "preflight-secrets", "running", "det")
        letto = json.loads((repo / "onboarding" / "update_progress.json").read_text())
        assert letto["step"] == 4 and letto["target"] == "0.40.7"
        assert letto["step_name"] == "preflight-secrets" and letto["detail"] == "det"


def test_progress_write_il_caso_esatto_della_vps_cartella_ok_file_no():
    """LA RIPRODUZIONE FEDELE, non un'approssimazione: sulla VPS la cartella era
    scrivibile e il singolo FILE no (di root, lasciato dal timer automatico). I due
    test qui sopra rendono non scrivibile la CARTELLA — stessa classe, meccanismo
    diverso, e un fix che coprisse solo quello sarebbe verde sul caso sbagliato."""
    if os.geteuid() == 0:
        return
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / "compose.yaml").write_text("services: {}\n")
        (repo / "onboarding").mkdir()
        f = repo / "onboarding" / "update_progress.json"
        f.write_text("{}\n")
        f.chmod(0o400)                       # cartella scrivibile, file no
        try:
            v._TELEMETRIA_MUTA = False
            v.progress_write(repo, "0.40.7", 4, "preflight-secrets", "running")
        finally:
            f.chmod(0o600)
        assert f.read_text() == "{}\n", "il file non doveva cambiare, e l'update non doveva morire"


def test_status_write_sopravvive_a_un_file_corrotto():
    """La lettura può fallire quanto la scrittura: un JSON troncato da un'uscita
    brusca non deve impedire di scriverne uno buono."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / "compose.yaml").write_text("services: {}\n")
        (repo / "onboarding").mkdir()
        (repo / "onboarding" / "update_status.json").write_text('{"current": "0.4')
        v._TELEMETRIA_MUTA = False
        v.status_write(repo, current="0.40.7")
        letto = json.loads((repo / "onboarding" / "update_status.json").read_text())
        assert letto["current"] == "0.40.7"


# ───── il runner diretto vedeva 32 test su 39: il presidio del presidio ─────

def test_il_runner_diretto_esegue_tutti_i_test_del_file():
    """MISURATO il 27/07: `python3 tools/tests/test_vps1777.py` ne eseguiva 32,
    pytest 39. Il blocco `__main__` stava a metà file e itera su `globals()` —
    le funzioni definite DOPO non esistono ancora quando gira, e il runner
    stampava «ok» per tutto uscendo 0. I sette test invisibili erano i più
    recenti: quelli scritti lo stesso giorno per l'incidente.

    Non basta averlo spostato in fondo: la trappola torna al prossimo `append`.
    Questo test la chiude — se qualcuno aggiunge un test sotto il blocco, va
    rosso subito e dice dove."""
    import ast
    sorgente = Path(__file__).read_text()
    albero = ast.parse(sorgente)
    ultimo_test = max((n.lineno for n in albero.body
                       if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")),
                      default=0)
    blocchi_main = [n.lineno for n in albero.body
                    if isinstance(n, ast.If) and "__main__" in ast.dump(n.test)]
    assert blocchi_main, "il blocco di esecuzione diretta è sparito"
    assert blocchi_main[0] > ultimo_test, (
        f"il blocco __main__ è alla riga {blocchi_main[0]} ma c'è un test alla "
        f"{ultimo_test}: l'esecuzione diretta non lo vedrebbe e uscirebbe 0 lo stesso")


# ────────── H58: lo spazio richiesto da un update si STIMA, non si indovina ──
# Casi costruiti di cui la risposta è nota prima di eseguirli — compresi quelli
# che la funzione deve lasciar passare e quelli che non la riguardano.

def _repo_con_backup(d: str, *dimensioni: int) -> Path:
    repo = Path(d)
    (repo / "backups").mkdir(parents=True, exist_ok=True)
    for i, n in enumerate(dimensioni):
        (repo / "backups" / f"vps1777-2026-07-2{i}-030000.tar.age").write_bytes(b"\0" * n)
    return repo


def test_spazio_senza_backup_ricade_sul_minimo_e_lo_dice():
    # RISPOSTA NOTA: niente da cui stimare ⇒ il pavimento storico, e il perché
    # deve dire che è una ricaduta, non una misura. Una soglia che non distingue
    # «misurata» da «di default» fa credere a un dato che non c'è.
    with tempfile.TemporaryDirectory() as d:
        serve, perche = v.spazio_richiesto_update(Path(d))
    assert serve == v.SPAZIO_MINIMO_UPDATE
    assert "nessun backup" in perche


def test_spazio_scala_col_backup_piu_grande():
    # RISPOSTA NOTA: un update scrive DUE oggetti della taglia dei dati —
    # l'archivio cifrato e lo snapshot pre-update — più 1 GiB di margine.
    # È il caso misurato in produzione il 27/07: la vecchia costante di 5 GiB
    # stava SOTTO il costo reale dell'operazione che doveva sorvegliare.
    with tempfile.TemporaryDirectory() as d:
        repo = _repo_con_backup(d, 3 * 1024**3, 1024**3)   # 3 GiB e 1 GiB
        serve, perche = v.spazio_richiesto_update(repo)
    assert serve == 2 * 3 * 1024**3 + 1024**3, "deve usare il PIÙ GRANDE, non l'ultimo né la somma"
    assert serve > v.SPAZIO_MINIMO_UPDATE, "con dati grandi la stima deve superare la vecchia costante"
    assert "3.0 GiB" in perche


def test_spazio_col_backup_minuscolo_tiene_comunque_il_pavimento():
    # CIÒ CHE DEVE LASCIAR PASSARE: un'installazione quasi vuota non deve far
    # scendere la guardia sotto il minimo storico. Una stima che può solo
    # crescere è una stima; una che può anche crollare è un permesso.
    with tempfile.TemporaryDirectory() as d:
        repo = _repo_con_backup(d, 1024)   # 1 KiB
        serve, _ = v.spazio_richiesto_update(repo)
    assert serve == v.SPAZIO_MINIMO_UPDATE


def test_spazio_ignora_cio_che_non_e_un_backup():
    # CIÒ CHE NON LA RIGUARDA: nella stessa cartella vivono gli snapshot
    # pre-update e i log. Contarli gonfierebbe la soglia fino a bloccare update
    # legittimi — un falso rosso su un canale di aggiornamento è un canale
    # fermo, che è il modo in cui una macchina resta indietro sulle patch.
    with tempfile.TemporaryDirectory() as d:
        repo = _repo_con_backup(d, 1024)
        (repo / "backups" / "un-file-enorme.tar").write_bytes(b"\0" * 9 * 1024**3)
        (repo / "backups" / "pre-update").mkdir()
        serve, _ = v.spazio_richiesto_update(repo)
    assert serve == v.SPAZIO_MINIMO_UPDATE, "solo i vps1777-*.tar.age contano"


# ── H59: la copertura dei backup, e l'allarme che NON deve suonare a vuoto ───

def _repo_con_giorni(d: str, *nomi: str) -> Path:
    repo = Path(d)
    (repo / "backups").mkdir(parents=True, exist_ok=True)
    for n in nomi:
        (repo / "backups" / f"vps1777-{n}.tar.age").write_bytes(b"x")
    return repo


def test_copertura_conta_giorni_non_file():
    # RISPOSTA NOTA: sette file di un giorno solo sono UN giorno. È il difetto
    # H57 riportato al livello della misura — se la sonda contasse i file,
    # ripeterebbe l'errore che esiste per sorvegliare.
    with tempfile.TemporaryDirectory() as d:
        repo = _repo_con_giorni(d, *[f"2026-07-27-0{h}0000" for h in range(1, 8)])
        quanti, primo, ultimo = v.copertura_backup(repo)
    assert (quanti, primo, ultimo) == (1, "2026-07-27", "2026-07-27")


def test_copertura_ignora_nomi_illeggibili_e_altri_file():
    # CIÒ CHE NON LA RIGUARDA: nella stessa cartella vivono gli snapshot e i log.
    with tempfile.TemporaryDirectory() as d:
        repo = _repo_con_giorni(d, "2026-07-26-030000", "2026-07-27-030000", "non-una-data")
        (repo / "backups" / "appunti.txt").write_bytes(b"x")
        quanti, primo, ultimo = v.copertura_backup(repo)
    assert (quanti, primo, ultimo) == (2, "2026-07-26", "2026-07-27")


def test_cartella_illeggibile_NON_e_zero_giorni():
    # 🔴 IL FALSO ALLARME PEGGIORE CHE QUESTO PRESIDIO POTESSE PRODURRE, trovato
    # da abdd732a leggendo il codice il giorno stesso in cui è nato: `Path.glob`
    # su una cartella senza permessi NON solleva — restituisce vuoto. «Zero file»
    # e «zero permessi» collassavano nello stesso valore, e la sorveglianza
    # leggeva quel collasso come «i tuoi backup sono spariti».
    # ⚠️ Il precedente non è teorico: H55, stesso pattern root-contro-utente, ha
    # ucciso un update vero la mattina del 27/07.
    with tempfile.TemporaryDirectory() as d:
        repo = _repo_con_giorni(d, "2026-07-26-030000", "2026-07-27-030000")
        os.chmod(repo / "backups", 0o000)
        try:
            quanti, _, _ = v.copertura_backup(repo)
            st = {"copertura_max": 7}
            v._sorveglia_copertura_backup(repo, st, notifica=False)
        finally:
            os.chmod(repo / "backups", 0o755)
    assert quanti is None, "illeggibile deve essere NON MISURATO, non zero"
    assert "copertura_scesa_da" not in st, "una domanda senza risposta non è una risposta cattiva"
    assert st.get("copertura_cieca_da"), "la cecità va segnata, non taciuta"
    assert st["copertura_max"] == 7, "un dato che non c'è non deve toccare il massimo storico"


def test_cartella_assente_e_davvero_zero():
    # CIÒ CHE NON LA RIGUARDA: nessuna cartella = nessun backup, ed è un dato
    # vero. Su un'installazione nuova non allarma comunque, perché anche il
    # massimo storico è zero.
    with tempfile.TemporaryDirectory() as d:
        quanti, _, _ = v.copertura_backup(Path(d))
        st = {}
        v._sorveglia_copertura_backup(Path(d), st, notifica=False)
    assert quanti == 0
    assert "copertura_scesa_da" not in st


def test_la_cecita_si_chiude_quando_torna_leggibile():
    # Il rientro pulisce lo stato, o l'avviso resta acceso per sempre.
    with tempfile.TemporaryDirectory() as d:
        repo = _repo_con_giorni(d, "2026-07-26-030000", "2026-07-27-030000")
        st = {"copertura_max": 2, "copertura_cieca_da": "2026-07-27T00:00:00Z"}
        v._sorveglia_copertura_backup(repo, st, notifica=False)
    assert "copertura_cieca_da" not in st


def test_finestra_che_si_riempie_NON_fa_scattare_l_allarme():
    # ⭐ IL CASO CHE DECIDE SE IL PRESIDIO VERRÀ LETTO O DISATTIVATO.
    # Installazione nuova: copertura 2 su 7. È sotto soglia, quindi il log lo
    # dice — ma NON è una regressione, quindi non si notifica. Un allarme che
    # suona quando va tutto bene viene silenziato prima di servire davvero.
    with tempfile.TemporaryDirectory() as d:
        repo = _repo_con_giorni(d, "2026-07-26-030000", "2026-07-27-030000")
        st = {}
        v._sorveglia_copertura_backup(repo, st, notifica=False)
    assert st.get("copertura_max") == 2
    assert "copertura_scesa_da" not in st, "una finestra che si riempie non è un guasto"


def test_una_REGRESSIONE_fa_scattare_l_allarme_una_volta_sola():
    # RISPOSTA NOTA: si era già arrivati a 7; ora sono 2 ⇒ qualcosa ha potato.
    # E la seconda chiamata NON deve riarmare: si notifica la transizione, non
    # lo stato, o diventa un messaggio al giorno che nessuno legge più.
    with tempfile.TemporaryDirectory() as d:
        repo = _repo_con_giorni(d, "2026-07-26-030000", "2026-07-27-030000")
        st = {"copertura_max": 7}
        v._sorveglia_copertura_backup(repo, st, notifica=False)
        assert st.get("copertura_scesa_da"), "una discesa dal massimo è un guasto e va segnata"
        segnata = st["copertura_scesa_da"]
        v._sorveglia_copertura_backup(repo, st, notifica=False)
        assert st["copertura_scesa_da"] == segnata, "la seconda chiamata non deve riarmare"


def test_il_rientro_pulisce_lo_stato():
    # RISPOSTA NOTA: tornati al massimo, l'allarme si chiude da solo — o resta
    # acceso per sempre e diventa arredamento.
    with tempfile.TemporaryDirectory() as d:
        repo = _repo_con_giorni(d, *[f"2026-07-2{g}-030000" for g in range(1, 8)])
        st = {"copertura_max": 7, "copertura_scesa_da": "2026-07-27T00:00:00Z"}
        v._sorveglia_copertura_backup(repo, st, notifica=False)
    assert "copertura_scesa_da" not in st


# ─────────────────────────────────────────────────────────────────────────────
# M4-b — l'aggancio di collaudo del health-gate.
#
# 📌 Questi tre casi sono nati SOTTO il blocco `__main__` e li ho spostati qui perché
#    `test_il_runner_diretto_esegue_tutti_i_test_del_file` è andato ROSSO — il presidio
#    scritto lo stesso giorno per quella trappola ha preso me, alla prima occasione.
#    *Un `append` in fondo a un file di test è il gesto più naturale che esista, ed è
#    esattamente per questo che quel presidio serviva.*
#
# Il fail-closed dell'update (`if not healthy: rollback`) è l'unico ramo importante
# di vps1777.py che nessun test tocca: richiede docker, systemd e una release
# davvero malata. L'aggancio permette di eseguirlo per davvero invece di
# certificarlo con una stringa — che sarebbe H52 rifatta da noi.
#
# Questi casi pinnano la sola cosa che conta dell'aggancio: che possa dire NO e
# che NON possa dire sì, e che si accenda solo col valore esatto.
# ─────────────────────────────────────────────────────────────────────────────

def test_aggancio_collaudo_forza_il_no(monkeypatch, tmp_path):
    monkeypatch.setenv("VPS1777_COLLAUDO_HEALTH_KO", "1")
    ok, why = v.health_gate(tmp_path)
    assert ok is False
    assert "collaudo" in why


def test_aggancio_collaudo_si_accende_solo_con_1(monkeypatch, tmp_path):
    """Un valore diverso da «1» NON deve accenderlo.

    Non è pignoleria: `VPS1777_COLLAUDO_HEALTH_KO=0` significa «spento» per
    chiunque lo legga, e un aggancio che si accende con qualunque stringa
    trasformerebbe quella riga in una trappola. Qui si verifica che con «0» la
    funzione NON restituisca la ragione di collaudo — se prosegue e fallisce per
    altro (niente docker in CI) va bene: quello che non deve fare è dire
    «collaudo».
    """
    for valore in ("0", "", "true", "si"):
        monkeypatch.setenv("VPS1777_COLLAUDO_HEALTH_KO", valore)
        try:
            _, why = v.health_gate(tmp_path, window_s=0)
        except Exception:
            continue          # senza docker può sollevare: non è questo il punto
        assert "collaudo" not in why, f"acceso a torto con «{valore}»"


def test_aggancio_collaudo_spento_di_default(monkeypatch, tmp_path):
    monkeypatch.delenv("VPS1777_COLLAUDO_HEALTH_KO", raising=False)
    try:
        _, why = v.health_gate(tmp_path, window_s=0)
    except Exception:
        return                # niente docker: il ramo di collaudo non è stato preso
    assert "collaudo" not in why


# ───── secrets-status · il verde su ZERO osservati (02/08, `71d540e6`) ────────
# 🔴 IL DIFETTO: con `items == []` il flusso stampava «nessun secret trovato» e poi
#   cadeva nel ramo `else` con «tutti i secret entro la soglia», uscendo **0**. Due
#   frasi opposte nello stesso output, e il verde era l'ultima parola.
# ⭐ È la distinzione che `copertura_backup` fa già in questo file: **None = non
#   misurato ≠ 0 = misurato e vuoto.** Zero secret su una macchina installata non è
#   «sano»: è «non ho potuto guardare» — il caso di H55 (unit con `--home` sbagliato
#   o `secrets/` non attraversabile) è documentato nel file stesso.

class _ArgsFinti:
    notify = False


def test_secrets_status_su_zero_osservati_NON_dice_che_e_tutto_a_posto(tmp_path):
    (tmp_path / "onboarding").mkdir(parents=True, exist_ok=True)
    (tmp_path / "secrets").mkdir(parents=True, exist_ok=True)   # esiste ma è VUOTA
    detto: list[str] = []
    orig_ok, orig_warn, orig_log = v.ok, v.warn, v.log
    v.ok = lambda m: detto.append(f"ok:{m}")
    v.warn = lambda m: detto.append(f"warn:{m}")
    v.log = lambda m: detto.append(f"log:{m}")
    try:
        rc = v.cmd_secrets_status(tmp_path, _ArgsFinti())
    finally:
        v.ok, v.warn, v.log = orig_ok, orig_warn, orig_log
    assert rc == 2, f"zero secret osservati deve essere «non eseguibile», non 0 (rc={rc})"
    assert not any("tutti i secret entro la soglia" in d for d in detto), (
        f"dichiara sano uno stato che non ha misurato: {detto}"
    )
    assert any("NON MISURATO" in d for d in detto), detto


def test_secrets_status_segnala_i_secret_ATTESI_e_assenti(tmp_path):
    """Un secret atteso e assente è peggio di uno vecchio: quello vecchio esiste."""
    (tmp_path / "onboarding").mkdir(parents=True, exist_ok=True)
    (tmp_path / "secrets").mkdir(parents=True, exist_ok=True)
    # ne creo UNO solo: gli altri della policy restano assenti
    nome_file = v._SECRET_POLICY[0][1]
    (tmp_path / "secrets" / nome_file).write_text("x")
    detto: list[str] = []
    orig_ok, orig_warn, orig_log = v.ok, v.warn, v.log
    v.ok = lambda m: detto.append(f"ok:{m}")
    v.warn = lambda m: detto.append(f"warn:{m}")
    v.log = lambda m: detto.append(f"log:{m}")
    try:
        rc = v.cmd_secrets_status(tmp_path, _ArgsFinti())
    finally:
        v.ok, v.warn, v.log = orig_ok, orig_warn, orig_log
    assert rc == 0, "con almeno un secret osservato il comando resta eseguibile"
    assert any("ATTESI e NON trovati" in d for d in detto), (
        f"i secret assenti spariscono in silenzio: {detto}"
    )
    stato = json.loads((tmp_path / "onboarding" / "secrets_status.json").read_text())
    assert stato.get("mancanti"), "l'elenco dei mancanti deve arrivare anche a /admin/secrets"


def test_SECRET_POLICY_non_puo_dimenticare_un_segreto_in_silenzio():
    """Il patto: la lista può invecchiare, ma RUMOROSAMENTE.

    🔴 Il 02/08 `archive_desc_secret` era l'unico dei sei segreti dichiarati nei
    compose a non avere una politica di scadenza — e non per una decisione: è
    l'unico **mai digitato da un umano e mai nominato in un rituale di rotazione**,
    quindi non aveva lasciato traccia in nessuno dei due elenchi scritti a mano.
    ⭐ Lo stesso patto esiste già in questo file per `SEGRETI_GENERABILI` (r.442),
    con la ragione scritta: «non "ricordarsi", ma non poter dimenticare».
    `_SECRET_POLICY` non ce l'aveva — il suo test pinnava i nomi a mano, quindi un
    settimo segreto nascerebbe cieco esattamente come il sesto.
    """
    in_policy = {voce[0] for voce in v._SECRET_POLICY}
    reali = set()
    for nome_file in ("compose.yaml", "compose.ingress.cloudflared.yaml"):
        righe = (_ROOT / nome_file).read_text(encoding="utf-8").splitlines()
        try:
            start = next(n for n, r in enumerate(righe) if r.rstrip() == "secrets:")
        except StopIteration:
            continue
        for r in righe[start + 1:]:
            if r and not r.startswith(" "):
                break
            m = re.match(r"^  ([a-z_]+):", r)
            if m:
                reali.add(m.group(1))
    assert reali, "nessun secret letto dai compose: la sonda non guarda dove crede"
    # `admin_password` in policy ↔ `admin_password_bcrypt` nei compose: stesso
    # oggetto, due nomi. Si confronta sul NOME FILE, che è l'unica cosa che combacia.
    file_policy = {voce[1].removesuffix(".txt") for voce in v._SECRET_POLICY}
    scoperti = reali - file_policy - in_policy
    assert not scoperti, (
        f"segreti dichiarati nei compose e SENZA politica di scadenza: {sorted(scoperti)} — "
        f"aggiungili a _SECRET_POLICY col loro max_giorni, o dichiara qui perché non ne hanno"
    )


def test_un_proxy_che_pubblica_SENZA_public_base_non_e_non_applicabile():
    """`cloudflared` pubblica su Internet e non ha `PUBLIC_BASE`: senza questo caso
    resta senza nessuna sonda, ed è il buco che `3600b07` NON aveva chiuso.

    Non si inventa un bersaglio (senza URL non si può sondare) e non si alza un
    allarme (sarebbe un rosso quotidiano su una macchina che magari funziona). Si
    separano i due «vero» che prima collassavano: «non c'è niente da sondare» e
    «dovrei sondare e non so dove». Il secondo deve LASCIARE UNA TRACCIA.
    """
    detto = []
    orig = (v.nome_pubblico_funnel, v.env_read, v.compose_ps, v.warn)
    v.nome_pubblico_funnel = lambda: ""
    v.env_read = lambda repo: {"PUBLIC_BASE": ""}
    v.warn = lambda m: detto.append(m)
    try:
        v.compose_ps = lambda repo, all_states=False: [{"Service": "gateway"},
                                                       {"Service": "cloudflared"}]
        ok, perche = v.funnel_ok(Path("/non/serve"))
        assert ok is True, "non deve provocare un rollback né un allarme"
        assert "NON SORVEGLIATO" in perche, perche
        assert detto and "CIECA" in detto[0], f"nessun avviso visibile: {detto}"

        # …e chi NON pubblica resta «non applicabile», senza rumore.
        detto.clear()
        v.compose_ps = lambda repo, all_states=False: [{"Service": "gateway"}]
        ok2, perche2 = v.funnel_ok(Path("/non/serve"))
        assert ok2 is True and "non applicabile" in perche2, perche2
        assert not detto, f"avviso su un profilo che non pubblica: {detto}"
    finally:
        v.nome_pubblico_funnel, v.env_read, v.compose_ps, v.warn = orig


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {name}")
            except Exception as exc:  # noqa: BLE001
                fails += 1
                print(f"FAIL {name}: {exc}")
    raise SystemExit(1 if fails else 0)
