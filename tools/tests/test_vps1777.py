"""Test di logica pura per tools/vps1777.py (nessun docker/systemd richiesto).

Copre i fix H14 (esclusione nlm-auth dallo snapshot in chiaro) e H43
(templatizzazione delle unit systemd). Solo stdlib; eseguibile sia con pytest
sia direttamente: `python3 tools/tests/test_vps1777.py`.
"""
from __future__ import annotations

import importlib.util
import os
import pwd
import tempfile
from pathlib import Path

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
    """Best-effort davvero: un marcatore corrotto a mano non deve far fallire
    secrets-status, che è il portatore di TUTTI gli altri promemoria."""
    with tempfile.TemporaryDirectory() as td:
        repo = _repo_con_env(Path(td), "VPS1777_REQUIRE_COSIGN=0\n")
        v.cosign_bypass_status(repo)
        (repo / "onboarding" / v._COSIGN_BYPASS_MARKER).write_text("ieri sera\n")
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
