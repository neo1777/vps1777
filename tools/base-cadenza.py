#!/usr/bin/env python3
"""Le immagini base fissate per digest sono rimaste indietro? (23/11/2026)

Le basi dei Dockerfile sono fissate col digest (#338): un tag ripuntato a monte non entra. Il prezzo
è che la base invecchia se nessuno sposta il digest. Dovrebbe farlo Dependabot ogni settimana, ma dal
27/09 al 21/11/2026 non ha mai proposto quello di `python:3.12-slim` (solo Caddy), e nessuno lo
vedeva: l'ha mostrato una scansione, due mesi dopo. Questo script lo misura: per ogni `FROM
nome:tag@sha256:…` chiede al registro il digest corrente di quel tag; se è diverso E il digest
fissato è nel repo da più di SOGLIA_GIORNI, la base è indietro. Lo lancia rebuild-mensile.yml, che
apre una issue. Non aggiorna niente da sé.

La soglia c'è perché la base a monte viene ricostruita spesso: «diverso da oggi» è normale per
qualche giorno, non per un mese e mezzo (sei giri mancati di Dependabot).

Uscita: 0 = in pari, o diverso da poco · 1 = almeno una base indietro oltre la soglia ·
2 = non misurabile (registro irraggiungibile, nessuna base trovata, data del pin ignota).
Stdlib: gira su un runner nudo. Solo immagini ufficiali di Docker Hub (`library/…`): sono le nostre.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

SOGLIA_GIORNI = 45
_RADICE = Path(__file__).resolve().parents[1]
_FROM = re.compile(r"^FROM\s+([a-z0-9._/-]+):([A-Za-z0-9._-]+)@(sha256:[0-9a-f]{64})", re.M)
_ACCETTA = ", ".join(["application/vnd.oci.image.index.v1+json",
                      "application/vnd.docker.distribution.manifest.list.v2+json",
                      "application/vnd.oci.image.manifest.v1+json",
                      "application/vnd.docker.distribution.manifest.v2+json"])


def basi(radice: Path) -> dict[tuple[str, str, str], list[str]]:
    """{(nome, tag, digest): [Dockerfile che lo usano]}."""
    trovate: dict[tuple[str, str, str], list[str]] = {}
    for f in sorted(radice.glob("services/*/Dockerfile")):
        for chiave in _FROM.findall(f.read_text(encoding="utf-8")):
            dove = trovate.setdefault(chiave, [])
            if str(f.relative_to(radice)) not in dove:
                dove.append(str(f.relative_to(radice)))
    return trovate


def digest_corrente(nome: str, tag: str) -> str:
    """Il digest che il registro dà OGGI a quel tag (Docker Hub, immagini ufficiali)."""
    if "/" in nome:
        raise ValueError(f"{nome}: non è un'immagine ufficiale di Docker Hub, non so chiederla")
    repo = f"library/{nome}"
    with urllib.request.urlopen(
            f"https://auth.docker.io/token?service=registry.docker.io&scope=repository:{repo}:pull", timeout=30) as r:
        gettone = json.loads(r.read(1024 * 1024))["token"]
    rich = urllib.request.Request(f"https://registry-1.docker.io/v2/{repo}/manifests/{tag}", method="HEAD",
                                  headers={"Authorization": f"Bearer {gettone}", "Accept": _ACCETTA})
    with urllib.request.urlopen(rich, timeout=30) as r:
        d = r.headers.get("Docker-Content-Digest", "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", d):
        raise ValueError(f"{nome}:{tag}: il registro non ha dato un digest leggibile")
    return d


def fissato_il(radice: Path, digest: str, file: str) -> dt.date:
    """La data del commit più vecchio che ha quel digest in quel file (serve la storia intera)."""
    esito = subprocess.run(["git", "-C", str(radice), "log", "--format=%cs", "-S", digest, "--", file],
                           capture_output=True, text=True, timeout=60, check=False)
    date = esito.stdout.split()
    if esito.returncode != 0 or not date:
        raise ValueError(f"{file}: non trovo nella storia di git quando è entrato {digest[:19]}…")
    return dt.date.fromisoformat(date[-1])


def verdetto(trovate, corrente, entrato, *, oggi: dt.date) -> tuple[int, list[str]]:
    """`corrente(nome, tag)` e `entrato(digest, file)` sono passati da fuori: i test li fingono."""
    if not trovate:
        raise ValueError("nessuna riga `FROM nome:tag@sha256:…` nei Dockerfile: non ho misurato niente")
    righe, indietro = [], False
    for (nome, tag, digest), dove in sorted(trovate.items()):
        ora = corrente(nome, tag)
        if ora == digest:
            righe.append(f"{nome}:{tag} in pari ({len(dove)} Dockerfile).")
            continue
        giorni = (oggi - entrato(digest, dove[0])).days
        oltre = giorni > SOGLIA_GIORNI
        indietro = indietro or oltre
        righe.append(f"{nome}:{tag} fissata a {digest[:19]}… da {giorni} giorni; il registro oggi dà {ora[:19]}… "
                     + (f"INDIETRO oltre la soglia di {SOGLIA_GIORNI} giorni" if oltre
                        else f"sotto la soglia di {SOGLIA_GIORNI} giorni") + f" ({', '.join(dove)}).")
    return (1 if indietro else 0), righe


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--radice", default=str(_RADICE))
    ap.add_argument("--oggi", default="", help="AAAA-MM-GG (default: oggi in UTC)")
    a = ap.parse_args(argv)
    radice = Path(a.radice)
    try:
        oggi = dt.date.fromisoformat(a.oggi) if a.oggi else dt.datetime.now(dt.timezone.utc).date()
        rc, righe = verdetto(basi(radice), digest_corrente, lambda d, f: fissato_il(radice, d, f), oggi=oggi)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f"base-cadenza: non misurabile ({exc})")
        return 2
    print("\n".join(righe))
    return rc


if __name__ == "__main__":
    sys.exit(main())
