"""Ogni secret che il compose dichiara deve essere PROVVISTO da TUTTE le vie di install.

Perché esiste — misurato il 23/08/2026 sul primo install post-format, da utente
qualsiasi: `archive_desc_secret` (nato in 581793f, 20/07) era generato SOLO da
setup.sh; `deploy.sh` e `installer/engine.py` no. Il compose lo dichiara con
`file:`, quindi su una macchina VERGINE installata dal PC il compose moriva con
«bind source path does not exist» e lo stack non partiva. Nessuna installazione
ESISTENTE poteva accorgersene: il file c'era già ovunque tranne che sul futuro.

È la terza volta di questa classe nel repo (H45 fail2ban «in TUTTI e tre gli
installer»; ENABLE_UNITS): la cura entra in UNA via e le altre restano cieche.
Questo test è il controllo sull'ELENCO DEGLI ELENCHI: pesca i secret dal
compose (la fonte che le vie devono servire), non da una lista scritta qui —
così il prossimo secret nato con la forma giusta cade qui invece di nascere cieco.

Stdlib-only per la suite «uvx pytest tools/tests/»: niente yaml — il blocco
`secrets:` di compose.yaml si legge con una regex ancorata, e la sua forma è
già presidiata dal parse del compose in CI (i job build lo caricano davvero).
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

VIE = {
    "setup.sh": REPO / "setup.sh",
    "deploy.sh": REPO / "deploy.sh",
    "installer/engine.py": REPO / "installer" / "engine.py",
}


def secrets_dichiarati(compose_text: str) -> set[str]:
    """I nomi file dei secret `file: ./secrets/<nome>.txt` dichiarati dal compose."""
    return set(re.findall(r"file:\s*\./secrets/([A-Za-z0-9_]+\.txt)", compose_text))


def vie_che_non_provvedono(nome_file: str, vie: dict[str, str]) -> list[str]:
    """Le vie il cui CODICE (righe non-commento) non nomina secrets/<nome_file>.

    Righe commentate escluse: un commento che RACCONTA il secret non lo genera —
    è la lezione del test-perimetro di check_findings (un `contains` soddisfatto
    da una riga commentata è un gate verde su codice assente).
    """
    fuori = []
    for via, testo in vie.items():
        vivo = "\n".join(
            r for r in testo.splitlines() if not r.lstrip().startswith("#")
        )
        if f"secrets/{nome_file}" not in vivo:
            fuori.append(via)
    return fuori


def test_ogni_secret_del_compose_e_provvisto_da_tutte_le_vie():
    compose = (REPO / "compose.yaml").read_text(encoding="utf-8")
    dichiarati = secrets_dichiarati(compose)
    assert dichiarati, "zero secret nel compose: o è cambiata la forma, o il test è cieco"
    vie = {n: p.read_text(encoding="utf-8") for n, p in VIE.items()}
    buchi = {s: fuori for s in sorted(dichiarati)
             if (fuori := vie_che_non_provvedono(s, vie))}
    assert not buchi, (
        f"secret dichiarati dal compose ma NON provvisti da tutte le vie: {buchi} — "
        f"su una macchina vergine quella via muore con «bind source path does not exist»"
    )


def test_controprova_il_verso_rosso_esiste():
    """Un secret assente da una via FINTA deve essere trovato: il test sa diventare rosso."""
    vie_finte = {
        "via-sana": "gen 24 > secrets/finto_secret.txt\n",
        "via-cieca": "# secrets/finto_secret.txt solo raccontato, mai generato\n",
    }
    assert vie_che_non_provvedono("finto_secret.txt", vie_finte) == ["via-cieca"]


def test_il_caso_vivo_del_23_08_resta_coperto():
    """archive_desc_secret è nel compose e in tutte e tre le vie — il caso che ha
    fermato il primo install post-format non deve poter tornare in silenzio."""
    compose = (REPO / "compose.yaml").read_text(encoding="utf-8")
    assert "archive_desc_secret.txt" in secrets_dichiarati(compose)
    vie = {n: p.read_text(encoding="utf-8") for n, p in VIE.items()}
    assert vie_che_non_provvedono("archive_desc_secret.txt", vie) == []
