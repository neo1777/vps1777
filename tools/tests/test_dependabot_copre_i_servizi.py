"""Ogni servizio Python è sorvegliato da Dependabot — o il test lo nomina.

🔓 Round-16, rilievo `23cc4783`. `dependabot.yml` copriva github-actions, docker
   e docker-compose: **nessun ecosystem per Python**. Le dipendenze che il
   gateway IMPORTA — non l'immagine base, quelle dentro — non le guardava
   nessuno.

⚠️ E non è igiene: `docs/ARCHITECTURE.md` fa poggiare una delle garanzie più
   forti del prodotto (*l'IP del client non è falsificabile*) sul comportamento
   di `ProxyHeadersMiddleware`, che è un dettaglio interno di **uvicorn** — e
   `services/gateway/pyproject.toml` lo dichiara `>=0.32.0`, senza tetto, su un
   pacchetto in 0.x.

🔑 Il test guarda la RELAZIONE, non una lista: «esiste un servizio con un
   pyproject che nessun ecosystem copre?». Una lista scritta a mano invecchia
   in silenzio al primo servizio nuovo; questa domanda no.
"""
from __future__ import annotations

import re
from pathlib import Path

# 🔴 STDLIB-ONLY, e la prima versione NON lo era. Usavo `pytest.importorskip("yaml")`
#   con questo motivo: «in CI c'è (`uv run --with pyyaml`), e uno skip qui non è un
#   verde». **Era falso**: la CI esegue questa suite con `uvx pytest tools/tests/`
#   (ci.yml:177), che è stdlib-only — quindi il test veniva SALTATO, e uno skip si
#   legge come un pass. *Ho scritto una frase falsa dentro la ragione dello skip:
#   la parte che serviva a rassicurare era proprio quella sbagliata.*
#   Trovato da `abdd732a` revisionando, non da me.
# 🔑 Quindi niente pyyaml: leggo il file con un parser MINIMO che capisce SOLO la
#   forma che usiamo — e che **fallisce rumorosamente** se la forma cambia,
#   invece di restituire meno e passare.

RADICE = Path(__file__).resolve().parents[2]
DEPENDABOT = RADICE / ".github" / "dependabot.yml"
SERVIZI = RADICE / "services"


def _blocchi_updates(testo: str) -> list[dict]:
    """Parser minimo di `updates:` — SOLO la forma che usiamo.

    ⚠️ Capisce `- package-ecosystem: X`, `directory: /y` e `directories:` con la
    lista a trattini. **Non è un parser YAML** e non pretende di esserlo: se il
    file passasse a un'altra forma (ancore, flow-style, chiavi annidate), questo
    lo direbbe restituendo zero blocchi — e il test sotto fallisce su quello,
    invece di dichiarare «coperto» per non aver capito.
    """
    blocchi: list[dict] = []
    corrente: dict | None = None
    in_dirs = False
    for riga in testo.splitlines():
        if re.match(r"\s*#", riga) or not riga.strip():
            continue
        m = re.match(r"\s*-\s*package-ecosystem:\s*[\"']?([\w-]+)", riga)
        if m:
            corrente = {"eco": m.group(1), "dirs": []}
            blocchi.append(corrente)
            in_dirs = False
            continue
        if corrente is None:
            continue
        m = re.match(r"\s*directory:\s*[\"']?([^\s\"']+)", riga)
        if m:
            corrente["dirs"].append(m.group(1))
            in_dirs = False
            continue
        if re.match(r"\s*directories:\s*$", riga):
            in_dirs = True
            continue
        if in_dirs:
            m = re.match(r"\s*-\s*[\"']?([^\s\"']+)", riga)
            if m:
                corrente["dirs"].append(m.group(1))
            else:
                in_dirs = False
    return blocchi


def _coperte() -> set[str]:
    """Le directory coperte da un ecosystem Python, normalizzate."""
    blocchi = _blocchi_updates(DEPENDABOT.read_text(encoding="utf-8"))
    assert blocchi, (
        "il parser minimo non ha capito NESSUN blocco `updates`: o il file ha "
        "cambiato forma, o la sonda è cieca. In entrambi i casi NON è un verde.")
    return {d.strip("/") for b in blocchi if b["eco"] in ("uv", "pip") for d in b["dirs"]}


def test_ogni_servizio_con_pyproject_e_sorvegliato():
    servizi = {f"services/{p.parent.name}"
               for p in SERVIZI.glob("*/pyproject.toml")}
    assert servizi, "nessun servizio con pyproject trovato: il test non ha guardato niente"
    scoperti = sorted(servizi - _coperte())
    assert not scoperti, (
        f"servizi Python che NESSUN ecosystem Dependabot copre: {scoperti}. "
        "Le loro dipendenze possono avanzare senza che nessuno lo veda — ed è "
        "il rilievo 23cc4783."
    )


def test_la_sonda_SA_DIRE_DI_NO():
    """Controprova: se la copertura sparisse, il test sopra fallirebbe?

    Senza questa, `_coperte()` potrebbe restituire tutto e il verde non
    distinguerebbe «coperti» da «la sonda non guarda».
    """
    coperte = _coperte()
    assert coperte, "zero directory coperte: o la config è vuota, o la sonda è cieca"
    assert "services/inventato-che-non-esiste" not in coperte


def test_i_major_NON_entrano_da_soli():
    """Un major che entra da solo in un servizio che regge una garanzia di
    sicurezza è esattamente ciò che non vogliamo — la stessa scelta già fatta
    per le action (#48/#49) e per le immagini."""
    blocchi = _blocchi_updates(DEPENDABOT.read_text(encoding="utf-8"))
    py = [b for b in blocchi if b["eco"] in ("uv", "pip")]
    assert py, "nessun ecosystem Python: vedi il test sopra"
    for u in py:
        # il blocco `ignore` lo cerco nel testo del file: il parser minimo non
        # scende nei sotto-blocchi, e fingere che lo faccia sarebbe peggio.
        testo = DEPENDABOT.read_text(encoding="utf-8")
        coda = testo[testo.index(f"package-ecosystem: {u['eco']}"):]
        assert "version-update:semver-major" in coda, (
            "l'ecosystem Python non ignora i major: entrerebbero da soli")
