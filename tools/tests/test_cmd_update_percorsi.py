"""Ogni strada di `cmd_update`, percorsa da una prova rapida, prima di spezzarla (QUA-04).

PERCHÉ ESISTE. Il 24/11/2026 `cmd_update` misurava complessità 54 su 540 righe, e le prove
rapide ne percorrevano 2 rami su 80: era provata sul serio solo dalle prove lente (il
collaudo su macchina, i job di `rollback.yml`). Un caso raro rotto (disco pieno, rete che
cade, intent rifiutato, un segreto senza permessi) non lo vedeva nessuno prima del rilascio.
Le prove che c'erano leggevano il SORGENTE (che una chiamata ci sia, in che ordine): utili,
ma uno spezzamento le rompe senza dire se il comportamento è cambiato.

⇒ Qui ogni collaboratore di `cmd_update` è sostituito da un finto che scrive in un registro
(`Banco.ev`). Ogni prova fissa una strada e controlla che cosa la funzione FA: l'esito, il
messaggio, i passi scritti nel progress (li leggono i pannelli), le chiamate e il loro
ordine. Sono prove di COMPORTAMENTO: restano valide dopo lo spezzamento, ed è il loro scopo.

Niente docker, niente rete, niente sudo: stdlib e pytest.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("vps1777_cli_percorsi", _ROOT / "tools" / "vps1777.py")
v = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v)

DIGEST = {s: f"ghcr.io/x/vps1777-{s}@sha256:{'a' * 64}" for s in v.SERVICES}


class Reexec(Exception):
    """Al posto di os.execv: la funzione cede il posto alla CLI nuova."""


class Banco:
    """Il mondo attorno a `cmd_update`, finto e configurabile. Ogni chiamata va in `ev`."""

    def __init__(self, tmp: Path, mp: pytest.MonkeyPatch) -> None:
        self.repo = tmp / "repo"
        self.repo.mkdir()
        self.bundle = tmp / "bundle"
        (self.bundle / "tools").mkdir(parents=True)
        (self.bundle / "images.lock").write_text(json.dumps(DIGEST))
        self.ev: list[tuple] = []
        # ── la configurazione del mondo (le prove la cambiano prima di `esegui`)
        self.cur = "0.98.12"
        self.st: dict = {"history": []}
        self.lock = True
        self.ripresa: int | None = None
        self.intent: str | Exception = "0.98.13"
        self.docker_ok = True
        self.stack = True
        self.watchtower = False
        self.libero, self.serve = 50 * 1024**3, 2 * 1024**3
        self.latest: dict | None | Exception = {"tag_name": "v0.98.13", "body": "note",
                                                 "published_at": "2026-11-20T00:00:00Z"}
        self.per_tag: dict[str, dict | Exception] = {}
        self.canale_rel = "stable"
        self.canale: tuple = ({"latest": "0.98.13", "scade_il": "2027-01-08"}, "")
        self.salute: list[tuple[bool, str]] = []        # una risposta per chiamata; vuota = sano
        self.floor = False
        self.quarantena: str | None = None
        self.risposta = "s"
        self.sorgenti: dict[int, list | Exception] = {}  # per numero di chiamata (1, 2, 3)
        self.mancanti: dict[int, list[str]] = {}
        self.env: dict[str, str] = {}
        self.bundle_err: Exception | None = None
        self.regressioni: dict = {}
        self.backup_err: Exception | None = None
        self.esito: dict[str, int] = {"config": 0, "pull": 0, "up": 0}
        self.digest_err: Exception | None = None
        self.applica_err: Exception | None = None
        self.migrazioni: tuple | Exception = ([], False)
        self._n_sorgenti = 0
        self._n_mancanti = 0
        self._installa(mp)

    # ── i finti
    def _installa(self, mp: pytest.MonkeyPatch) -> None:
        b = self

        def reg(nome):
            return lambda *a, **k: b.ev.append((nome,)) or None
        mp.setattr(v, "acquire_lock", lambda repo: SimpleNamespace(close=reg("lock.close")) if b.lock else None)
        mp.setattr(v, "state_load", lambda repo: b.st)
        mp.setattr(v, "state_save", lambda repo, st: b.ev.append(("state_save", json.dumps(st, sort_keys=True, default=str))))
        mp.setattr(v, "_riprendi_update_interrotto", lambda repo, st: b.ripresa)

        def consume(repo, path, st):
            b.ev.append(("consume_intent", str(path)))
            if isinstance(b.intent, Exception):
                raise b.intent
            return b.intent
        mp.setattr(v, "consume_intent", consume)
        mp.setattr(v, "progress_write", lambda repo, target, n, nome, stato, det="": b.ev.append(("step", n, nome, stato)))
        mp.setattr(v, "current_version", lambda repo: b.cur)
        mp.setattr(v, "stack_running", lambda repo: b.stack)
        mp.setattr(v.shutil, "disk_usage", lambda p: SimpleNamespace(free=b.libero))
        mp.setattr(v, "spazio_richiesto_update", lambda repo: (b.serve, "immagini e backup"))

        def latest(repo):
            b.ev.append(("latest_release",))
            if isinstance(b.latest, Exception):
                raise b.latest
            return b.latest
        mp.setattr(v, "latest_release", latest)

        def per_tag(tag):
            b.ev.append(("release_by_tag", tag))
            r = b.per_tag.get(tag, {"tag_name": tag, "body": "", "published_at": "2026-11-01T00:00:00Z"})
            if isinstance(r, Exception):
                raise r
            return r
        mp.setattr(v, "release_by_tag", per_tag)
        mp.setattr(v, "release_channel", lambda repo: b.canale_rel)
        mp.setattr(v, "canale_per_update", lambda repo, **k: b.ev.append(("canale",)) or b.canale)
        mp.setattr(v, "telegram_notify", lambda repo, testo, **k: b.ev.append(("telegram", testo)) or True)

        def salute(repo, env=None, **k):
            b.ev.append(("health_gate",))
            return b.salute.pop(0) if b.salute else (True, "")
        mp.setattr(v, "health_gate", salute)
        mp.setattr(v, "floor_blocca", lambda target, cur: b.floor)
        mp.setattr(v, "quarantena_blocca", lambda rel, ore: b.quarantena)
        mp.setattr("builtins.input", lambda prompt="": b.ev.append(("input",)) or b.risposta)

        def sorgenti(root, repo):
            b._n_sorgenti += 1
            b.ev.append(("compose_sorgenti", b._n_sorgenti))
            r = b.sorgenti.get(b._n_sorgenti, [root / "compose.yaml"])
            if isinstance(r, Exception):
                raise r
            return r
        mp.setattr(v, "_compose_sorgenti", sorgenti)

        def mancanti(paths, repo):
            b._n_mancanti += 1
            return list(b.mancanti.get(b._n_mancanti, []))
        mp.setattr(v, "_secrets_mancanti", mancanti)
        mp.setattr(v, "env_read", lambda repo: dict(b.env))

        def fetch(repo, rel, require_cosign):
            b.ev.append(("fetch_bundle", require_cosign))
            if b.bundle_err:
                raise b.bundle_err
            return b.bundle
        mp.setattr(v, "fetch_bundle", fetch)
        mp.setattr(v, "regressioni_del_bundle", lambda bundle, repo: b.regressioni)
        mp.setattr(v, "sudo", lambda cmd, **k: b.ev.append(("sudo", tuple(cmd))))

        def execv(path, argv):
            b.ev.append(("execv", tuple(argv)))
            raise Reexec()
        mp.setattr(v.os, "execv", execv)
        mp.setattr(v, "backup_sh_della_release", lambda repo, bundle: repo / "tools" / "backup.sh")
        mp.setattr(v, "snapshot_create", lambda repo, cur, target: b.ev.append(("snapshot",)) or Path("/snap"))
        mp.setattr(v, "compose_cmd", lambda repo, files=None: ["compose", "nuovo" if files else "installato"])

        def run(cmd, **k):
            cmd = list(cmd)
            if cmd[:2] == ["docker", "info"]:
                b.ev.append(("docker_info",))
                return subprocess.CompletedProcess(cmd, 0 if b.docker_ok else 1, "", "")
            if cmd[:2] == ["docker", "inspect"]:
                return subprocess.CompletedProcess(cmd, 0 if b.watchtower else 1, "", "")
            if cmd[:3] == ["docker", "image", "rm"]:
                b.ev.append(("image_rm", cmd[3]))
                return subprocess.CompletedProcess(cmd, 0, "", "")
            if cmd[0] == "bash":
                b.ev.append(("backup", cmd[-1]))
                if b.backup_err:
                    raise b.backup_err
                return subprocess.CompletedProcess(cmd, 0, "", "")
            azione = cmd[-1] if cmd[-1] != "-d" else "up"
            if cmd[-2:] == ["config", "-q"]:
                azione = "config"
            b.ev.append(("compose", cmd[1], azione))
            codice = b.esito.get(azione, 0)
            return subprocess.CompletedProcess(cmd, codice, "", "errore finto" if codice else "")
        mp.setattr(v, "run", run)

        def digest(repo, lock, target, attive):
            b.ev.append(("verify_digests",))
            if b.digest_err:
                raise b.digest_err
        mp.setattr(v, "verify_digests", digest)
        mp.setattr(v, "immagini_attive", lambda repo, target, files=None: set())
        mp.setattr(v, "image_ref", lambda repo, svc, ver: f"img/{svc}:{ver}")
        mp.setattr(v, "capture_current_images", lambda repo, cur: {"gateway": "vecchia"})

        def applica(nome):
            def f(*a, **k):
                b.ev.append((nome,))
                if b.applica_err and nome == "sync_managed_files":
                    raise b.applica_err
            return f
        for nome in ("save_rollback_files", "sync_managed_files", "install_systemd_units", "versione_set"):
            mp.setattr(v, nome, applica(nome))
        mp.setattr(v, "rimuovi_watchtower_orfano", reg("rimuovi_watchtower"))

        def migra(repo, lock, target):
            b.ev.append(("migrazioni",))
            if isinstance(b.migrazioni, Exception):
                raise b.migrazioni
            return b.migrazioni
        mp.setattr(v, "run_migrations", migra)
        mp.setattr(v, "assicura_webapp_secret", reg("webapp_secret"))
        mp.setattr(v, "permessi_servizi", reg("permessi_servizi"))

        def rollback(repo, st, target, prev, bundle, snap, dati, perche):
            b.ev.append(("ROLLBACK", dati, perche))
            return 1
        mp.setattr(v, "_rollback_routine", rollback)
        for nome in ("prune_old_images", "snapshot_prune", "releases_prune", "status_write", "sync_state_card"):
            mp.setattr(v, nome, reg(nome))

    # ── l'esecuzione
    def esegui(self, **arg) -> tuple[int | str, str]:
        """(esito, testo): l'esito è il ritorno, o il codice di uscita di `die`, o "reexec"."""
        a = dict(version=None, from_intent=None, eta_minima=None, yes=True,
                 skip_self_update=True, no_require_cosign=False)
        a.update(arg)
        try:
            return v.cmd_update(self.repo, SimpleNamespace(**a)), ""
        except SystemExit as e:
            return e.code, ""
        except Reexec:
            return "reexec", ""

    def nomi(self) -> list[str]:
        return [e[0] for e in self.ev]

    def passi(self) -> list[tuple]:
        return [e[1:] for e in self.ev if e[0] == "step"]


@pytest.fixture()
def b(tmp_path, monkeypatch, capsys):
    banco = Banco(tmp_path, monkeypatch)
    banco.capsys = capsys
    return banco


def _uscita(b) -> str:
    o = b.capsys.readouterr()
    return o.out + o.err


# ── la strada maestra ────────────────────────────────────────────────────────

PASSI_COMPLETI = [
    (4, "preflight-secrets", "running"), (5, "fetch", "running"),
    (6, "preflight-secrets-bundle", "running"), (7, "backup", "running"),
    (8, "stage-check", "running"), (9, "pull", "running"), (10, "apply-files", "running"),
    (11, "stop", "running"), (12, "migrate", "running"), (13, "up", "running"),
    (14, "health-gate", "running"), (15, "done", "ok"),
]


def test_un_update_riuscito_percorre_i_quindici_passi_e_chiude_lo_stato(b):
    esito, _ = b.esegui()
    assert esito == 0
    assert b.passi() == PASSI_COMPLETI
    st = b.st
    assert st["current"] == "0.98.13" and st["previous"] == "0.98.12"
    assert st["update_in_progress"] is None
    assert st["previous_images"] == {"gateway": "vecchia"}
    assert st["history"][-1]["event"] == "updated" and st["history"][-1]["to"] == "0.98.13"
    n = b.nomi()
    # l'ordine che conta: backup prima di toccare, file prima di fermare, stop prima di migrare
    assert n.index("backup") < n.index("save_rollback_files") < n.index("sync_managed_files") \
        < n.index("versione_set") < n.index("rimuovi_watchtower") < n.index("migrazioni") \
        < n.index("webapp_secret") < n.index("permessi_servizi") < n.index("health_gate")
    assert [e for e in b.ev if e[0] == "compose"] == [
        ("compose", "nuovo", "config"), ("compose", "nuovo", "pull"),
        ("compose", "installato", "down"), ("compose", "installato", "up")]
    for dopo in ("prune_old_images", "snapshot_prune", "releases_prune", "status_write", "sync_state_card"):
        assert dopo in n
    assert ("telegram", "✅ vps1777 aggiornato: v0.98.12 → v0.98.13") in b.ev
    assert "aggiornato a v0.98.13" in _uscita(b)


def test_lo_stato_di_mezzo_dice_da_dove_si_riparte(b):
    """Allo step 10 lo stato su disco porta l'update in corso e i `previous` di prima
    (per la ripresa di un update interrotto): è la prima scrittura dopo il backup."""
    b.st.update({"previous": "0.98.11", "previous_images": {"gateway": "antica"}})
    b.esegui()
    scritti = [json.loads(e[1]) for e in b.ev if e[0] == "state_save"]
    mezzo = next(s for s in scritti if s.get("update_in_progress"))
    assert mezzo["update_in_progress"]["target"] == "0.98.13"
    assert mezzo["update_in_progress"]["step"] == 10
    assert mezzo["update_in_progress"]["prima"] == {"previous": "0.98.11",
                                                    "previous_images": {"gateway": "antica"}}


def test_la_storia_ha_un_tetto(b):
    b.st["history"] = [{"event": "x"}] * (v.STORIA_MAX + 5)
    assert b.esegui()[0] == 0
    assert len(b.st["history"]) == v.STORIA_MAX and b.st["history"][-1]["event"] == "updated"


# ── prima di cominciare ─────────────────────────────────────────────────────

def test_lock_occupato_toglie_l_intent_ed_esce_75(b, tmp_path):
    b.lock = False
    intent = tmp_path / "intent.json"
    intent.write_text("{}")
    assert b.esegui(from_intent=str(intent))[0] == v.ESITO_LOCK_OCCUPATO
    assert not intent.exists(), "un intent lasciato lì rilancerebbe l'update in un giro"


def test_lock_occupato_a_mano_esce_75_senza_intent(b):
    b.lock = False
    assert b.esegui()[0] == v.ESITO_LOCK_OCCUPATO
    assert "update già in corso" in _uscita(b)


def test_un_update_interrotto_si_chiude_e_il_giro_finisce_li(b):
    b.ripresa = 7
    assert b.esegui()[0] == 7
    assert "docker_info" not in b.nomi()


def test_l_intent_letto_diventa_il_target(b):
    b.intent = "0.98.13"
    assert b.esegui(from_intent="/x/intent.json")[0] == 0
    assert ("consume_intent", "/x/intent.json") in b.ev
    assert ("release_by_tag", "v0.98.13") in b.ev and "latest_release" not in b.nomi()


def test_un_intent_rifiutato_ferma_tutto_e_lo_dice_al_pannello(b):
    b.intent = RuntimeError("firma assente")
    assert b.esegui(from_intent="/x/intent.json")[0] == 1
    assert b.passi() == [(0, "intent", "failed")]
    assert "intent rifiutato: firma assente" in _uscita(b)


@pytest.mark.parametrize("guasto,frase", [
    ("docker", "docker non attivo"),
    ("dev", "modalità dev"),
    ("disco", "spazio disco insufficiente: 1.0 GiB liberi, ne servono 2.0 GiB — immagini e backup"),
])
def test_il_preflight_si_ferma_senza_toccare_niente(b, guasto, frase):
    if guasto == "docker":
        b.docker_ok = False
    elif guasto == "dev":
        b.cur = "dev"
    else:
        b.libero = 1024**3
    assert b.esegui()[0] == 1
    assert frase in _uscita(b)
    assert b.passi() == [] and "latest_release" not in b.nomi()


def test_stack_fermo_e_watchtower_si_dicono_e_non_fermano(b):
    b.stack = False
    b.watchtower = True
    assert b.esegui()[0] == 0
    out = _uscita(b)
    assert "lo stack non risulta in esecuzione" in out
    assert "vps1777-watchtower" in out and "0.67.0" in out


# ── quale release ────────────────────────────────────────────────────────────

def test_github_irraggiungibile(b):
    b.latest = urllib.error.URLError("dns")
    assert b.esegui()[0] == 1
    assert "GitHub irraggiungibile" in _uscita(b)


def test_nessuna_release_pubblicata(b):
    b.latest = None
    assert b.esegui()[0] == 0
    assert "nessuna release pubblicata" in _uscita(b) and b.passi() == []


def test_con_version_si_chiede_quella_release(b):
    assert b.esegui(version="0.98.13")[0] == 0
    assert ("release_by_tag", "v0.98.13") in b.ev and "latest_release" not in b.nomi()


# ── il canale firmato (SIC-15) ───────────────────────────────────────────────

def test_canale_fermo_ferma_l_automatico_e_avvisa(b):
    b.canale = (None, "canale di aggiornamento SCADUTO il 2027-01-08")
    assert b.esegui(eta_minima=48)[0] == 0
    assert b.st["canale"]["esito"] == "fermo" and "SCADUTO" in b.st["canale"]["motivo"]
    assert any(e[0] == "telegram" and "FERMATO" in e[1] for e in b.ev)
    assert b.passi() == []


def test_canale_valido_si_registra_e_si_prosegue(b):
    assert b.esegui(eta_minima=48)[0] == 0
    assert b.st["canale"]["esito"] == "ok" and b.st["canale"]["latest"] == "0.98.13"
    assert b.passi()[-1] == (15, "done", "ok")


def test_il_canale_piu_nuovo_dell_api_vince(b):
    b.canale = ({"latest": "0.98.14", "scade_il": "2027-01-08"}, "")
    assert b.esegui(eta_minima=48)[0] == 0
    assert ("release_by_tag", "v0.98.14") in b.ev
    assert b.st["current"] == "0.98.14"
    assert "seguo il canale" in _uscita(b)


def test_il_canale_piu_nuovo_ma_github_cade(b):
    b.canale = ({"latest": "0.98.14", "scade_il": "2027-01-08"}, "")
    b.per_tag["v0.98.14"] = OSError("rete")
    assert b.esegui(eta_minima=48)[0] == 1
    assert "GitHub irraggiungibile" in _uscita(b)


@pytest.mark.parametrize("arg,canale_rel", [
    ({"eta_minima": None}, "stable"),             # a mano
    ({"eta_minima": 48, "version": "0.98.13"}, "stable"),   # target esplicito
    ({"eta_minima": 48}, "prerelease"),           # canale di prova
])
def test_il_canale_si_guarda_solo_sul_percorso_automatico_stabile(b, arg, canale_rel):
    b.canale_rel = canale_rel
    b.esegui(**arg)
    assert "canale" not in b.nomi() and "canale" not in b.st


# ── già aggiornato, downgrade, quarantena ────────────────────────────────────

def test_gia_aggiornato(b):
    b.cur = "0.98.13"
    assert b.esegui()[0] == 0
    assert "già aggiornato (v0.98.13)" in _uscita(b) and b.passi() == []


def test_gia_aggiornato_con_lo_stato_perso_e_lo_stack_sano(b):
    b.cur = "0.98.13"
    b.st["stato_perso"] = "2026-11-20"
    assert b.esegui()[0] == 0
    assert "stato_perso" not in b.st and b.st["current"] == "0.98.13"
    assert "health_gate" in b.nomi()


@pytest.mark.parametrize("stack,salute", [(True, (False, "gateway unhealthy")), (False, None)])
def test_gia_aggiornato_con_lo_stato_perso_e_lo_stack_malato(b, stack, salute):
    b.cur = "0.98.13"
    b.stack = stack
    b.st["stato_perso"] = "2026-11-20"
    if salute:
        b.salute = [salute]
    assert b.esegui()[0] == 2
    out = _uscita(b)
    assert "lo stack non è sano" in out and "2026-11-20" in out
    assert ("health_gate" in b.nomi()) is stack, "a stack fermo non si interroga la salute"


@pytest.mark.parametrize("cur,frase", [("0.99.0", "v0.98.13 < v0.99.0"),
                                       ("nightly", "versione in esercizio non confrontabile")])
def test_il_pulsante_non_fa_scendere_di_versione(b, cur, frase):
    b.cur = cur
    b.floor = True
    assert b.esegui(from_intent="/x/i.json")[0] == 1
    assert frase in _uscita(b)
    assert b.passi() == [(0, "intent", "failed")]


def test_una_latest_piu_vecchia_e_una_risposta_stantia(b):
    b.cur = "0.99.0"
    assert b.esegui()[0] == 0
    assert "risposta stantia" in _uscita(b) and b.passi() == []


def test_con_version_esplicita_si_scende_davvero(b):
    b.cur = "0.99.0"
    assert b.esegui(version="0.98.13")[0] == 0
    assert b.st["current"] == "0.98.13"


def test_la_quarantena_rimanda_al_prossimo_giro(b):
    b.quarantena = "pubblicata da 3 ore, ne servono 48"
    assert b.esegui(eta_minima=48)[0] == 0
    assert "in quarantena: pubblicata da 3 ore" in _uscita(b) and b.passi() == []


def test_la_quarantena_non_vale_per_un_target_esplicito(b):
    b.quarantena = "troppo giovane"
    assert b.esegui(eta_minima=48, version="0.98.13")[0] == 0
    assert b.passi()[-1] == (15, "done", "ok")


@pytest.mark.parametrize("risposta,esito", [("n", 1), ("", 1), ("s", 0), ("yes", 0)])
def test_la_conferma_a_mano(b, risposta, esito):
    b.risposta = risposta
    assert b.esegui(yes=False)[0] == esito
    assert "input" in b.nomi()


def test_il_pulsante_non_chiede_conferma(b):
    assert b.esegui(yes=False, from_intent="/x/i.json")[0] == 0
    assert "input" not in b.nomi()


def test_il_changelog_si_stampa_redatto_e_tagliato(b):
    b.latest = {"tag_name": "v0.98.13", "body": "x" * 3000}
    b.esegui()
    out = _uscita(b)
    assert "─── Changelog ───" in out and "x" * 2001 not in out


# ── step 4 e 5: la rete di rollback, il bundle ──────────────────────────────

def test_la_rete_di_rollback_bucata_si_dice_e_non_ferma(b):
    b.mancanti[1] = ["gateway_secret → ./secrets/gateway_secret   [VUOTO]"]
    assert b.esegui()[0] == 0
    assert "la rete di ROLLBACK è bucata" in _uscita(b)


def test_la_rete_di_rollback_non_controllabile_si_dice_e_non_ferma(b):
    b.sorgenti[1] = FileNotFoundError("compose.yaml")
    assert b.esegui()[0] == 0
    assert "pre-flight rollback non eseguibile" in _uscita(b)


@pytest.mark.parametrize("env,arg,atteso", [
    ({}, {}, True),
    ({"VPS1777_REQUIRE_COSIGN": "0"}, {}, False),
    ({"VPS1777_REQUIRE_COSIGN": " 1 "}, {}, True),
    ({}, {"no_require_cosign": True}, False),
])
def test_cosign_e_obbligatorio_salvo_la_via_d_emergenza(b, env, arg, atteso):
    b.env = env
    b.esegui(**arg)
    assert ("fetch_bundle", atteso) in b.ev


@pytest.mark.parametrize("errore", [RuntimeError("firma"), OSError("disco"),
                                    urllib.error.URLError("rete")])
def test_bundle_non_scaricato_o_non_verificato(b, errore):
    b.bundle_err = errore
    assert b.esegui()[0] == 1
    assert b.passi()[-1] == (5, "fetch", "failed")
    assert "fetch/verifica bundle fallita" in _uscita(b)


def test_bundle_con_images_lock_rotto(b):
    (b.bundle / "images.lock").write_text("{non json")
    assert b.esegui()[0] == 1
    assert b.passi()[-1] == (5, "fetch", "failed")


def test_un_bundle_che_riporta_indietro_una_unit_si_rifiuta(b):
    b.regressioni = {"vps1777-update.service": ["NoNewPrivileges=yes"]}
    assert b.esegui()[0] == 1
    assert b.passi()[-1] == (5, "preflight-unit", "failed")
    out = _uscita(b)
    assert "REINTRODURREBBE" in out and "NoNewPrivileges=yes" in out
    assert "backup" not in b.nomi()


# ── step 6: la CLI si aggiorna da sé ─────────────────────────────────────────

@pytest.fixture()
def cli_installata(b, tmp_path, monkeypatch):
    installata = tmp_path / "bin" / "vps1777"
    installata.parent.mkdir()
    installata.write_text("vecchia")
    (b.bundle / "tools" / "vps1777.py").write_text("nuova")
    monkeypatch.setattr(v, "INSTALLED_CLI", str(installata))
    monkeypatch.setattr(sys, "argv", [str(installata)])
    return installata


def test_la_cli_nuova_si_installa_e_riparte_con_il_target_fissato(b, cli_installata):
    esito, _ = b.esegui(skip_self_update=False, from_intent="/x/i.json", no_require_cosign=True)
    assert esito == "reexec"
    assert ("sudo", ("install", "-m", "755", str(b.bundle / "tools" / "vps1777.py"),
                     str(cli_installata))) in b.ev
    assert "lock.close" in b.nomi(), "il lock si rilascia prima di cedere il posto"
    argv = next(e[1] for e in b.ev if e[0] == "execv")
    assert argv == (str(cli_installata), "--home", str(b.repo), "update", "--version", "0.98.13",
                    "--yes", "--skip-self-update", "--no-require-cosign")
    assert "--from-intent" not in argv
    assert "backup" not in b.nomi()


def test_senza_la_via_d_emergenza_il_riavvio_non_la_inventa(b, cli_installata):
    assert b.esegui(skip_self_update=False)[0] == "reexec"
    argv = next(e[1] for e in b.ev if e[0] == "execv")
    assert argv[-1] == "--skip-self-update" and "--no-require-cosign" not in argv


@pytest.mark.parametrize("caso", ["uguale", "altro_eseguibile", "senza_cli_nel_bundle", "saltato"])
def test_la_cli_non_si_riavvia_quando_non_serve(b, cli_installata, caso, monkeypatch, tmp_path):
    arg = {"skip_self_update": False}
    if caso == "uguale":
        (b.bundle / "tools" / "vps1777.py").write_text("vecchia")
    elif caso == "altro_eseguibile":
        monkeypatch.setattr(sys, "argv", [str(tmp_path / "altrove.py")])
    elif caso == "senza_cli_nel_bundle":
        (b.bundle / "tools" / "vps1777.py").unlink()
    else:
        arg = {"skip_self_update": True}
    assert b.esegui(**arg)[0] == 0
    assert "execv" not in b.nomi()


# ── step 6-bis: i segreti della release in arrivo ───────────────────────────

def test_bundle_senza_compose(b):
    b.sorgenti[2] = FileNotFoundError("compose.yaml")
    assert b.esegui()[0] == 1
    assert b.passi()[-1] == (6, "preflight-secrets-bundle", "failed")
    assert "incompleto" in _uscita(b) and "backup" not in b.nomi()


def test_il_bot_senza_token_non_ferma_l_update(b):
    b.mancanti[2] = [f"{v.SEGRETI_DEL_BOT[0]} → ./secrets/{v.SEGRETI_DEL_BOT[0]}   [VUOTO]"]
    assert b.esegui()[0] == 0
    assert "il token di Telegram è vuoto" in _uscita(b)


@pytest.mark.parametrize("voce,consiglio", [
    ("secrets → ./secrets   [DIRECTORY NON LEGGIBILE]", "NON ricreare né i file né la cartella"),
    ("gateway_secret → ./secrets/gateway_secret   [NON LEGGIBILE]", "chmod 600 secrets/gateway_secret"),
    ("gateway_secret → ./secrets/gateway_secret   [VUOTO]", "openssl rand -hex 32 > secrets/gateway_secret"),
    ("segreto_ignoto → ./secrets/segreto_ignoto   [MANCANTE]", "natura non classificata"),
])
def test_un_segreto_mancante_ferma_prima_di_toccare_e_dice_come_curarlo(b, voce, consiglio):
    b.mancanti[2] = [voce]
    assert b.esegui()[0] == 1
    assert b.passi()[-1] == (6, "preflight-secrets-bundle", "failed")
    out = _uscita(b)
    assert consiglio in out and "niente è stato toccato" in out
    assert "backup" not in b.nomi()


def test_un_segreto_non_generabile_non_si_inventa(b):
    nome = "cloudflared_token"           # non del bot: quelli hanno la regola dell'attesa
    assert nome in v.SEGRETI_NON_GENERABILI
    b.mancanti[2] = [f"{nome} → ./secrets/{nome}   [VUOTO]"]
    assert b.esegui()[0] == 1
    assert "NON generarlo con un valore casuale" in _uscita(b)


# ── step 7-9: backup, controllo del compose nuovo, immagini ─────────────────

@pytest.mark.parametrize("errore", [subprocess.CalledProcessError(2, "backup.sh"), OSError("disco")])
def test_backup_fallito_annulla_a_stack_intatto(b, errore):
    b.backup_err = errore
    assert b.esegui()[0] == 1
    assert b.passi()[-1] == (7, "backup", "failed")
    assert "stack intatto" in _uscita(b) and "save_rollback_files" not in b.nomi()


def test_il_backup_e_quello_della_release_senza_archivio(b):
    b.esegui()
    assert ("backup", "--senza-archivio") in b.ev


def test_stage_check_bundle_incompleto(b):
    b.sorgenti[3] = FileNotFoundError("compose.tailscale.yaml")
    assert b.esegui()[0] == 1
    assert b.passi()[-1] == (8, "stage-check", "failed")


def test_stage_check_compose_non_valido(b):
    b.esito["config"] = 1
    assert b.esegui()[0] == 1
    assert b.passi()[-1] == (8, "stage-check", "failed")
    assert "compose config sul bundle fallita" in _uscita(b)


def test_pull_fallito(b):
    b.esito["pull"] = 1
    assert b.esegui()[0] == 1
    assert b.passi()[-1] == (9, "pull", "failed")
    assert "stack intatto sulla vecchia versione" in _uscita(b)


def test_digest_diversi_tolgono_le_immagini_scaricate(b):
    b.digest_err = RuntimeError("digest di gateway diverso dal lock")
    assert b.esegui()[0] == 1
    assert b.passi()[-1] == (9, "pull", "failed")
    assert [e[1] for e in b.ev if e[0] == "image_rm"] == [f"img/{s}:0.98.13" for s in v.SERVICES]
    assert "save_rollback_files" not in b.nomi()


# ── oltre il punto di non ritorno: ogni guasto passa dal rollback ───────────

def test_file_non_applicati_tornano_indietro_senza_dati(b):
    b.applica_err = OSError("disco pieno")
    assert b.esegui()[0] == 1
    rb = next(e for e in b.ev if e[0] == "ROLLBACK")
    assert rb[1] is False and "applicazione dei file fallita: disco pieno" in rb[2]
    assert "rimuovi_watchtower" not in b.nomi()


@pytest.mark.parametrize("errore,dati,perche", [
    (v.MigrationError("colonna", mutated=True), True, "migrazione fallita: colonna"),
    (v.MigrationError("prima di scrivere", mutated=False), False, "migrazione fallita"),
    (subprocess.CalledProcessError(1, "sqlite3"), True, "registro migrazioni fallito"),
])
def test_migrazione_fallita(b, errore, dati, perche):
    b.migrazioni = errore
    assert b.esegui()[0] == 1
    rb = next(e for e in b.ev if e[0] == "ROLLBACK")
    assert rb[1] is dati and perche in rb[2]
    assert ("compose", "installato", "up") not in b.ev


def test_le_migrazioni_eseguite_si_contano(b):
    b.migrazioni = (["0001", "0002"], True)
    assert b.esegui()[0] == 0
    assert "2 migrazioni applicate" in _uscita(b)


@pytest.mark.parametrize("dati", [False, True])
def test_up_fallito_torna_indietro_coi_dati_se_le_migrazioni_li_hanno_toccati(b, dati):
    b.migrazioni = (["0001"] if dati else [], dati)
    b.esito["up"] = 1
    assert b.esegui()[0] == 1
    rb = next(e for e in b.ev if e[0] == "ROLLBACK")
    assert rb[1] is dati and rb[2] == "compose up fallito"
    assert "health_gate" not in b.nomi()


def test_salute_rossa_torna_indietro(b):
    b.salute = [(False, "archive-mcp unhealthy")]
    assert b.esegui()[0] == 1
    rb = next(e for e in b.ev if e[0] == "ROLLBACK")
    assert rb[2] == "health-gate: archive-mcp unhealthy"
    assert "current" not in b.st and "status_write" not in b.nomi()
