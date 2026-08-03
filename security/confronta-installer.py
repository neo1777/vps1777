#!/usr/bin/env python3
"""I TRE INSTALLER DEVONO CONCORDARE — e se divergono, lo dice la CI, non un umano.

🔓 PERCHÉ ESISTE. Round-16, rilievo `bedecdcb` (audio B, lente «cosa NON è
   coperto da niente»): ci sono tre strade d'installazione — `setup.sh`,
   `deploy.sh`, `installer/engine.py` — e **nessun job della CI le confronta**.
   `ci.yml` nomina i primi due solo come perimetro di shellcheck; i `git diff`
   che ci sono riguardano le migrazioni.

   ⚠️ Non è teoria: è già successo. Il fix #13 (`6c764bc`) allineò `deploy.sh` e
   `engine.py` **e saltò `setup.sh`** — `vps1777-secrets-check.timer` restò
   scoperto su un percorso su tre. E `H55`: `setup.sh` derivava l'operatore da
   `id -un` mentre `engine.py` lo aveva costante.

🔴 E DICHIARO SUBITO LA COSA CHE CONTA: **oggi i tre CONCORDANO su tutto ciò che
   questo file sa misurare** (misurato il 03/08). Quindi questo non cura una
   divergenza: previene la PROSSIMA. *Un presidio scritto quando il difetto non
   c'è è l'unico che si può provare senza rompere niente — e infatti
   `--autoprova` ne inietta uno finto e verifica che scatti.*

⚠️ COSA NON VEDE, dichiarato perché nessuno lo scopra come se fosse un bug:
   è un'analisi STATICA di shell e Python. Vede i nomi che compaiono nei file.
   **Non vede** un'unit abilitata dietro una variabile calcolata a runtime, né
   un pacchetto installato da uno script chiamato da un altro script. ⇒ un
   verde qui è «i nomi concordano», NON «i tre installer fanno la stessa cosa».
   *La differenza è quella fra un presidio e una promessa.*

USO
    python3 security/confronta-installer.py            → confronta, esito 0/1/2
    python3 security/confronta-installer.py --autoprova → prova che sa scattare

ESITO  0 = concordano · 1 = DIVERGONO (e dice su cosa) · 2 = non misurabile
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
INSTALLER = ["setup.sh", "deploy.sh", "installer/engine.py"]

# Gli ASSI del confronto. Ognuno è (nome, regex): ciò che l'asse trova in un
# file è un INSIEME di stringhe, e i tre insiemi devono essere uguali.
ASSI: list[tuple[str, str]] = [
    ("unit systemd abilitate", r"vps1777-[a-z-]+\.(?:timer|service|path)"),
    ("hardening host", r"\b(?:fail2ban|unattended-upgrades)\b"),
]


def estrai(testo: str, pattern: str) -> set[str]:
    return {m.group(0) for m in re.finditer(pattern, testo)}


def confronta(radice: Path = RADICE) -> tuple[int, list[str]]:
    """Ritorna (esito, righe da stampare)."""
    righe: list[str] = []
    contenuti: dict[str, str] = {}
    for nome in INSTALLER:
        p = radice / nome
        if not p.is_file():
            return 2, [f"⚪ NON MISURATO — manca `{nome}`: non posso dire che concordino."]
        contenuti[nome] = p.read_text(encoding="utf-8", errors="replace")

    divergenze = 0
    for asse, pattern in ASSI:
        trovati = {n: estrai(t, pattern) for n, t in contenuti.items()}
        unione: set[str] = set().union(*trovati.values())
        if not unione:
            righe.append(f"  ⚪ {asse}: ZERO occorrenze in tutti e tre — "
                         "il pattern non ha trovato niente, quindi questo asse "
                         "NON è stato misurato (non è un verde).")
            divergenze += 0
            continue
        if len({frozenset(v) for v in trovati.values()}) == 1:
            righe.append(f"  ✅ {asse}: concordano ({len(unione)} voci)")
            continue
        divergenze += 1
        righe.append(f"  🔴 {asse}: DIVERGONO")
        for voce in sorted(unione):
            chi_ce_l_ha = [n for n, v in trovati.items() if voce in v]
            if len(chi_ce_l_ha) != len(INSTALLER):
                mancano = [n for n in INSTALLER if n not in chi_ce_l_ha]
                righe.append(f"       «{voce}» manca in: {', '.join(mancano)}")
    return (1 if divergenze else 0), righe


def autoprova() -> int:
    """Il presidio sa scattare? Inietto una divergenza finta e verifico.

    Senza questo, un verde direbbe «concordano» anche se il confronto fosse
    rotto — e oggi i tre concordano davvero, quindi il verde da solo non
    distingue un presidio che funziona da uno che non guarda.
    """
    import tempfile, shutil
    ok = True
    with tempfile.TemporaryDirectory() as d:
        finta = Path(d)
        (finta / "installer").mkdir()
        for nome in INSTALLER:
            shutil.copy(RADICE / nome, finta / nome)
        # ① copia fedele → deve dire «concordano»
        esito, _ = confronta(finta)
        print(f"  {'✅' if esito == 0 else '🔴'} copia fedele → esito {esito} (atteso 0)")
        ok = ok and esito == 0
        # ② tolgo una unit da UN solo installer → deve scattare
        p = finta / "setup.sh"
        p.write_text(p.read_text(encoding="utf-8")
                     .replace("vps1777-secrets-check.timer", "# rimossa-per-prova"),
                     encoding="utf-8")
        esito, righe = confronta(finta)
        scatta = esito == 1 and any("secrets-check" in r for r in righe)
        print(f"  {'✅' if scatta else '🔴'} unit tolta da UN installer → esito {esito} "
              f"e la NOMINA (atteso 1)")
        ok = ok and scatta
        # ③ un file mancante NON è un verde
        (finta / "deploy.sh").unlink()
        esito, _ = confronta(finta)
        print(f"  {'✅' if esito == 2 else '🔴'} installer mancante → esito {esito} "
              f"(atteso 2: «non misurato», non 0)")
        ok = ok and esito == 2
    print(f"\n  ⇒ autoprova {'PASSATA' if ok else 'FALLITA'} (3 casi)")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--autoprova" in sys.argv:
        sys.exit(autoprova())
    esito, righe = confronta()
    print(f"confronto dei {len(INSTALLER)} installer · {', '.join(INSTALLER)}\n")
    for r in righe:
        print(r)
    print()
    if esito == 0:
        print("✅ i tre installer CONCORDANO sugli assi misurati.\n"
              "   («sugli assi misurati» non è una formula: leggi il docstring — "
              "questo è statico e non vede tutto)")
    elif esito == 1:
        print("🔴 DIVERGONO. Una cura applicata a un installer solo lascia\n"
              "   scoperti gli altri due, ed è già successo (fix #13, H55).")
    sys.exit(esito)
