"""I tre installer — un permesso si chiede all'OGGETTO, non al comando (H15, H38).

Il difetto che questi test proteggono (#66) non è che il `chmod` manchi: è che
c'è, e **sopprime il proprio esito due volte**.

    chmod 600 .env 2>/dev/null || true

`2>/dev/null` toglie il messaggio, `|| true` toglie l'exit — sotto `set -e` è
esattamente ciò che impedisce al fallimento di fermare l'installazione. Subito
dopo, in ogni punto, il successo viene dichiarato: due `ok "… .env 600"`, un
`ok "… dir sensibili 700"`, un `echo CONFIG_OK` e un `echo "ENV_OK"` — che è la
sonda che il PC legge per decidere se proseguire. Se il `chmod` fallisce
(filesystem read-only, ACL, attributo immutabile, proprietario diverso, `.env`
sostituito da una directory), i permessi restano quelli di prima **e
l'installazione dichiara riuscito il setup dei segreti.**

🔑 PERCHÉ QUESTO TEST *ESEGUE* INVECE DI CERCARE UNA STRINGA — ed è il punto di
   tutta la voce: il gate che presidia H15 (`security/findings.yml`, campo
   `evidence.contains`) verifica che il testo «chmod 600 .env» ESISTA nel file.
   Il testo esiste, nella forma che sopprime il proprio esito. **Un presidio che
   cerca un comando non può vedere un comando che si zittisce da solo**; uno che
   lo ESEGUE sì. Qui il frammento viene estratto dal `deploy.sh` vero e fatto
   girare con un `chmod` sabotato che finge di riuscire: se il blocco non se ne
   accorge, il test è rosso.

Solo stdlib. Nessuna rete, nessun ssh, nessun docker: il frammento è shell puro.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]

# 🔴 IL PERIMETRO NON È QUELLO DELLA ISSUE. #66 elencava tre punti, tutti in
#    `deploy.sh` — perché è lì che li aveva cercati. La stessa riga sta anche in
#    `setup.sh` (l'installazione da zero) e in `installer/engine.py` (due volte,
#    l'installer con la UI): SEI, non tre. Chi cerca un difetto lo trova nel file
#    da cui è partito; questo elenco è il rimedio, e va allargato — non ridotto —
#    se domani un quarto percorso scrive `.env`.
_SORGENTI = ("deploy.sh", "setup.sh", "installer/engine.py")

# 🔑 E IL PERIMETRO GIUSTO NON È NEMMENO «i chmod su .env»: è la FORMA del difetto,
#    cioè ogni `chmod … 2>/dev/null || true`. Cercando la parola della issue («.env»)
#    ne restava fuori uno nella riga accanto — `chmod 700 secrets backups onboarding`
#    a deploy.sh:285, sotto la stessa `ok "… dir sensibili 700"` (H38). Che fosse
#    un'anomalia e non una scelta lo dice il file stesso: la stessa operazione è
#    scritta RUMOROSA in deploy.sh:690, setup.sh:187 e engine.py:491.
#    ⇒ qui si cerca la forma, non le coordinate: un ottavo punto diventa rosso da sé.
_ATTESI = 7

# Il frammento arriva da TRE contesti di quoting diversi (apice singolo, stringa
# a doppi apici, heredoc non quotato), quindi nel sorgente può essere scritto
# `\"` e `\$`. Qui si toglie l'escape per eseguirlo: è la stessa riga.
_DISESCAPE = ((r"\"", '"'), (r"\$", "$"))


def _blocchi() -> list[tuple[str, int, str]]:
    """Ogni `chmod 600 .env` dei sorgenti, con la riga che lo segue.

    Restituisce (file, numero_di_riga, frammento_shell). Se una riga di verifica
    non c'è, il frammento è il solo `chmod` — ed è il caso che fallisce il test.
    """
    out: list[tuple[str, int, str]] = []
    for nome in _SORGENTI:
        righe = (_ROOT / nome).read_text().splitlines()
        for i, riga in enumerate(righe):
            if re.search(r"^\s*chmod .*2>/dev/null \|\| true", riga):
                frammento = "\n".join(righe[i:i + 2])
                for a, b in _DISESCAPE:
                    frammento = frammento.replace(a, b)
                out.append((nome, i + 1, frammento))
    return out


def _esegui(frammento: str, tmp: Path, *, chmod_sabotato: bool) -> subprocess.CompletedProcess:
    """Esegue il frammento in una dir con `.env` a 644.

    Con `chmod_sabotato`, un finto `chmod` in testa al PATH esce 0 senza toccare
    niente: è il fallimento silenzioso del mondo reale (ACL, RO, immutabile).
    """
    tmp.mkdir(parents=True, exist_ok=True)
    env_file = tmp / ".env"
    env_file.write_text("TS_AUTHKEY=segreto\n")
    env_file.chmod(0o644)
    # gli oggetti che i frammenti toccano: il file dei valori e le tre dir sensibili
    for d in ("secrets", "backups", "onboarding"):
        (tmp / d).mkdir(exist_ok=True)
        (tmp / d).chmod(0o755)
    ambiente = dict(os.environ)
    if chmod_sabotato:
        finto = tmp / "bin"
        finto.mkdir(exist_ok=True)
        (finto / "chmod").write_text("#!/bin/sh\nexit 0\n")
        (finto / "chmod").chmod(0o755)
        ambiente["PATH"] = f"{finto}:{ambiente['PATH']}"
    return subprocess.run(["bash", "-c", frammento], cwd=tmp, env=ambiente,
                          capture_output=True, text=True)


def test_i_punti_sono_sette_e_non_solo_quelli_della_issue():
    """Sette, non tre: se ne compare uno nuovo va curato, non contato a parte.

    Un numero MAGGIORE non è un errore del test — è un percorso nuovo che scrive
    `.env` e che nessuno ha ancora guardato: qui diventa rosso apposta."""
    punti = _blocchi()
    assert len(punti) == _ATTESI, (
        f"attesi {_ATTESI} `chmod 600 .env` in {', '.join(_SORGENTI)}, trovati "
        f"{len(punti)}: {[f'{f}:{n}' for f, n, _ in punti]}"
    )


@pytest.mark.parametrize("indice", range(_ATTESI))
def test_il_chmod_zitto_non_passa(tmp_path, indice):
    """Il cuore: con un `chmod` che finge di riuscire, il blocco deve FERMARSI.

    Se qualcuno toglie la riga di verifica, qui resta il solo `chmod … || true`,
    che esce 0 — e questo test diventa rosso. È il gate che #66 chiedeva."""
    punti = _blocchi()
    if indice >= len(punti):
        pytest.skip("meno punti del previsto: lo dice il test sul conteggio")
    nome, riga, frammento = punti[indice]
    res = _esegui(frammento, tmp_path / f"ko{indice}", chmod_sabotato=True)
    assert res.returncode != 0, (
        f"{nome}:{riga} — il chmod è fallito in silenzio e il blocco ha "
        f"proseguito (exit 0): .env resta 644 e il deploy dichiara ENV_OK.\n"
        f"frammento:\n{frammento}"
    )
    assert "PERM_FALLITO" in res.stdout, (
        f"{nome}:{riga} — si è fermato, ma senza dire perché: chi legge "
        f"l'output non sa che il permesso è il problema.\nstdout: {res.stdout!r}"
    )


@pytest.mark.parametrize("indice", range(_ATTESI))
def test_controprova_di_polarita(tmp_path, indice):
    """Con il `chmod` VERO il blocco deve passare: un gate che dice sempre «no»
    non protegge niente, si limita a non poter essere smentito."""
    punti = _blocchi()
    if indice >= len(punti):
        pytest.skip("meno punti del previsto: lo dice il test sul conteggio")
    nome, riga, frammento = punti[indice]
    dest = tmp_path / f"ok{indice}"
    dest.mkdir(exist_ok=True)
    res = _esegui(frammento, dest, chmod_sabotato=False)
    assert res.returncode == 0, (
        f"{nome}:{riga} — il blocco fallisce anche quando il chmod riesce "
        f"davvero.\nstdout: {res.stdout!r}\nstderr: {res.stderr!r}"
    )
    atteso = 0o600 if ".env" in frammento.split("\n")[0] else 0o700
    oggetto = dest / (".env" if atteso == 0o600 else "secrets")
    assert oggetto.stat().st_mode & 0o777 == atteso, (
        f"{nome}:{riga} — il chmod è passato ma {oggetto.name} non ha {oct(atteso)}"
    )
