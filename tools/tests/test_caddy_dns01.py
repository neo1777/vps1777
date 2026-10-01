"""Feature `caddy-dns01` (01/10/2026): Caddy con la sfida ACME DNS-01 via Cloudflare.

Prima di oggi docs/INGRESS.md diceva che DNS-01 «NON è predisposto», e i commenti di
`compose.ingress.caddy.yaml` e di `ingress/Caddyfile` rimandavano a un override che non
esisteva. Ora è una feature dichiarata (VPS1777_FEATURES), con un'immagine costruita e
firmata dal progetto. Questi test tengono ferme le parti che possono derivare in silenzio:

- i DUE Caddyfile devono restare la stessa configurazione a meno del blocco `acme_dns`:
  chi cambia il tetto del body o un header in uno e non nell'altro avrebbe due ingressi
  diversi secondo come si ottiene il certificato — e se ne accorgerebbe solo chi usa
  quello non toccato;
- l'overlay ridefinisce SOLO `caddy`, resta dentro il profilo `ingress.caddy` (con un
  altro ingresso il servizio non deve partire) e legge il token da un secret-file;
- la CLI rifiuta la feature con un ingresso diverso, monta l'overlay senza un profilo in
  più, e `verify_digests` non pretende l'immagine opzionale quando lo stack non la usa.
"""
from __future__ import annotations

import difflib
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

RADICE = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("vps1777_cli_dns01", RADICE / "tools" / "vps1777.py")
v = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v)

OVERLAY = RADICE / "compose.ops.caddy-dns01.yaml"
CADDYFILE = RADICE / "ingress" / "Caddyfile"
CADDYFILE_DNS01 = RADICE / "ingress" / "Caddyfile.dns01"
RIGA_ACME = "acme_dns cloudflare {file./run/secrets/cf_api_token}"


# ─────────────────────────────────────────── i due Caddyfile

def test_i_due_caddyfile_differiscono_solo_per_il_blocco_acme_dns():
    """Anti-deriva: Caddyfile.dns01 = Caddyfile + righe AGGIUNTE, tutte commenti tranne
    UNA, che è la riga `acme_dns` col token letto da file."""
    a = CADDYFILE.read_text(encoding="utf-8").splitlines()
    b = CADDYFILE_DNS01.read_text(encoding="utf-8").splitlines()
    aggiunte: list[str] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        assert op == "insert", (
            f"i due Caddyfile divergono oltre il blocco acme_dns ({op}):\n"
            f"  Caddyfile       {i1 + 1}-{i2}: {a[i1:i2]}\n"
            f"  Caddyfile.dns01 {j1 + 1}-{j2}: {b[j1:j2]}\n"
            "Chi cambia una copia cambia l'altra (vedi il commento in testa ai due file).")
        aggiunte += b[j1:j2]
    codice = [r.strip() for r in aggiunte if r.strip() and not r.strip().startswith("#")]
    assert codice == [RIGA_ACME], codice


def test_la_riga_acme_dns_sta_nelle_opzioni_globali():
    """Il blocco globale è il primo `{` a colonna 0; la riga deve stare lì dentro, non
    nel blocco del sito (dove Caddy la rifiuterebbe come direttiva sconosciuta)."""
    righe = CADDYFILE_DNS01.read_text(encoding="utf-8").splitlines()
    apre = righe.index("{")
    chiude = next(i for i in range(apre, len(righe)) if righe[i] == "}")
    assert any(r.strip() == RIGA_ACME for r in righe[apre:chiude])


def test_il_caddyfile_normale_non_ha_piu_la_riga_commentata_da_scommentare():
    """La vecchia istruzione «scommenta + carica plugin» portava a un token in un env
    (`{env.CF_API_TOKEN}`) su un'immagine senza plugin: non funzionava in nessun modo."""
    testo = CADDYFILE.read_text(encoding="utf-8")
    assert "acme_dns" not in "\n".join(
        r for r in testo.splitlines() if not r.lstrip().startswith("#"))
    assert "CF_API_TOKEN" not in testo
    assert "caddy-dns01" in testo     # il rimando alla feature c'è


# ─────────────────────────────────────────── l'overlay

def _overlay() -> dict:
    return yaml.safe_load(OVERLAY.read_text(encoding="utf-8"))


def test_l_overlay_ridefinisce_solo_caddy_dentro_il_profilo_dell_ingresso():
    dati = _overlay()
    assert set(dati["services"]) == {"caddy"}
    caddy = dati["services"]["caddy"]
    # con un altro ingresso il servizio deve restare spento: senza la riga, il
    # frammento da solo sarebbe un servizio sempre acceso
    assert caddy["profiles"] == ["ingress.caddy"]
    # le porte si ereditano da compose.ingress.caddy.yaml (e con loro l'eccezione
    # 80/443 di test_porte_con_bind, legata a quel file)
    assert "ports" not in caddy
    assert "./ingress/Caddyfile.dns01:/etc/caddy/Caddyfile:ro" in caddy["volumes"]


def test_il_token_arriva_da_un_secret_file_mai_da_un_env():
    dati = _overlay()
    caddy = dati["services"]["caddy"]
    assert caddy["secrets"] == ["cf_api_token"]
    assert dati["secrets"]["cf_api_token"] == {"file": "./secrets/cf_api_token.txt"}
    assert "environment" not in caddy, "nessun valore nell'ambiente: `docker inspect` lo mostrerebbe"
    # il secret è un bind mount 600 di UID 1000 e Caddy è root senza capability:
    # senza DAC_OVERRIDE il file non si legge (misurato il 01/10/2026)
    assert "DAC_OVERRIDE" in caddy["cap_add"] and "NET_BIND_SERVICE" in caddy["cap_add"]
    assert "DAC_READ_SEARCH" not in caddy["cap_add"]


def test_il_segreto_e_classificato_non_generabile():
    """Un token Cloudflare fabbricato a caso è un file pieno e sbagliato: il pre-flight
    tornerebbe verde e Caddy non otterrebbe mai il certificato."""
    assert "cf_api_token" in v.SEGRETI_NON_GENERABILI
    assert "cf_api_token" not in v.SEGRETI_GENERABILI


def _compose(*args: str, env: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", "compose", "--env-file", str(env), *args],
                          cwd=RADICE, capture_output=True, text=True, timeout=60)


@pytest.mark.skipif(not shutil.which("docker"), reason="docker assente: il merge non si misura")
@pytest.mark.parametrize("ingresso, caddy_atteso", [
    ("tailscale", False), ("cloudflared", False), ("caddy", True)])
def test_il_merge_compose_accende_caddy_solo_con_l_ingresso_caddy(tmp_path, ingresso, caddy_atteso):
    """La misura vera, non la lettura del file: compose fonde i tre file e decide."""
    env = tmp_path / "finto.env"
    env.write_text("CADDY_DOMAIN=vps.example.invalid\nCADDY_EMAIL=ops@example.invalid\n"
                   "TELEGRAM_OWNER_ID=1\nADMIN_EMAIL=ops@example.invalid\nVPS1777_TAG=9.9.9\n")
    r = _compose("-f", "compose.yaml", "-f", f"compose.ingress.{ingresso}.yaml",
                 "-f", OVERLAY.name, "--profile", f"ingress.{ingresso}",
                 "config", "--services", env=env)
    if r.returncode != 0 and "is not a docker command" in r.stderr:
        pytest.skip("docker compose v2 assente")
    assert r.returncode == 0, r.stderr
    assert ("caddy" in r.stdout.split()) is caddy_atteso, r.stdout
    if caddy_atteso:
        r = _compose("-f", "compose.yaml", "-f", "compose.ingress.caddy.yaml", "-f", OVERLAY.name,
                     "--profile", "ingress.caddy", "config", "--format", "json", env=env)
        assert r.returncode == 0, r.stderr
        caddy = json.loads(r.stdout)["services"]["caddy"]
        assert caddy["image"] == "ghcr.io/neo1777/vps1777-caddy-dns01:9.9.9"
        assert {(p["target"], p["published"]) for p in caddy["ports"]} == {(80, "80"), (443, "443")}
        montato = {m["target"]: m["source"] for m in caddy["volumes"]}
        assert montato["/etc/caddy/Caddyfile"].endswith("ingress/Caddyfile.dns01")
        assert "/data" in montato          # i certificati restano nel volume dell'ingresso


# ─────────────────────────────────────────── la CLI

def _repo(tmp_path: Path, env: str) -> Path:
    (tmp_path / ".env").write_text(env)
    return tmp_path


def test_cli_monta_l_overlay_senza_profilo_in_piu_con_l_ingresso_caddy(tmp_path):
    repo = _repo(tmp_path, "INGRESS_PROFILE=ingress.caddy\nVPS1777_FEATURES=caddy-dns01\n")
    cmd = v.compose_cmd(repo)
    assert str(repo / "compose.ops.caddy-dns01.yaml") in cmd
    profili = [cmd[i + 1] for i, x in enumerate(cmd) if x == "--profile"]
    assert profili == ["ingress.caddy"], profili


@pytest.mark.parametrize("ingresso", ["ingress.tailscale", "ingress.cloudflared"])
def test_cli_rifiuta_caddy_dns01_con_un_altro_ingresso(tmp_path, capsys, ingresso):
    """Innocuo (il servizio resterebbe spento) ma silenzioso: proprio la forma che
    VPS1777_FEATURES esiste per impedire. Il rifiuto vale per il comando compose E per
    il pre-flight dei segreti, che devono vedere gli stessi file."""
    repo = _repo(tmp_path, f"INGRESS_PROFILE={ingresso}\nVPS1777_FEATURES=backup,caddy-dns01\n")
    (repo / "compose.yaml").write_text("services: {}\n")
    for chiama in (lambda: v.compose_cmd(repo), lambda: v._compose_sorgenti(repo, repo)):
        with pytest.raises(SystemExit):
            chiama()
        err = capsys.readouterr().err
        assert "caddy-dns01" in err and "ingress.caddy" in err and ingresso in err


def test_cli_senza_la_feature_non_tocca_caddy(tmp_path):
    repo = _repo(tmp_path, "INGRESS_PROFILE=ingress.caddy\nVPS1777_FEATURES=backup\n")
    assert not any("caddy-dns01" in x for x in v.compose_cmd(repo))


def test_il_preflight_dei_segreti_vede_cf_api_token_quando_l_overlay_e_montato(tmp_path):
    repo = _repo(tmp_path, "INGRESS_PROFILE=ingress.caddy\nVPS1777_FEATURES=caddy-dns01\n")
    (repo / "secrets").mkdir()
    (repo / "compose.yaml").write_text("services: {}\n")
    shutil.copy(OVERLAY, repo / OVERLAY.name)
    sorgenti = v._compose_sorgenti(repo, repo)
    assert repo / OVERLAY.name in sorgenti
    fuori = v._secrets_mancanti(sorgenti, repo)
    assert len(fuori) == 1 and "cf_api_token" in fuori[0], fuori


# ─────────────────────────────────────────── verify_digests e l'immagine opzionale

SHA = "sha256:" + "b" * 64


def _finto_docker(monkeypatch, presenti: set[str], immagini_compose: list[str] | None = None):
    """`run` finto: `image inspect` risponde solo per le immagini `presenti`;
    `config --images` restituisce `immagini_compose`."""
    chiesti: list[str] = []

    def run(cmd, capture=False, check=True, env=None):   # noqa: ARG001
        if cmd[:3] == ["docker", "image", "inspect"]:
            ref = cmd[-1]
            chiesti.append(ref)
            if ref in presenti:
                nome = ref.rsplit(":", 1)[0]
                return SimpleNamespace(returncode=0, stdout=json.dumps([f"{nome}@{SHA}"]), stderr="")
            return SimpleNamespace(returncode=1, stdout="", stderr="No such image")
        if "config" in cmd and "--images" in cmd:
            if immagini_compose is None:
                return SimpleNamespace(returncode=1, stdout="", stderr="compose rotto")
            return SimpleNamespace(returncode=0, stdout="\n".join(immagini_compose) + "\n", stderr="")
        raise AssertionError(f"comando inatteso: {cmd}")

    monkeypatch.setattr(v, "run", run)
    return chiesti


def _lock(repo: Path, ver: str) -> dict[str, str]:
    return {s: v.image_ref(repo, s, ver).rsplit(":", 1)[0] + f"@{SHA}" for s in v.SERVICES}


def test_verify_a_feature_spenta_non_pretende_caddy_dns01_e_lo_dice(tmp_path, monkeypatch, capsys):
    """Prima pretendeva OGNI servizio di SERVICES sul disco dopo il pull: con caddy-dns01
    nel lock, ogni update di chi non ha la feature sarebbe morto qui."""
    repo = _repo(tmp_path, "INGRESS_PROFILE=ingress.tailscale\nVPS1777_FEATURES=none\n")
    usate = [v.image_ref(repo, s, "1.2.3") for s in v.SERVICES if s != "caddy-dns01"]
    chiesti = _finto_docker(monkeypatch, set(usate), usate)
    attivi = v.immagini_attive(repo, "1.2.3")
    assert attivi == set(v.SERVICES) - {"caddy-dns01"}
    v.verify_digests(repo, _lock(repo, "1.2.3"), "1.2.3", attivi)
    assert v.image_ref(repo, "caddy-dns01", "1.2.3") not in chiesti
    assert "caddy-dns01: nel lock ma non attivo" in capsys.readouterr().out


def test_verify_a_feature_accesa_verifica_anche_caddy_dns01(tmp_path, monkeypatch):
    repo = _repo(tmp_path, "INGRESS_PROFILE=ingress.caddy\nVPS1777_FEATURES=caddy-dns01\n")
    usate = [v.image_ref(repo, s, "1.2.3") for s in v.SERVICES]
    chiesti = _finto_docker(monkeypatch, set(usate), usate)
    attivi = v.immagini_attive(repo, "1.2.3")
    assert "caddy-dns01" in attivi
    v.verify_digests(repo, _lock(repo, "1.2.3"), "1.2.3", attivi)
    assert v.image_ref(repo, "caddy-dns01", "1.2.3") in chiesti
    # …e se l'immagine attiva NON c'è, il verify fallisce come per le altre
    _finto_docker(monkeypatch, set(usate) - {v.image_ref(repo, "caddy-dns01", "1.2.3")}, usate)
    with pytest.raises(RuntimeError, match="caddy-dns01"):
        v.verify_digests(repo, _lock(repo, "1.2.3"), "1.2.3", attivi)


def test_se_compose_non_dice_quali_immagini_usa_non_e_un_verde(tmp_path, monkeypatch):
    repo = _repo(tmp_path, "INGRESS_PROFILE=ingress.caddy\nVPS1777_FEATURES=none\n")
    _finto_docker(monkeypatch, set(), None)
    with pytest.raises(RuntimeError, match="non so quali immagini"):
        v.immagini_attive(repo, "1.2.3")


def test_secrets_status_attende_cf_api_token_solo_con_la_feature(tmp_path, monkeypatch):
    monkeypatch.setattr(v, "nlm_cookie_status", lambda repo: None)
    for feats, atteso in (("none", False), ("caddy-dns01", True)):
        d = tmp_path / feats
        d.mkdir()
        repo = _repo(d, f"INGRESS_PROFILE=ingress.caddy\nVPS1777_FEATURES={feats}\n")
        (repo / "secrets").mkdir()
        (repo / "onboarding").mkdir()
        v.cmd_secrets_status(repo, SimpleNamespace(notify=False, json=False))
        dati = json.loads((repo / "onboarding" / "secrets_status.json").read_text())
        assert any("DNS-01" in m for m in dati.get("mancanti", [])) is atteso, dati.get("mancanti")


def test_le_immagini_obbligatorie_si_verificano_anche_se_attivi_le_dimentica(tmp_path, monkeypatch):
    """Se il nome che stampa compose e `image_ref` divergessero, `immagini_attive`
    uscirebbe vuoto: un verify che salta tutto sarebbe un verde falso su ogni update.
    Solo le immagini di SERVICES_OPZIONALI possono essere saltate."""
    repo = _repo(tmp_path, "INGRESS_PROFILE=ingress.tailscale\nVPS1777_FEATURES=none\n")
    obbligatorie = [v.image_ref(repo, s, "1.2.3") for s in v.SERVICES
                    if s not in v.SERVICES_OPZIONALI]
    chiesti = _finto_docker(monkeypatch, set(obbligatorie), [])
    v.verify_digests(repo, _lock(repo, "1.2.3"), "1.2.3", set())
    assert set(obbligatorie) <= set(chiesti)
    _finto_docker(monkeypatch, set(obbligatorie[1:]), [])
    with pytest.raises(RuntimeError):
        v.verify_digests(repo, _lock(repo, "1.2.3"), "1.2.3", set())
