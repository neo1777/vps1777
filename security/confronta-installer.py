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


def solo_codice(testo: str, nome: str) -> str:
    """Toglie i COMMENTI. Senza questo il presidio è cieco dove dovrebbe vedere.

    🔴 PROVATO, non temuto (`abdd732a`, 03/08): togliendo
       `vps1777-secrets-check.timer` dal CODICE di `setup.sh` e lasciandolo in un
       commento — che è **esattamente come si scrive una divergenza vera**, con
       accanto la nota che la spiega — il confronto usciva **0, «concordano»**.
       Una divergenza reale, e il presidio dava verde.

    ⭐ E LA MIA AUTOPROVA NON L'AVEVA PRESA: il caso ② sostituiva la stringa con
       `# rimossa-per-prova`, cioè la faceva **sparire**. *Testavo la versione
       facile del guasto: quella in cui il difetto si toglie di mezzo da solo.*
       Il caso vero è quello in cui resta lì, in un commento, a dire il contrario.

    ⚠️ LIMITE DICHIARATO. Per `.py` è esatto (`tokenize` conosce le stringhe).
       Per `.sh` è un'euristica di riga: taglia da un `#` che non sia dentro
       apici. Un `#` dentro una stringa a doppi apici con apici singoli annidati
       può ingannarla. ⇒ **può togliere codice di troppo (falso positivo:
       segnala una divergenza che non c'è), mai lasciarne di meno.**
       *Sbaglia nel verso in cui l'errore lo paga chi guarda, non chi si fida.*
    """
    if nome.endswith(".py"):
        import io
        import tokenize
        try:
            fuori = []
            for tok in tokenize.generate_tokens(io.StringIO(testo).readline):
                if tok.type != tokenize.COMMENT:
                    fuori.append(tok.string)
            return "\n".join(fuori)
        except (tokenize.TokenError, IndentationError, SyntaxError):
            # non poter tokenizzare non è «non ci sono commenti»: si dichiara
            # tenendo il testo intero, e il confronto sarà più permissivo. Il
            # rischio resta scritto qui invece di sparire in un except muto.
            return testo
    out = []
    for riga in testo.splitlines():
        singoli = doppi = 0
        taglio = None
        for i, c in enumerate(riga):
            if c == "'" and doppi % 2 == 0:
                singoli += 1
            elif c == '"' and singoli % 2 == 0:
                doppi += 1
            elif c == "#" and singoli % 2 == 0 and doppi % 2 == 0:
                taglio = i
                break
        out.append(riga if taglio is None else riga[:taglio])
    return "\n".join(out)


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
        contenuti[nome] = solo_codice(
            p.read_text(encoding="utf-8", errors="replace"), nome)

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
    import shutil
    import tempfile
    ok = True
    casi = 0
    with tempfile.TemporaryDirectory() as d:
        finta = Path(d)
        (finta / "installer").mkdir()
        for nome in INSTALLER:
            shutil.copy(RADICE / nome, finta / nome)
        # ① copia fedele → deve dire «concordano»
        esito, _ = confronta(finta)
        print(f"  {'✅' if esito == 0 else '🔴'} copia fedele → esito {esito} (atteso 0)")
        ok = ok and esito == 0
        casi += 1
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
        casi += 1
        # ②bis IL CASO CHE LA MIA PRIMA AUTOPROVA NON PRENDEVA: la unit non
        #      sparisce, RESTA in un commento — come si scrive una divergenza vera.
        for nome in INSTALLER:
            shutil.copy(RADICE / nome, finta / nome)
        # ⚠️ Va tolta SOLO dalla riga di CODICE. In `setup.sh` quella unit
        #   compare già due volte: riga 348 in un commento, riga 356 dentro
        #   `ENABLE_UNITS="…"`. **È la forma esatta di una divergenza vera**:
        #   il codice smette di abilitarla e il commento continua a nominarla.
        #   *Il mio primo tentativo sostituiva ENTRAMBE, e la seconda finiva
        #   dentro una stringa a doppi apici — dove un `#` NON è un commento,
        #   e lo stripper faceva bene a lasciarlo. Il test era malformato, non
        #   il codice: l'ho scoperto guardando le due righe invece del verdetto.*
        p = finta / "setup.sh"
        righe_f = p.read_text(encoding="utf-8").splitlines()
        for i, r in enumerate(righe_f):
            if "ENABLE_UNITS=" in r and "vps1777-secrets-check.timer" in r:
                righe_f[i] = r.replace(" vps1777-secrets-check.timer", "")
        p.write_text("\n".join(righe_f), encoding="utf-8")
        esito, righe = confronta(finta)
        scatta = esito == 1 and any("secrets-check" in r for r in righe)
        print(f"  {'✅' if scatta else '🔴'} unit tolta dal CODICE ma lasciata in un "
              f"COMMENTO → esito {esito} (atteso 1)")
        ok = ok and scatta
        casi += 1
        # ③ un file mancante NON è un verde
        (finta / "deploy.sh").unlink()
        esito, _ = confronta(finta)
        print(f"  {'✅' if esito == 2 else '🔴'} installer mancante → esito {esito} "
              f"(atteso 2: «non misurato», non 0)")
        ok = ok and esito == 2
        casi += 1
    # il numero si CONTA, non si scrive: era «3 casi» mentre ne giravano 4 —
    # un numero scritto a mano racconta l'intenzione, non il fatto.
    print(f"\n  ⇒ autoprova {'PASSATA' if ok else 'FALLITA'} ({casi} casi)")
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
