#!/usr/bin/env python3
"""Che cosa è cambiato DAVVERO quando qualcuno ha rigenerato un `uv.lock`.

Il buco che questo copre — e non è teorico, ci è costato la 0.41.1:

    Dependabot NON porta le major: `.github/dependabot.yml` le ignora esplicitamente
    per `uv` (`version-update:semver-major`). Le major entrano **quando si GENERA il
    lock**, cioè in un gesto manuale — `uv lock` — che nessun presidio guarda.
    `starlette` 0.45 → 1.3.1 è entrata in `b29d4f7`, il commit che INTRODUCEVA i lock.
    `mcp` 2.0.0 è entrata allo stesso modo, e ha impedito l'avvio della 0.41.1.

E il motivo per cui sfugge non è la distrazione: **in un lock di 83 pacchetti il salto di
major è una riga fra centinaia, e ha esattamente lo stesso aspetto di un salto di patch.**
Il diff non distingue `1.28.1 → 1.29.0` da `0.45.0 → 1.3.1`: distinguerlo è il lavoro di
questo script.

## Cosa NON fa (limiti dichiarati, perché il prossimo non li riscopra)

- Non giudica se un salto sia giusto: dice che ATTRAVERSA UN CONFINE e va guardato.
- Non vede i vincoli del `pyproject` (quello è `uv lock --check`, in `ci.yml`), e non
  vede la divergenza FRA servizi gemelli: confronta lo stesso lock con se stesso, prima
  e dopo.
- Non sa se il pacchetto è davvero importato dal codice.

## Il contratto d'uscita è a TRE valori, non a due

    0   nessun salto che attraversi un confine di regime
    1   ci sono salti da dichiarare  (il gate deve fermare)
    2   NON HO POTUTO MISURARE (file assente, TOML illeggibile, versione non semver)

Il 2 esiste perché un presidio che non può guardare deve poterlo DIRE: se «non ho
guardato» esce come 0, il verde è una bugia con la faccia di un dato.
"""
from __future__ import annotations

import sys
import tomllib
from pathlib import Path

USO = """uso:
  lock-salti.py <lock-prima.toml> <lock-dopo.toml>

  In CI, i due file si producono con `git show`:
     git show origin/main:services/x/uv.lock > /tmp/prima
     git show HEAD:services/x/uv.lock        > /tmp/dopo
"""


def _versione(testo: str) -> tuple[int, ...] | None:
    """«1.29.0» → (1, 29, 0). None se non è una semver di soli numeri.

    Le versioni con suffisso (`1.0.dev1`, `2.0.0rc1`) tornano None **apposta**: non so
    ordinarle in modo affidabile, e un ordinamento sbagliato qui produrrebbe un verdetto
    sbagliato con la faccia della certezza. Chi le incontra riceve un esito 2.
    """
    pezzi = testo.split(".")
    if not 1 <= len(pezzi) <= 4:
        return None
    try:
        return tuple(int(p) for p in pezzi)
    except ValueError:
        return None


def _pacchetti(percorso: Path) -> dict[str, str]:
    """{nome: versione} da un uv.lock. Solleva se il file non è leggibile."""
    dati = tomllib.loads(percorso.read_text(encoding="utf-8"))
    fuori = {}
    for p in dati.get("package", []):
        nome, ver = p.get("name"), p.get("version")
        if nome and ver:
            fuori[nome] = ver
    return fuori


def classifica(prima: str, dopo: str) -> tuple[str, str]:
    """(gravità, spiegazione). Gravità: 'confine' | 'minore' | 'ignoto'.

    🔑 LA REGOLA CHE NON È OVVIA — **sotto la 1.0 il confine è la MINOR.**
    SemVer dice che una `0.x` non ha major: per convenzione ogni minor può rompere.
    Quindi `0.45 → 0.46` è un attraversamento quanto `1.x → 2.x`, e `starlette` 0.45 →
    1.3.1 li attraversa entrambi. Trattare le 0.x «con indulgenza perché sono 0.x»
    è il ragionamento che ci ha lasciato `uvicorn` a venti minor oltre il vincolo.
    """
    a, b = _versione(prima), _versione(dopo)
    if a is None or b is None:
        return "ignoto", f"versione non ordinabile ({prima} → {dopo})"
    if a[0] != b[0]:
        return "confine", f"MAJOR {a[0]} → {b[0]}"
    if a[0] == 0 and len(a) > 1 and len(b) > 1 and a[1] != b[1]:
        return "confine", f"MINOR sotto la 1.0 ({prima} → {dopo}) — in 0.x la minor È il confine"
    return "minore", f"{prima} → {dopo}"


def confronta(f_prima: Path, f_dopo: Path) -> int:
    try:
        prima, dopo = _pacchetti(f_prima), _pacchetti(f_dopo)
    except FileNotFoundError as e:
        print(f"⚠️  NON MISURATO: manca {e.filename}", file=sys.stderr)
        return 2
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
        print(f"⚠️  NON MISURATO: lock illeggibile ({e})", file=sys.stderr)
        return 2

    confini, minori, ignoti = [], [], []
    for nome in sorted(set(prima) & set(dopo)):
        if prima[nome] == dopo[nome]:
            continue
        grav, testo = classifica(prima[nome], dopo[nome])
        (confini if grav == "confine" else ignoti if grav == "ignoto" else minori).append(
            (nome, testo)
        )
    nuovi = sorted(set(dopo) - set(prima))
    spariti = sorted(set(prima) - set(dopo))

    print(f"lock: {len(prima)} → {len(dopo)} pacchetti")
    for etichetta, voci in (("⛔ ATTRAVERSA UN CONFINE", confini), ("· patch/minor", minori)):
        if voci:
            print(f"\n{etichetta}")
            for nome, testo in voci:
                print(f"    {nome:28} {testo}")
    if nuovi or spariti:
        print(f"\n· entrati: {', '.join(nuovi) or '—'}")
        print(f"· usciti:  {', '.join(spariti) or '—'}")

    if ignoti:
        print("\n⚠️  NON MISURATO — versioni che non so ordinare:", file=sys.stderr)
        for nome, testo in ignoti:
            print(f"    {nome:28} {testo}", file=sys.stderr)
        print("    Estendi `_versione()`: finché non lo fai, questi NON sono verificati.",
              file=sys.stderr)
        return 2

    if confini:
        print(
            f"\n⛔ {len(confini)} attraversamento/i di confine in questa rigenerazione.\n"
            "   Non è un errore: è la cosa che va DETTA. Nomina ciascun pacchetto nel\n"
            "   messaggio del commit, così il salto avviene dentro un diff che dichiara\n"
            "   di essere quel salto — e non dentro uno che parlava d'altro."
        )
        # Righe per il gate, una per pacchetto. Portano la VERSIONE DI DESTINAZIONE e non
        # solo il nome, e il motivo è un falso positivo che mi sono fatta da sola in
        # review: cercare «mcp» nel testo di una PR matcha dentro «nb1777-mcp», cioè
        # dentro il nome del SERVIZIO — e il servizio lo si nomina sempre. Il gate
        # sarebbe stato compiacente proprio nel caso più frequente.
        # Una versione (`1.29.0`) nel testo non ci finisce per caso: chi la scrive l'ha
        # guardata. `\b` non basterebbe: in `nb1777-mcp` il trattino È un confine di parola.
        print("\n# righe per il gate (nome + versione di destinazione):")
        for nome, _ in confini:
            print(f"RATIFICA-RICHIESTA: {nome}=={dopo[nome]}")
        return 1
    print("\n✓ nessun attraversamento di confine")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(USO, file=sys.stderr)
        return 2
    return confronta(Path(argv[1]), Path(argv[2]))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
