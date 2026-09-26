#!/usr/bin/env python3
"""Aggiorna l'indice della ricerca per senso di un DB dell'archivio, dal PC, in un gesto.

PERCHÉ ESISTE (26/09/2026, gradino 2 di «l'indice semantico dentro il prodotto»)
────────────────────────────────────────────────────────────────────────────────
L'indice (`<nome-db>.vec.db`) si costruisce sul PC, perché costa ore di CPU, e si
carica sulla VPS. Fino alla 0.55.0 i passi erano sei, a mano, scritti in
docs/RICERCA-IBRIDA.md: copia del DB, costruzione, controllo, confronto col DB
sulla VPS, caricamento, prova. L'installazione dell'autore li faceva con uno
script fuori dal repo. Questo strumento li mette in fila, con le stesse guardie:

1. **Copia del DB** dalla VPS: in streaming (`docker cp … -` via ssh), senza file
   temporanei sulla VPS, e con `PRAGMA quick_check` sulla copia. Una copia presa
   mentre un ingest scrive può essere incoerente: il controllo lo dice.
2. **L'indice di partenza**: quello del lavoro precedente, o quello sulla VPS, così
   la costruzione è incrementale. Se non c'è nessun indice serve un perimetro
   (`--tutto`, `--dal/--al`, `--project`).
3. **La costruzione** col costruttore del repo (`costruisci_indice.py`, nell'ambiente
   del lock di archive-mcp) e il modello di `vps1777 indice-modello --dest`.
4. **Il controllo** (`--controlla`): l'indice deve essere in pari con la copia.
5. **Il DB sulla VPS è ancora quello della copia?** Se è stato re-ingerito nel
   frattempo, l'indice è già vecchio: non si carica, e lo si dice.
6. **Il caricamento**: su `<nome>.vec.db.caricamento` nel volume, poi `mv` (una
   rinomina nella stessa directory è atomica): archive-mcp non legge mai un file a
   metà, e lo scan non scambia il file in arrivo per un indice.

Solo stdlib: gira col Python del PC. Il costruttore lo lancia con `uv run` in
services/archive-mcp, come dice la sua docstring.

    python3 tools/indice_semantico.py aggiorna --host <ssh-della-vps> --db <nome-db> \\
        --modello ~/e5-small [--tutto]

ESITO 0 = indice caricato · 1 = un passo è fallito (il messaggio dice quale e perché)
      2 = rifiutato: il DB sulla VPS è cambiato dopo la copia, o manca il perimetro
"""
from __future__ import annotations

import argparse
import hashlib
import shlex
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Callable

RADICE = Path(__file__).resolve().parents[1]
ARCHIVE_MCP = RADICE / "services" / "archive-mcp"
DIR_DB = "/var/lib/archive/db"

# Il modo di lanciare un comando: sostituibile nei test.
Esegui = Callable[..., subprocess.CompletedProcess]


class Rifiuto(Exception):
    """Un passo che non si fa, con la ragione e la cura (esito 2)."""


class Fallito(Exception):
    """Un passo che non è riuscito (esito 1)."""


def _esegui(cmd, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, **kw)


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while blocco := f.read(1 << 20):
            h.update(blocco)
    return h.hexdigest()


def _ssh(host: str, comando: str) -> list[str]:
    return ["ssh", host, comando]


def _pipe(comando: str) -> list[str]:
    """Una pipe di shell con `pipefail`: se uno dei due lati fallisce, fallisce tutto.
    I file passano in streaming, senza tenerli in memoria (un DB arriva a 2,4 GB)."""
    return ["bash", "-o", "pipefail", "-c", comando]


def scarica(host: str, container: str, remoto: str, dest_dir: Path, esegui: Esegui) -> Path:
    """`docker cp <container>:<remoto> -` produce un tar su stdout: lo si estrae nella
    cartella di lavoro. Niente file temporanei sulla VPS."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    remoto_cmd = f"docker cp {shlex.quote(f'{container}:{remoto}')} -"
    r = esegui(_pipe(f"ssh {shlex.quote(host)} {shlex.quote(remoto_cmd)} | "
                     f"tar -x -C {shlex.quote(str(dest_dir))}"), capture_output=True, text=True)
    if r.returncode != 0:
        raise Fallito(f"copia di {remoto} dalla VPS fallita: {(r.stderr or '').strip()[:300]}")
    return dest_dir / Path(remoto).name


def esiste_remoto(host: str, container: str, remoto: str, esegui: Esegui) -> bool:
    r = esegui(_ssh(host, f"docker exec {shlex.quote(container)} test -f {shlex.quote(remoto)}"),
               capture_output=True)
    return r.returncode == 0


def sha_remoto(host: str, container: str, remoto: str, esegui: Esegui) -> str:
    r = esegui(_ssh(host, f"docker exec {shlex.quote(container)} sha256sum {shlex.quote(remoto)}"),
               capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.split():
        raise Fallito(f"non ho potuto leggere lo sha di {remoto} sulla VPS: {(r.stderr or '').strip()[:200]}")
    return r.stdout.split()[0]


def controlla_copia(db: Path) -> None:
    if not db.is_file():
        raise Fallito(f"la copia di {db.name} non c'è in {db.parent}: la copia dalla VPS non "
                      "l'ha prodotta (il nome del DB è giusto?).")
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            esito = conn.execute("PRAGMA quick_check").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        esito = str(exc)
    if esito != "ok":
        raise Fallito(f"la copia di {db.name} non è coerente ({esito}): probabilmente un ingest "
                      "stava scrivendo mentre la copiavo. Rilancia quando l'ingest è finito.")


def costruttore(argomenti: list[str], esegui: Esegui) -> int:
    cmd = ["uv", "run", "python", "tools/costruisci_indice.py", *argomenti]
    return esegui(cmd, cwd=str(ARCHIVE_MCP)).returncode


def carica(host: str, container: str, vec: Path, esegui: Esegui) -> None:
    """Il tar dell'indice va nel volume come `<nome>.vec.db.caricamento`, poi `mv`."""
    arrivo = f"{vec.name}.caricamento"
    remoto_cmd = f"docker cp - {shlex.quote(container)}:{DIR_DB}/"
    # `--transform` (GNU tar) cambia il nome DENTRO il tar: il file arriva già col nome
    # d'attesa, senza una copia rinominata sul disco del PC.
    r = esegui(_pipe(f"tar -c -C {shlex.quote(str(vec.parent))} "
                     f"--transform {shlex.quote(f's|^{vec.name}$|{arrivo}|')} {shlex.quote(vec.name)} | "
                     f"ssh {shlex.quote(host)} {shlex.quote(remoto_cmd)}"),
               capture_output=True, text=True)
    if r.returncode != 0:
        raise Fallito(f"caricamento di {vec.name} fallito: {(r.stderr or '').strip()[:300]}")
    mv = esegui(_ssh(host, f"docker exec {shlex.quote(container)} mv "
                           f"{DIR_DB}/{arrivo} {DIR_DB}/{vec.name}"), capture_output=True)
    if mv.returncode != 0:
        raise Fallito(f"il file è arrivato come {arrivo} ma la rinomina è fallita: "
                      "archive-mcp continua a leggere l'indice di prima.")


def _stampa(*parti: object) -> None:
    # flush: i passi devono comparire PRIMA dell'output del costruttore che segue
    print(*parti, flush=True)


def aggiorna(a: argparse.Namespace, esegui: Esegui = _esegui, stampa=_stampa) -> int:
    lavoro = Path(a.lavoro).expanduser()
    db_remoto = f"{DIR_DB}/{a.db}.db"
    vec_remoto = f"{DIR_DB}/{a.db}.vec.db"
    db = lavoro / f"{a.db}.db"
    vec = lavoro / f"{a.db}.vec.db"
    parziale = lavoro / f"{a.db}.vec.db.parziale"

    if a.senza_copia and db.exists():
        stampa(f"1. copia del DB: uso quella che c'è ({db}), come chiesto")
    else:
        stampa(f"1. copia del DB {a.db} dalla VPS…")
        scarica(a.host, a.container, db_remoto, lavoro, esegui)
    controlla_copia(db)
    sha_copia = _sha256(db)

    perimetro = [*(["--tutto"] if a.tutto else []),
                 *([f"--dal={a.dal}"] if a.dal else []), *([f"--al={a.al}"] if a.al else []),
                 *[f"--project={p}" for p in a.project],
                 *([f"--senza-ts={a.senza_ts}"] if a.senza_ts else [])]
    if not vec.exists() and not parziale.exists():
        if esiste_remoto(a.host, a.container, vec_remoto, esegui):
            stampa("2. indice di partenza: quello sulla VPS (la costruzione sarà incrementale)")
            scarica(a.host, a.container, vec_remoto, lavoro, esegui)
        elif not perimetro:
            raise Rifiuto(f"{a.db} non ha ancora un indice, né qui né sulla VPS: dichiara cosa "
                          "indicizzare (--tutto, oppure --dal/--al, --project). Costa ~7 ore ogni "
                          "100.000 vettori su un PC a 4 core.")
    else:
        stampa(f"2. indice di partenza: quello del lavoro precedente ({vec.name}"
               f"{' + costruzione interrotta da riprendere' if parziale.exists() else ''})")

    stampa("3. costruzione…")
    arg = ["--db", str(db), "--modello", str(Path(a.modello).expanduser()), *perimetro]
    if a.thread:
        arg.append(f"--thread={a.thread}")
    if costruttore(arg, esegui) != 0:
        raise Fallito("il costruttore non ha finito: il suo messaggio qui sopra dice perché. "
                      "Il lavoro fatto resta nel .parziale: rilancia con --senza-copia per riprendere.")

    stampa("4. controllo…")
    if costruttore(["--db", str(db), "--controlla"], esegui) != 0:
        raise Fallito("l'indice NON è in pari con la copia del DB: i numeri qui sopra dicono dove.")

    stampa("5. il DB sulla VPS è ancora quello della copia?")
    if sha_remoto(a.host, a.container, db_remoto, esegui) != sha_copia:
        raise Rifiuto(f"il DB {a.db} sulla VPS è cambiato dopo la copia (un ingest, una "
                      "migrazione): l'indice appena costruito è già vecchio e non lo carico. "
                      "Rilancia `aggiorna`: la costruzione riparte in modo incrementale.")

    if a.non_caricare:
        stampa(f"6. caricamento saltato (--non-caricare): l'indice è in {vec}")
        return 0
    stampa("6. caricamento nel volume…")
    carica(a.host, a.container, vec, esegui)
    stampa(f"fatto: {a.db}.vec.db caricato. Prova: una search_ibrida su {a.db} deve rispondere "
           "con indici[].verifica.registro = true e scartati = 0.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="indice_semantico",
                                description="L'indice della ricerca per senso, dal PC alla VPS.")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("aggiorna", help="copia, costruzione, controllo, caricamento")
    a.add_argument("--host", required=True, help="la VPS come la chiami con ssh")
    a.add_argument("--db", required=True, help="il DB dell'archivio, senza .db")
    a.add_argument("--modello", default="~/e5-small",
                   help="cartella del modello (`vps1777 indice-modello --dest`), default ~/e5-small")
    a.add_argument("--lavoro", default="~/archivio-indice",
                   help="cartella di lavoro sul PC: la copia del DB e l'indice (default ~/archivio-indice)")
    a.add_argument("--container", default="vps1777-gateway-1",
                   help="il container che scrive il volume dell'archivio (default vps1777-gateway-1)")
    g = a.add_argument_group("perimetro (serve solo se il DB non ha ancora un indice)")
    g.add_argument("--tutto", action="store_true")
    g.add_argument("--dal", default="")
    g.add_argument("--al", default="")
    g.add_argument("--project", action="append", default=[])
    g.add_argument("--senza-ts", choices=("includi", "escludi"), default="")
    a.add_argument("--thread", type=int, default=0, help="thread del costruttore (default: tutti)")
    a.add_argument("--senza-copia", action="store_true",
                   help="usa la copia del DB già nella cartella di lavoro (per riprendere una costruzione)")
    a.add_argument("--non-caricare", action="store_true", help="si ferma prima del caricamento")
    return p


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    try:
        return aggiorna(a)
    except Rifiuto as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2
    except Fallito as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
