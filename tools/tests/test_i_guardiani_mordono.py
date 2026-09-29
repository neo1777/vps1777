"""I guardiani di vps1777 mordono ancora? Per ciascuno: un guasto costruito, e tre tempi.

PERCHÉ ESISTE. Un guardiano spento somiglia in tutto a uno che non ha mai trovato niente:
esce 0, stampa il suo ✓, e la CI è verde. Cinque presìdi del repo lo sanno dimostrare da
sé con la loro autoprova (confronta-installer, doc-riferimenti, coordinate-nei-doc,
gate-locale, esegui-test-bash). Gli altri no — e alcuni di quelli sono i più importanti:
l'anti-leak di un repo PUBBLICO, il registro dei rilievi di sicurezza, il ledger delle
feature, il pre-commit.

Per ognuno, su una COPIA del repo (mai sul repo vero), si misurano tre tempi:
  (a) è AGGANCIATO — una riga di codice (non un commento) lo esegue: in un workflow, o
      nell'installatore degli hook. Un presidio che nessuno lancia non fallisce mai;
  (b) MORDE — sul guasto esce ≠0 e il messaggio dice la RAGIONE attesa. Un rosso per
      la ragione sbagliata (un import rotto, un file che manca) non prova niente;
  (c) TACE sul sano — sulla stessa copia senza guasto esce 0. Senza questo, un guardiano
      che dice sempre di no passerebbe il punto (b).

COSA C'ERA GIÀ, e cosa aggiunge questo file:
  • `check_findings`: `test_checker_sa_rifiutare.py` manomette il REGISTRO. Qui si
    manomette il CODICE (l'evidenza sparisce dal file, il registro resta com'è), che è
    il caso della vita reale. E quel file usa `importorskip("yaml")`: nel job della CI,
    dove `tools/tests/` gira con `uvx pytest` senza PyYAML, SALTA per intero. Questo file
    non salta: se PyYAML non c'è, lo chiede a `uv`.
  • `check_no_leaks`: `test_no_leaks.py` prova le REGEX una per una; nessun test eseguiva
    il gate intero su un repo con dentro una credenziale. Qui sì, e si verifica anche che
    il valore NON finisca nell'output (il gate promette «dove, mai cosa»).
  • il pre-commit: `test_hook_versionati.py` controlla che sia versionato, valido e con
    gli strumenti della CI; nessun test lo faceva ARRIVARE a un commit vero.
  • `verify-features`: `test_ledger_condizione_o_data.py` prova la regola dei rinvii;
    i due versi del ledger (reale→dichiarato, dichiarato→reale) non avevano un guasto.
  • le traduzioni: `test_traduzioni_fresche.py` è il guardiano, e girava solo sul sano.

⚠️ FUORI, e perché: `onesta-a-macchina-nuda.sh` — il suo sano dipende dalla macchina (con
lo stack di sviluppo acceso, una prova può legittimamente misurare), quindi qui sarebbe un
rosso che dipende da cosa gira sul PC di chi lancia i test. La CI lo esegue su un runner,
che è nudo per costruzione.

Stdlib + pytest. Niente rete: la copia è locale (`git ls-files` → cartella temporanea →
`git init`), e PyYAML, se serve a `uv`, si cerca prima nella sua cache (`--offline`).
"""
from __future__ import annotations

import functools
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pytest

RADICE = Path(__file__).resolve().parents[2]
WORKFLOW = RADICE / ".github" / "workflows"

# L'identità dei commit nella copia, e una config git che non è quella di chi lancia:
# un `commit.gpgsign` o un `core.hooksPath` globale cambierebbero l'esito sotto i piedi.
GIT_ENV = {
    "GIT_AUTHOR_NAME": "guasto-costruito", "GIT_AUTHOR_EMAIL": "guasto@example.invalid",
    "GIT_COMMITTER_NAME": "guasto-costruito", "GIT_COMMITTER_EMAIL": "guasto@example.invalid",
    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
    "PYTHONDONTWRITEBYTECODE": "1",
}


def _env(**extra: str) -> dict[str, str]:
    return {**os.environ, **GIT_ENV, **extra}


def _git(copia: Path, *args: str, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(copia), *args], env=_env(**kw.pop("env", {})),
                          capture_output=True, text=True, check=kw.pop("check", True), **kw)


# ── la copia del repo ─────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def pristino(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """I file TRACCIATI, com'erano nella working tree, in un repo git nuovo con un commit.

    `git ls-files` e non una copia della cartella: niente `.venv`, niente file non
    tracciati che il gate anti-leak vedrebbe. E la storia non serve a nessun guardiano
    qui: la CI stessa fa checkout superficiale per il job lint.
    """
    dst = tmp_path_factory.mktemp("guardiani") / "repo"
    elenco = subprocess.run(["git", "-C", str(RADICE), "ls-files", "-z"],
                            capture_output=True, check=True).stdout.decode().split("\0")
    for rel in filter(None, elenco):
        src = RADICE / rel
        if not src.exists() and not src.is_symlink():
            continue                    # cancellato nella working tree: non c'è da copiare
        (dst / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst / rel, follow_symlinks=False)
    subprocess.run(["git", "init", "-q", "-b", "main", str(dst)], env=_env(), check=True)
    _git(dst, "add", "-A")
    _git(dst, "commit", "-q", "--no-verify", "-m", "copia per i guasti costruiti")
    return dst


@pytest.fixture
def copia(pristino: Path, tmp_path: Path) -> Path:
    """Una copia usa-e-getta per ogni prova: un guasto non deve sporcare la successiva."""
    dst = tmp_path / "repo"
    shutil.copytree(pristino, dst, symlinks=True)
    return dst


@functools.cache
def _python_con_yaml() -> tuple[str, ...]:
    """Un interprete con PyYAML, che `check_findings` e `verify-features` richiedono.

    🔴 NON `pytest.importorskip`: è il modo in cui `test_checker_sa_rifiutare.py` SALTA
    in CI (dove `tools/tests/` gira senza PyYAML). Un presidio che salta sempre è il
    buco che esiste per chiudere. Se PyYAML non c'è lo porta `uv` — che in CI c'è —
    prima dalla cache, senza rete; se manca anche `uv`, il test FALLISCE e lo dice.
    """
    try:
        import yaml  # noqa: F401
        return (sys.executable,)
    except ImportError:
        pass
    uv = shutil.which("uv")
    if uv:
        for extra in (("--offline",), ()):
            argv = (uv, "run", *extra, "--no-project", "--with", "pyyaml", "python3")
            if subprocess.run([*argv, "-c", "import yaml"], capture_output=True).returncode == 0:
                return argv
    pytest.fail("né PyYAML né `uv` disponibili: check_findings e verify-features non si "
                "possono eseguire — e un guardiano non eseguito non è un guardiano verde.")


def _esegui(copia: Path, argv: list[str], **env: str) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=copia, env=_env(**env), capture_output=True, text=True,
                          timeout=120, check=False)


# ── (a) gli agganci ───────────────────────────────────────────────────────────

def _eseguito_da_un_workflow(nome: str, *aghi: str) -> str | None:
    """None se una riga di CODICE di `nome` contiene tutti gli aghi; altrimenti il perché.
    Un commento che nomina il guardiano non lo esegue: si guardano solo le righe nude."""
    for riga in (WORKFLOW / nome).read_text(encoding="utf-8").splitlines():
        nuda = riga.strip()
        if nuda and not nuda.startswith("#") and all(a in nuda for a in aghi):
            return None
    return f"nessuna riga di codice di .github/workflows/{nome} esegue {' '.join(aghi)}"


def _installato_dagli_hook(copia: Path) -> str | None:
    r = _esegui(copia, ["bash", "tools/hooks/installa.sh"])
    installato = copia / ".git" / "hooks" / "pre-commit"
    if r.returncode != 0 or not installato.is_file():
        return f"tools/hooks/installa.sh non installa il pre-commit (exit {r.returncode})"
    if installato.read_bytes() != (copia / "tools" / "hooks" / "pre-commit").read_bytes():
        return "il pre-commit installato NON è quello versionato"
    return None


# ── i guardiani ───────────────────────────────────────────────────────────────

# Una credenziale FINTA nel formato che il gate riconosce (auth-key Tailscale: prefisso,
# tipo, almeno 8 caratteri alfanumerici). Composta a runtime: nel sorgente la sequenza
# intera non esiste, quindi il gate non scatta su QUESTO file — la stessa tecnica di
# `test_no_leaks.py` per i DSN, invece di allargare un'allowlist.
CREDENZIALE_FINTA = "tskey-" + "auth-" + "kQ7fZr2Lm9Xw4Tb"
MARCATORE_PRE_COMMIT = "COMMIT FERMATO dal gate anti-leak della CI"


def _commit(copia: Path) -> subprocess.CompletedProcess:
    """Il pre-commit si prova com'è usato: `git commit`, con l'hook installato.

    `HOME` finto: l'hook cerca prima un gate personale sotto la home di chi lo usa, e
    qui deve trovare solo quello del repo (`security/check_no_leaks.py`) — il ripiego
    che vale su qualunque clone. Il file sano è un `.md`: così ruff e shellcheck, gli
    altri due gate dell'hook, restano fuori dalla prova.
    """
    home = copia.parent / "home-finta"
    home.mkdir(exist_ok=True)
    (copia / "docs" / "nota-sana-del-commit.md").write_text("una nota innocua\n", encoding="utf-8")
    _git(copia, "add", "docs/nota-sana-del-commit.md")
    prima = _git(copia, "rev-parse", "HEAD").stdout.strip()
    assert _installato_dagli_hook(copia) is None
    r = _git(copia, "commit", "-q", "-m", "prova del pre-commit", check=False,
             env={"HOME": str(home)})
    dopo = _git(copia, "rev-parse", "HEAD").stdout.strip()
    r.stdout += f"\nHEAD avanzato: {'sì' if dopo != prima else 'no'}\n"
    return r


@dataclass(frozen=True)
class Guardiano:
    nome: str
    aggancio: Callable[[Path], str | None]
    esegui: Callable[[Path], subprocess.CompletedProcess]


GUARDIANI = {
    "check_no_leaks": Guardiano(
        "security/check_no_leaks.py — gate anti-leak",
        lambda c: _eseguito_da_un_workflow("ci.yml", "security/check_no_leaks.py"),
        lambda c: _esegui(c, [sys.executable, "security/check_no_leaks.py"]),
    ),
    "check_findings": Guardiano(
        "security/check_findings.py — il registro dei rilievi",
        lambda c: _eseguito_da_un_workflow("ci.yml", "security/check_findings.py"),
        lambda c: _esegui(c, [*_python_con_yaml(), "security/check_findings.py"]),
    ),
    "verify-features": Guardiano(
        "tools/verify-features.py — il ledger delle feature",
        lambda c: _eseguito_da_un_workflow("verify-features.yml", "tools/verify-features.py"),
        lambda c: _esegui(c, [*_python_con_yaml(), "tools/verify-features.py"]),
    ),
    "pre-commit": Guardiano(
        "tools/hooks/pre-commit — anti-leak al momento del commit",
        _installato_dagli_hook,
        _commit,
    ),
    "traduzioni": Guardiano(
        "test_traduzioni_fresche.py — il MANIFEST delle traduzioni",
        lambda c: _eseguito_da_un_workflow("ci.yml", "pytest", "tools/tests/"),
        lambda c: _esegui(c, [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                              "tools/tests/test_traduzioni_fresche.py"]),
    ),
}


# ── i guasti: ognuno rompe la copia e dice che cosa il guardiano deve NOMINARE ─

def _credenziale_in_un_doc(c: Path) -> list[str]:
    (c / "docs" / "appunti-guasto.md").write_text(
        f"chiave da incollare: {CREDENZIALE_FINTA}\n", encoding="utf-8")
    return ["[R2] docs/appunti-guasto.md:1", "auth-key Tailscale"]


def _export_di_sessione_forzato(c: Path) -> list[str]:
    """Il vettore che ha morso davvero: un transcript col nome innocuo, aggiunto con
    `-f` — che il `.gitignore` non ferma."""
    nome = "2026-01-02-030405-sessione-di-lavoro.txt"
    (c / nome).write_text("il detto-e-fatto di una sessione\n", encoding="utf-8")
    _git(c, "add", "-f", nome)
    return [f"[R1] {nome}", "export di sessione"]


def _evidenza_sparita_dal_codice(c: Path) -> list[str]:
    """Una voce `closed` il cui ago `contains` sparisce dal FILE (il registro resta
    intatto): il fix è stato tolto e il registro dice ancora «chiuso»."""
    scelta = subprocess.run([*_python_con_yaml(), "-c", """
import json, pathlib, yaml
reg = yaml.safe_load(open("security/findings.yml", encoding="utf-8"))
for f in reg["findings"]:
    if f.get("status") != "closed":
        continue
    for ev in f.get("evidence") or []:
        p = pathlib.Path(ev["file"])
        if p.suffix != ".py" or not p.is_file():
            continue
        for ago in ev.get("contains") or []:
            if len(ago) >= 12 and ago in p.read_text(encoding="utf-8"):
                print(json.dumps([f["id"], ev["file"], ago]))
                raise SystemExit(0)
raise SystemExit(3)
"""], cwd=c, capture_output=True, text=True, check=False)
    assert scelta.returncode == 0, (
        "nessuna voce `closed` con un'evidenza `contains` su un .py: il registro ha "
        f"cambiato forma e questo guasto non si può più costruire.\n{scelta.stderr[-400:]}")
    fid, file, ago = json.loads(scelta.stdout)
    p = c / file
    p.write_text(p.read_text(encoding="utf-8").replace(ago, "GUASTO_COSTRUITO"), encoding="utf-8")
    return [fid, "EVIDENZA SPARITA", file]


def _tool_mcp_senza_voce(c: Path) -> list[str]:
    """Reale → dichiarato: un tool MCP nel codice che il ledger non nomina."""
    server = c / "services" / "archive-mcp" / "app" / "server.py"
    server.write_text(server.read_text(encoding="utf-8")
                      + "\n\n@mcp.tool()\ndef guasto_costruito_senza_voce() -> str:\n"
                        "    return ''\n", encoding="utf-8")
    return ["[NON DICHIARATO]", "archive-mcp/guasto_costruito_senza_voce"]


def _tool_mcp_sparito(c: Path) -> list[str]:
    """Dichiarato → reale: una voce attiva il cui tool non esiste più (rinominato)."""
    ledger = (c / "features.yaml").read_text(encoding="utf-8")
    for blocco in re.split(r"\n  - id: ", ledger):
        m = re.search(r"mcp_tool:\s*\{service:\s*([\w-]+),\s*name:\s*(\w+)\}", blocco)
        if m and "status: active-default" in blocco:
            servizio, nome = m.groups()
            break
    else:
        pytest.fail("nessuna voce active-default con verify mcp_tool: il ledger ha cambiato forma")
    toccati = 0
    for f in (c / "services" / servizio / "app").rglob("*.py"):
        testo = f.read_text(encoding="utf-8")
        nuovo = re.sub(rf"\bdef {nome}\(", f"def {nome}_rinominato_dal_guasto(", testo)
        if nuovo != testo:
            f.write_text(nuovo, encoding="utf-8")
            toccati += 1
    assert toccati, f"la `def {nome}(` di {servizio} non si trova: il guasto non si costruisce"
    return ["[PERDITA]", f"tool MCP {servizio}/{nome} NON registrato"]


def _credenziale_in_un_commit(c: Path) -> list[str]:
    (c / "docs" / "appunti-guasto.md").write_text(
        f"chiave da incollare: {CREDENZIALE_FINTA}\n", encoding="utf-8")
    _git(c, "add", "docs/appunti-guasto.md")
    return [MARCATORE_PRE_COMMIT, "[R2] docs/appunti-guasto.md:1", "HEAD avanzato: no"]


def _italiano_mosso_dopo_la_traduzione(c: Path) -> list[str]:
    p = c / "CONTRIBUTING.it.md"
    p.write_text(p.read_text(encoding="utf-8") + "\nUna riga nuova, non tradotta.\n",
                 encoding="utf-8")
    return ["traduzioni STANTIE", "CONTRIBUTING.md (sorgente CONTRIBUTING.it.md cambiato)"]


GUASTI = [
    ("check_no_leaks", "credenziale in un doc", _credenziale_in_un_doc),
    ("check_no_leaks", "export di sessione aggiunto con -f", _export_di_sessione_forzato),
    ("check_findings", "evidenza sparita dal codice", _evidenza_sparita_dal_codice),
    ("verify-features", "tool MCP senza voce nel ledger", _tool_mcp_senza_voce),
    ("verify-features", "voce attiva il cui tool è sparito", _tool_mcp_sparito),
    ("pre-commit", "credenziale in un commit", _credenziale_in_un_commit),
    ("traduzioni", "MANIFEST stantio", _italiano_mosso_dopo_la_traduzione),
]


# ── i tre tempi ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("chiave", sorted(GUARDIANI))
def test_a_il_guardiano_e_agganciato(chiave: str, copia: Path) -> None:
    perche = GUARDIANI[chiave].aggancio(copia)
    assert perche is None, f"{GUARDIANI[chiave].nome}: {perche}. Un presidio che nessuno esegue non fallisce mai."


@pytest.mark.parametrize(("chiave", "descrizione", "rompi"), GUASTI,
                         ids=[f"{k}-{d}" for k, d, _ in GUASTI])
def test_b_sul_guasto_morde_per_la_ragione_giusta(chiave: str, descrizione: str,
                                                  rompi: Callable[[Path], list[str]],
                                                  copia: Path) -> None:
    ragioni = rompi(copia)
    r = GUARDIANI[chiave].esegui(copia)
    uscita = r.stdout + r.stderr
    assert r.returncode != 0, (
        f"{GUARDIANI[chiave].nome} è uscito 0 sul guasto «{descrizione}»: il guardiano "
        f"non morde più.\n{uscita[-1500:]}")
    assenti = [x for x in ragioni if x not in uscita]
    assert not assenti, (
        f"{GUARDIANI[chiave].nome} è rosso sul guasto «{descrizione}», ma NON per la ragione "
        f"attesa — manca {assenti} nell'output. Un rosso per un'altra causa non prova che "
        f"il guardiano veda questo guasto.\n{uscita[-1500:]}")
    assert CREDENZIALE_FINTA not in uscita, (
        f"{GUARDIANI[chiave].nome} ha STAMPATO la credenziale: il gate promette «dove, mai "
        "cosa», perché i log della CI di un repo pubblico sono pubblici.")


@pytest.mark.parametrize("chiave", sorted(GUARDIANI))
def test_c_sulla_copia_sana_tace(chiave: str, copia: Path) -> None:
    r = GUARDIANI[chiave].esegui(copia)
    assert r.returncode == 0, (
        f"{GUARDIANI[chiave].nome} è ROSSO sulla copia SANA (exit {r.returncode}): o il repo "
        "ha già un problema, o il guardiano dice di no a tutto — e allora il suo rosso sul "
        f"guasto non prova niente.\n{(r.stdout + r.stderr)[-1500:]}")


def test_ogni_guardiano_ha_almeno_un_guasto() -> None:
    """Un guardiano nell'elenco senza guasto passerebbe (a) e (c) e salterebbe (b), cioè
    il punto: aggiungerlo qui senza costruirne il guasto non deve restare verde."""
    senza = set(GUARDIANI) - {k for k, _, _ in GUASTI}
    assert not senza, f"guardiani senza un guasto costruito: {sorted(senza)}"
