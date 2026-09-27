"""Due controlli dello Scorecard OpenSSF, tenuti fermi da un test (27/09/2026).

Segnalati da Sagoma (sessione template), che ha lanciato lo Scorecard in sola lettura:
- **Token-Permissions**: le scritture si dichiarano nel JOB che le usa, mai a livello di
  workflow. A livello di workflow valgono per ogni job, anche per uno aggiunto dopo che
  non ne ha bisogno. `rebuild-mensile.yml` (contents/issues) e `trivy.yml`
  (security-events) le avevano in cima.
- **Pinned-Dependencies**: le immagini base dei servizi si fissano col digest. Un tag
  (`python:3.12-slim`) cambia contenuto sotto i piedi; il digest no, e lo aggiorna
  Dependabot (ecosistema `docker`, una cartella per servizio) con una PR che si guarda.

I plugin di esempio (`plugins/`) restano fuori di proposito: sono punti di partenza per
chi scrive un plugin, fuori da Dependabot, e un digest lì invecchierebbe senza nessuno
che lo aggiorni.
"""
from __future__ import annotations

import re
from pathlib import Path

RADICE = Path(__file__).resolve().parents[2]


def _permessi_di_primo_livello(testo: str) -> list[str]:
    righe, dentro = [], False
    for r in testo.splitlines():
        if re.match(r"^permissions:", r):
            dentro = True
            righe.append(r)
            continue
        if dentro:
            if r and not r[0].isspace():
                break
            righe.append(r)
    return righe


def test_nessuna_scrittura_a_livello_di_workflow():
    colpevoli = {}
    for wf in sorted((RADICE / ".github" / "workflows").glob("*.yml")):
        scritture = [r.strip() for r in _permessi_di_primo_livello(wf.read_text())
                     if re.search(r":\s*write\b", r.split("#")[0])]
        if scritture:
            colpevoli[wf.name] = scritture
    assert not colpevoli, f"scritture a livello di workflow (vanno nel job): {colpevoli}"


def test_le_immagini_dei_servizi_sono_fissate_col_digest():
    sciolte = []
    for df in sorted((RADICE / "services").glob("*/Dockerfile")):
        for n, r in enumerate(df.read_text().splitlines(), 1):
            m = re.match(r"^\s*FROM\s+(\S+)", r) or re.search(r"COPY\s+--from=(\S+)", r)
            if not m:
                continue
            immagine = m.group(1)
            if ":" not in immagine and "/" not in immagine:
                continue          # un nome di stage (`--from=builder`), non un'immagine
            if "@sha256:" not in immagine:
                sciolte.append(f"{df.relative_to(RADICE)}:{n} {immagine}")
    assert not sciolte, f"immagini senza digest: {sciolte}"
