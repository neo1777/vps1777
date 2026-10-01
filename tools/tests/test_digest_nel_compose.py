"""H22: «gira solo il digest verificato» vive anche nel compose, non solo nella CLI.

Prima (fino al 27/09/2026) l'invariante lo imponeva la CLI DOPO il pull: `verify_digests`
confronta le immagini scaricate per tag con `images.lock` del bundle firmato. Un
`docker compose pull && up` lanciato a mano, fuori dalla CLI, prendeva invece quello che
il registro serviva per quel tag in quel momento.

Ora ogni immagine vps1777 in `compose.yaml` è
`…/vps1777-<svc>:${VPS1777_TAG}${VPS1777_DIGEST_<SVC>:+@${VPS1777_DIGEST_<SVC>}}`, e i digest
li scrive nel `.env` SOLO la CLI, insieme al tag e dopo averli verificati. Qualunque
comando compose nella cartella (a mano compreso) gira il digest verificato.

Tre trappole misurate, che questi test tengono ferme:
- `docker pull nome:tag@digest` scarica l'immagine SENZA il tag (misurato: `<none>`), e
  `verify_digests` la cerca per tag ⇒ il pull della CLI si fa coi digest SPENTI (per tag,
  come prima), si verifica, e solo dopo si accendono per `up`;
- le variabili passate in `env=` vincono sul `.env`: un `env={"VPS1777_TAG": prev}` senza
  digest, durante un rollback, farebbe girare il tag VECCHIO coi digest NUOVI rimasti nel
  `.env` — cioè le immagini nuove. Ogni env di versione nasce da `versione_env`;
- tag e digest si scrivono in UNA sostituzione del `.env`: sei scritture separate
  lascerebbero, dopo un'interruzione, un tag con i digest di un'altra versione.
"""
from __future__ import annotations

import ast
import importlib.util
import os
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("vps1777_cli", _ROOT / "tools" / "vps1777.py")
v = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v)

SHA = "sha256:" + "a" * 64
LOCK = {svc: f"ghcr.io/neo1777/vps1777-{svc}@{SHA}" for svc in v.SERVICES}


def test_ogni_immagine_vps1777_del_compose_porta_il_suo_digest():
    righe = [r for r in (_ROOT / "compose.yaml").read_text().splitlines()
             if re.search(r"^\s+image: .*/vps1777-", r)]
    assert len(righe) >= len(v.SERVICES)
    for r in righe:
        svc = re.search(r"/vps1777-([a-z0-9-]+):", r).group(1)
        var = v.digest_var(svc)
        assert r.rstrip().endswith(f"${{VPS1777_TAG:-dev}}${{{var}:+@${{{var}}}}}"), r


def test_l_overlay_di_caddy_dns01_porta_il_suo_digest_nella_stessa_forma():
    """caddy-dns01 (01/10/2026) è un'immagine del progetto che NON sta in compose.yaml ma
    nel suo overlay: il test sopra legge solo compose.yaml, e senza questo la riga
    dell'overlay potrebbe perdere il pin del digest senza che niente fallisca."""
    righe = [r for r in (_ROOT / "compose.ops.caddy-dns01.yaml").read_text().splitlines()
             if re.search(r"^\s+image: ", r)]
    assert len(righe) == 1, righe
    var = v.digest_var("caddy-dns01")
    assert var == "VPS1777_DIGEST_CADDY_DNS01"
    assert righe[0].strip() == (
        "image: ${VPS1777_IMAGE_BASE:-ghcr.io/neo1777}/vps1777-caddy-dns01:"
        f"${{VPS1777_TAG:-dev}}${{{var}:+@${{{var}}}}}"), righe[0]


def test_ogni_servizio_di_SERVICES_ha_la_sua_riga_image():
    """Un servizio in SERVICES senza riga `image:` avrebbe un digest scritto nel .env che
    nessun compose legge: la verifica ci sarebbe, il pin no."""
    testo = "\n".join((_ROOT / f).read_text() for f in ("compose.yaml", "compose.ops.caddy-dns01.yaml"))
    trovati = set(re.findall(r"/vps1777-([a-z0-9-]+):\$\{VPS1777_TAG", testo))
    assert trovati == set(v.SERVICES), trovati ^ set(v.SERVICES)


def test_versione_env_estrae_i_digest_dal_lock():
    env = v.versione_env("1.2.3", LOCK)
    assert env["VPS1777_TAG"] == "1.2.3"
    assert {env[v.digest_var(s)] for s in v.SERVICES} == {SHA}
    assert len(env) == 1 + len(v.SERVICES)


def test_senza_lock_i_digest_sono_vuoti_cioe_spenti():
    """Vuoti e PRESENTI: una variabile vuota in env= vince su quella piena del .env."""
    for rif in (None, {}, {"gateway": "ghcr.io/x/vps1777-gateway:1.0"}, {"gateway": "@md5:x"}):
        env = v.versione_env("1.2.3", rif)
        assert all(env[v.digest_var(s)] == "" for s in v.SERVICES), rif


def test_tag_e_digest_si_scrivono_in_una_sola_sostituzione(tmp_path):
    envf = tmp_path / ".env"
    envf.write_text("ALTRO=1\nVPS1777_TAG=0.9.0\n")
    envf.chmod(0o600)
    sostituzioni = []
    orig = Path.replace
    Path.replace = lambda self, dst: (sostituzioni.append(dst), orig(self, dst))[1]
    try:
        v.versione_set(tmp_path, "1.2.3", LOCK)
    finally:
        Path.replace = orig
    assert len(sostituzioni) == 1
    letto = v.env_read(tmp_path)
    assert letto["VPS1777_TAG"] == "1.2.3" and letto["ALTRO"] == "1"
    assert letto[v.digest_var("ocr")] == SHA
    assert (envf.stat().st_mode & 0o777) == 0o600
    if os.geteuid() != 0:
        assert envf.read_text().count("VPS1777_TAG=") == 1


def _albero():
    return ast.parse((_ROOT / "tools" / "vps1777.py").read_text())


def _funzione_di(albero, nodo_cercato):
    for f in ast.walk(albero):
        if isinstance(f, ast.FunctionDef):
            for n in ast.walk(f):
                if n is nodo_cercato:
                    yield f.name


def test_nessun_env_di_versione_a_mano():
    """Un dict con la chiave VPS1777_TAG fuori da versione_env è un env senza digest."""
    albero = _albero()
    fuori = []
    for n in ast.walk(albero):
        if isinstance(n, ast.Dict) and any(
                isinstance(k, ast.Constant) and k.value == "VPS1777_TAG" for k in n.keys):
            dove = set(_funzione_di(albero, n))
            if "versione_env" not in dove:
                fuori.append((n.lineno, dove))
    assert not fuori, f"env di versione scritti a mano (senza digest): {fuori}"


def test_nessun_env_set_del_tag_a_mano():
    """Il tag nel .env si scrive solo con versione_set, insieme ai digest."""
    albero = _albero()
    fuori = []
    for n in ast.walk(albero):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "env_set"
                and len(n.args) >= 2 and isinstance(n.args[1], ast.Constant)
                and n.args[1].value == "VPS1777_TAG"):
            fuori.append((n.lineno, set(_funzione_di(albero, n))))
    assert not fuori, f"env_set del tag senza i digest: {fuori}"


def test_il_pull_della_cli_va_per_tag():
    """Ogni `compose … pull` della CLI passa un env coi digest spenti
    (`versione_env(x, None)`): per digest l'immagine arriverebbe senza tag, e
    `verify_digests` non la troverebbe."""
    albero = _albero()
    assegnazioni: dict[tuple[str, str], ast.AST] = {}
    for f in ast.walk(albero):
        if isinstance(f, ast.FunctionDef):
            for n in ast.walk(f):
                if isinstance(n, ast.Assign) and len(n.targets) == 1 \
                        and isinstance(n.targets[0], ast.Name):
                    assegnazioni[(f.name, n.targets[0].id)] = n.value
    pull = 0
    for f in ast.walk(albero):
        if not isinstance(f, ast.FunctionDef):
            continue
        for n in ast.walk(f):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == "run" and n.args and isinstance(n.args[0], ast.List)):
                continue
            if not any(isinstance(e, ast.Constant) and e.value == "pull" for e in n.args[0].elts):
                continue
            pull += 1
            env = next((k.value for k in n.keywords if k.arg == "env"), None)
            if isinstance(env, ast.Name):
                env = assegnazioni.get((f.name, env.id))
            ok = (isinstance(env, ast.Call) and isinstance(env.func, ast.Name)
                  and env.func.id == "versione_env" and len(env.args) == 2
                  and isinstance(env.args[1], ast.Constant) and env.args[1].value is None)
            assert ok, f"{f.name}:{n.lineno}: il pull non passa versione_env(…, None)"
    assert pull >= 2, "non trovo i pull di update e bootstrap"
