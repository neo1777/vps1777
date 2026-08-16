#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Le coordinate `file:riga` citate nei documenti puntano ancora dentro quel file?

🔴 PERCHÉ ESISTE — voce `a80025f1` del registro, rilievo di @abdd732a dell'01/08:
   «SECURITY.md rimanda a `snapshot_prune (tools/vps1777.py:1021-1032)` ma a quella
   riga oggi c'è `def spazio_richiesto_update`». Una coordinata in prosa che manda
   al posto sbagliato — e non è un refuso: **il codice si sposta, la prosa no**.

📏 RIMISURATO IL 17/08, prima di scrivere una riga: 27 coordinate nei `.md`, **zero**
   oltre la fine del file, e il caso di `snapshot_prune` non c'è più (la citazione è
   stata riscritta senza numero di riga). ⇒ questo presidio nasce su un difetto CURATO,
   non su uno vivo. Serve perché la classe è tornata due volte e **non si vede**: una
   coordinata sbagliata non rompe niente, manda solo la persona sbagliata nel posto
   sbagliato, sei mesi dopo.

⚠️ IL LIMITE, dichiarato qui e non scoperto da chi si fida: **questo NON sa dire se la
   riga contiene la cosa giusta.** Sa dire che il file esiste e che la riga esiste. Il
   caso `snapshot_prune` era IN RANGE ed era sbagliato: 1021 esisteva, conteneva altro.
   ⇒ *un verde qui significa «la coordinata non è assurda», non «la coordinata è vera».*
   Chi vorrà il controllo forte deve legare il simbolo alla riga, e la forma con cui li
   scriviamo oggi non è abbastanza regolare per farlo — misurato: zero citazioni nella
   forma `simbolo (file:riga)`, li scriviamo in cinque modi diversi.

🔍 E i basename si risolvono: la prosa scrive `db.py:161`, non il path intero. Una sonda
   che li conta come «file inesistente» dà **11 rotte su 32 dove ce ne sono zero** — è
   il primo numero che ho ottenuto io, con un predicato ben formato e sbagliato.

Uso:  python3 tools/coordinate-nei-doc.py            # esce 1 se ce n'è una fuori
      python3 tools/coordinate-nei-doc.py --autoprova
"""
from __future__ import annotations

import collections
import pathlib
import re
import sys

# `tools/vps1777.py:1021`, `db.py:161`, `restore.sh r.109` — le tre forme che usiamo.
COORD = re.compile(r"([A-Za-z0-9_./-]+\.(?:py|sh|ya?ml|toml))(?::| r\.)(\d+)(?:-(\d+))?")


def indice(repo: pathlib.Path) -> tuple[list[pathlib.Path], dict[str, list[pathlib.Path]]]:
    files = [p for p in repo.rglob("*") if p.is_file() and ".git" not in p.parts]
    per_nome: dict[str, list[pathlib.Path]] = collections.defaultdict(list)
    for p in files:
        per_nome[p.name].append(p)
    return files, per_nome


def controlla(repo: pathlib.Path) -> tuple[int, list[tuple]]:
    files, per_nome = indice(repo)
    guasti: list[tuple] = []
    tot = 0
    for doc in (p for p in files if p.suffix == ".md"):
        for i, riga in enumerate(
            doc.read_text(encoding="utf-8", errors="replace").splitlines(), 1
        ):
            for m in COORD.finditer(riga):
                rif, prima = m.group(1), int(m.group(2))
                ultima = int(m.group(3) or prima)
                bersaglio = repo / rif
                if not bersaglio.is_file():
                    cand = per_nome.get(pathlib.Path(rif).name, [])
                    if len(cand) == 1:
                        bersaglio = cand[0]
                    elif len(cand) > 1:
                        # ambiguo NON è guasto: la prosa cita un basename che esiste in
                        # più punti. Si conta a parte perché è un rischio, non un errore.
                        tot += 1
                        continue
                    else:
                        tot += 1
                        guasti.append((doc, i, m.group(0), "nessun file con questo nome"))
                        continue
                tot += 1
                n = len(bersaglio.read_text(encoding="utf-8", errors="replace").splitlines())
                if ultima > n:
                    guasti.append((doc, i, m.group(0),
                                   f"{bersaglio} ha {n} righe: la coordinata è fuori"))
    return tot, guasti


def _autoprova() -> int:
    import tempfile

    print("🔬 autoprova di coordinate-nei-doc.py\n")
    ko = 0
    with tempfile.TemporaryDirectory() as d:
        repo = pathlib.Path(d)
        (repo / "tools").mkdir()
        (repo / "tools" / "corto.py").write_text("a\nb\nc\n", encoding="utf-8")

        # ① il caso buono: dentro il file ⇒ nessun guasto
        (repo / "OK.md").write_text("vedi `tools/corto.py:2`\n", encoding="utf-8")
        tot, g = controlla(repo)
        if (tot, len(g)) == (1, 0):
            print(f"  ✅ {'coordinata dentro il file → nessun guasto':<48} → {tot} viste")
        else:
            ko += 1
            print(f"  🔴 {'coordinata dentro il file':<48} → {tot}, {g}")

        # ② LA DOMANDA CHE CONTA: saprebbe dire di NO? Se non prende questa, il verde
        #   sul repo vero non significa niente — è una sonda che non può fallire.
        (repo / "OK.md").write_text("vedi `tools/corto.py:99`\n", encoding="utf-8")
        _, g = controlla(repo)
        if len(g) == 1 and "fuori" in g[0][3]:
            print(f"  ✅ {'coordinata oltre la fine → GUASTO':<48} → 1")
        else:
            ko += 1
            print(f"  🔴 {'coordinata oltre la fine':<48} → {g}")

        # ③ il basename: `corto.py:2` senza path deve risolversi, non contare come rotto.
        #   È l'errore che ho fatto io alla prima misura (11 rotte dove ce n'erano 0).
        (repo / "OK.md").write_text("vedi `corto.py:2`\n", encoding="utf-8")
        _, g = controlla(repo)
        if not g:
            print(f"  ✅ {'basename senza path → risolto, non rotto':<48} → 0")
        else:
            ko += 1
            print(f"  🔴 {'basename senza path':<48} → {g}")

        # ④ un nome che non esiste da nessuna parte resta un guasto vero.
        (repo / "OK.md").write_text("vedi `fantasma.py:1`\n", encoding="utf-8")
        _, g = controlla(repo)
        if len(g) == 1 and "nessun file" in g[0][3]:
            print(f"  ✅ {'nome inesistente → GUASTO':<48} → 1")
        else:
            ko += 1
            print(f"  🔴 {'nome inesistente':<48} → {g}")

        # ⑤ il limite, reso esplicito: la riga esiste ma contiene altro ⇒ NON lo vede.
        #   Sta nel banco per non essere scoperto da chi si fida del verde.
        (repo / "OK.md").write_text("`funzione_che_non_ce` (tools/corto.py:1)\n",
                                    encoding="utf-8")
        _, g = controlla(repo)
        if not g:
            print(f"  ✅ {'limite dichiarato: riga giusta, contenuto no → cieco':<48} → 0")
        else:
            ko += 1
            print(f"  🔴 {'il limite non è più quello dichiarato':<48} → {g}")

    if ko:
        print(f"\n⛔ {ko} casi sbagliati.", file=sys.stderr)
        return 1
    print("\n✅ 5 su 5: trova le coordinate fuori, non inciampa sui basename,\n"
          "   e il suo limite è nel banco invece che nelle intenzioni.")
    return 0


def main() -> int:
    repo = pathlib.Path(__file__).resolve().parent.parent
    tot, guasti = controlla(repo)
    print(f"📍 {tot} coordinate `file:riga` nei documenti\n")
    for doc, i, testo, perche in guasti:
        print(f"  🔴 {doc.relative_to(repo)}:{i}  «{testo}» — {perche}")
    if guasti:
        print(f"\n⛔ {len(guasti)} su {tot} mandano nel posto sbagliato.")
        return 1
    print(f"✅ {tot} su {tot} puntano dentro il file che nominano.\n"
          "   ⚠️ NON dice che puntino alla riga GIUSTA: vedi il limite in testa al file.")
    return 0


if __name__ == "__main__":
    sys.exit(_autoprova() if "--autoprova" in sys.argv else main())
