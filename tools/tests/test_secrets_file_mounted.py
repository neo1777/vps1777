#!/usr/bin/env python3
"""«Secrets sempre file-mounted … mai in env var» (`SECURITY.md`) — presidiata.

PERCHÉ ESISTE, per intero — serve a chi lo vedrà fallire.

`SECURITY.md` promette: *«**Secrets sempre file-mounted** (baseline): password, signing
key, token via Docker `secrets:` in `tmpfs /run/secrets/`, **mai** in env var»*. È una
garanzia con due quantificatori — *sempre* e *mai* — e quando una promessa dice «ogni»,
l'evidenza non può essere un esempio: serve enumerare.

Perché un env var non è un file mount: le variabili d'ambiente di un container si leggono
da `docker inspect` (che chiunque nel gruppo `docker` può chiamare), finiscono nei log dei
crash-reporter e sono ereditate da **ogni processo figlio**. Un file in `tmpfs
/run/secrets/` no: lo legge chi lo apre, ha permessi propri, e non compare nell'inventario
del container.

## La scelta di progetto di questo file, ed è la lezione della giornata del 10/08

L'insieme dei segreti **non è dedotto dai nomi** (`*PASSWORD*`, `*TOKEN*`, `*SECRET*`):
è preso dalla sezione `secrets:` dei compose, che è la **dichiarazione autorevole**.

    ❌  «cerca le variabili che sembrano segreti»  → OAUTH_ACCESS_TOKEN_LIFETIME: "900"
                                                     è una durata, e un presidio che grida
                                                     su di lei viene disattivato
    ✅  «per ogni segreto DICHIARATO, com'è consegnato?»

⭐ Il 10/08 questo repo ha pagato **nove volte in un giorno** la stessa forma — *un insieme
definito da una stringa invece che dall'oggetto* (il socket per path, i volumi enumerati a
mano, gli script per estensione…). Qui l'oggetto esiste ed è scritto: usarlo costa meno
che inventare un'euristica, e non ha falsi positivi per costruzione.

## Cosa misura

  ① ogni secret dichiarato è **consumato** da almeno un servizio via `secrets:`
     (un secret dichiarato e mai montato non è protetto: è inutilizzato, e la differenza
     va detta invece che lasciata dedurre)
  ② nessun `environment:` assegna il segreto **per valore**: la sola forma ammessa è
     `<NOME>_FILE: /run/secrets/<nome>`, cioè un PATH, non il contenuto

Stile: stdlib-only, nessuna dipendenza — `uvx pytest tools/tests/` gira senza PyYAML, e un
import di troppo non fallisce questo test: impedisce agli altri di partire, in collect.
Uso:  python3 tools/tests/test_secrets_file_mounted.py     (esce 1 al primo difetto)
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def compose_del_repo() -> list[Path]:
    """Tutti i compose, `plugins/` compreso: quelli sono TEMPLATE DA COPIARE, quindi il
    codice nuovo nasce proprio lì — è il rilievo che il 09/08 ha allargato il perimetro
    del presidio gemello sul socket Docker da un file a tutti."""
    return sorted(p for p in ROOT.rglob("compose*.y*ml")
                  if p.is_file() and ".git" not in p.parts)


def senza_commento(riga: str) -> str:
    return re.sub(r"(?:^|\s)#.*$", "", riga)


def secrets_dichiarati(testo: str) -> list[str]:
    """I nomi sotto la sezione `secrets:` TOP-LEVEL (colonna 0), non quella dei servizi.

    La distinzione conta: `secrets:` dentro un servizio ELENCA i nomi da montare, quella
    top-level li DEFINISCE. Confonderle darebbe un insieme con i duplicati e, peggio,
    farebbe sembrare dichiarato un nome che nessuno ha definito.
    """
    fuori: list[str] = []
    dentro = False
    for riga in testo.splitlines():
        r = senza_commento(riga)
        if not r.strip():
            continue
        if re.match(r"^secrets:\s*$", r):
            dentro = True
            continue
        if dentro:
            m = re.match(r"^  ([A-Za-z0-9_.-]+):\s*$", r)
            if m:
                fuori.append(m.group(1))
                continue
            if not r.startswith(" "):          # una chiave top-level nuova: sezione finita
                dentro = False
    return fuori


def assegnazioni_environment(testo: str) -> list[tuple[int, str, str]]:
    """(riga, NOME, valore) di ogni assegnazione in un blocco `environment:`."""
    fuori: list[tuple[int, str, str]] = []
    indent_env: int | None = None
    for n, riga in enumerate(testo.splitlines(), 1):
        r = senza_commento(riga)
        if not r.strip():
            continue
        ind = len(r) - len(r.lstrip())
        if re.match(r"^\s*environment:\s*$", r):
            indent_env = ind
            continue
        if indent_env is None:
            continue
        if ind <= indent_env:                  # blocco finito
            indent_env = None
            continue
        m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$", r)
        if m:
            fuori.append((n, m.group(1), m.group(2).strip()))
    return fuori


def via_docker(path: Path) -> tuple[list[str], list[tuple[int, str, str]]] | None:
    """Chiede a `docker compose config` il compose NORMALIZZATO. None se non si può.

    🔴 PERCHÉ ESISTE, ed è una rettifica: la prima versione di questo file parsava il
    testo con tre regex, e b82df434 ha misurato che **il presidio aveva quattro modi di
    dare verde su un segreto in chiaro** — tre erano forme YAML che le mie regex non
    riconoscevano:
        environment in forma LISTA   `- GATEWAY_SECRET=valore`     invisibile
        dichiarazione in flow map    `nome: {file: ./x.txt}`        fuori dall'insieme
        indentazione diversa da 2    YAML valido                    fuori dall'insieme
    ⭐ *Il file diceva «con l'insieme preso dall'oggetto i falsi positivi non esistono
    per costruzione» — vero per QUALE segreto esiste, e falso per le altre tre domande
    che il presidio si faceva, tutte risolte da una regex.*

    ⇒ **la lista si chiede, non si dichiara.** È la regola che `restore.sh` aveva già e
    che `backup.sh` violava sullo stesso oggetto (#146), ed è ciò che ha chiuso in due
    minuti la divergenza sul socket: *avevamo interrogato il guardiano e nessuna aveva
    chiesto alla serratura.* Il compose normalizzato non ha forme alternative: docker le
    ha già collassate tutte, e non è più il mio parser a decidere cosa è un'assegnazione.
    """
    if not shutil.which("docker"):
        return None
    base = ROOT / "compose.yaml"
    # 🔑 due tentativi, e il secondo copre la maggioranza: un OVERLAY da solo non è un
    #   progetto valido («refers to undefined network backend») — lo diventa insieme al
    #   compose base, che è il modo in cui viene usato davvero. Senza questo secondo
    #   tentativo il parser testuale prendeva 8 file su 12, cioè la copertura piena
    #   valeva per un terzo del perimetro mentre la riga finale diceva «tutti».
    tentativi = [["-f", str(path)]]
    if path != base and base.is_file():
        tentativi.append(["-f", str(base), "-f", str(path)])
    r = None
    for args in tentativi:
        r = subprocess.run(["docker", "compose", *args, "config", "--format", "json"],
                           capture_output=True, text=True, check=False, cwd=str(ROOT))
        if r.returncode == 0:
            break
    if r is None or r.returncode != 0:
        return None                      # né da solo né col base: resta il parser testuale
    try:
        d = json.loads(r.stdout)
    except json.JSONDecodeError:
        return None
    dichiarati = sorted((d.get("secrets") or {}).keys())
    assegnazioni: list[tuple[int, str, str]] = []
    for nome, srv in (d.get("services") or {}).items():
        env = srv.get("environment") or {}
        if isinstance(env, list):        # difesa: la normalizzazione dovrebbe dare un dict
            env = dict(x.split("=", 1) for x in env if "=" in x)
        for var, val in env.items():
            assegnazioni.append((0, var, "" if val is None else str(val)))
    return dichiarati, assegnazioni


def main() -> int:
    compose = compose_del_repo()
    print(f"garanzia presidiata: «Secrets sempre file-mounted … mai in env var» "
          f"(SECURITY.md) · radice: {ROOT}")
    if not compose:
        print("  ✗ nessun compose trovato: la sonda non guarda il repo giusto")
        return 1

    testi = {p: p.read_text(encoding="utf-8") for p in compose}
    dichiarati: dict[str, Path] = {}
    assegnazioni: dict[Path, list[tuple[int, str, str]]] = {}
    normalizzati: list[str] = []
    a_mano: list[str] = []
    for p, t in testi.items():
        # 🔴 OGNI FONTE PER CIÒ CHE SA FARE, e questa riga è una rettifica misurata.
        #   Passando ai secret del compose NORMALIZZATO l'insieme è sceso da 7 a 6:
        #   `docker compose config` OMETTE i secret che nessun servizio del progetto
        #   composto usa — `cloudflared_token` è dichiarato in un overlay il cui servizio
        #   non è attivo, e spariva dalla sorveglianza.
        #   ⭐ Avevo curato un buco di COPERTURA (le forme YAML che le regex non vedevano)
        #     e cambiato la SUPERFICIE senza chiedermi **quale popolazione ESCE** — la
        #     domanda che ho scritto io stamattina in senso opposto («quale popolazione
        #     ENTRA in ogni filtro a valle»), e che vale nei due versi.
        #   ⇒ l'insieme dei DICHIARATI lo dà il testo (non omette niente); le
        #     ASSEGNAZIONI le dà il normalizzato (non ha forme cieche).
        for nome in secrets_dichiarati(t):
            dichiarati.setdefault(nome, p)
        d = via_docker(p)
        if d is not None:
            normalizzati.append(p.name)
            for nome in d[0]:
                dichiarati.setdefault(nome, p)
            assegnazioni[p] = d[1]
        else:
            a_mano.append(p.name)
            assegnazioni[p] = assegnazioni_environment(t)

    if not dichiarati:
        # la guardia della guardia: senza, questo test passerebbe a mani vuote il giorno
        # in cui i secret cambiassero forma — e il verde direbbe «nessun segreto in env»
        # quando la verità è «non ho trovato segreti».
        print("  ✗ nessun secret dichiarato in nessun compose. Se è deliberato va tolto\n"
              "      anche questo test: un presidio che sorveglia un insieme vuoto è\n"
              "      un verde che non significa niente.")
        return 1

    errori = 0
    # 🔴 LA COPERTURA RIDOTTA SI VEDE, non si deduce. Se docker non c'è, o un overlay non
    #   è componibile da solo, quel file torna al parser testuale — che b82df434 ha
    #   misurato avere tre punti ciechi. Uno skip che si legge come un pass è il difetto
    #   che questo repo si è preso sulla #146: qui è stampato accanto al perimetro.
    print(f"  perimetro: {len(compose)} compose · {len(dichiarati)} secret dichiarati")
    print(f"  letti da `docker compose config` (normalizzati): {len(normalizzati)}")
    if a_mano:
        print(f"  ⚠️ letti col parser TESTUALE, copertura ridotta: {len(a_mano)} — "
              f"{', '.join(a_mano)}")
        print("     (docker assente o overlay non componibile da solo: le forme "
              "lista/flow-map/indentazione non-2 non sono viste in questi file)")

    # ① ogni secret dichiarato è montato da almeno un servizio
    for nome, dove in sorted(dichiarati.items()):
        montato = any(re.search(rf"^\s+-\s+{re.escape(nome)}\s*$", t, re.M)
                      for t in testi.values())
        if not montato:
            errori += 1
            print(f"  ✗ `{nome}` (dichiarato in {dove.name}) non è montato da nessun\n"
                  f"      servizio: o è morto, o arriva in un altro modo — e il secondo\n"
                  f"      caso è quello che questa garanzia esclude.")

    # ② nessuno di essi passa per VALORE in environment
    for p in compose:
        for n, var, valore in assegnazioni.get(p, []):
            base = var[:-5] if var.endswith("_FILE") else var
            corrispondenti = [s for s in dichiarati if s.upper() == base]
            if not corrispondenti:
                continue                        # non è un segreto dichiarato: non è affare nostro
            nome = corrispondenti[0]
            if not var.endswith("_FILE"):
                errori += 1
                print(f"  ✗ {p.name}:{n} · `{var}` porta il segreto `{nome}` in una\n"
                      f"      VARIABILE D'AMBIENTE. `docker inspect` la mostra, i figli\n"
                      f"      la ereditano, i crash-reporter la registrano.\n"
                      f"      SECURITY.md promette «mai in env var»: la forma è\n"
                      f"      `{var}_FILE: /run/secrets/{nome}`.")
            elif not valore.startswith("/run/secrets/"):
                errori += 1
                print(f"  ✗ {p.name}:{n} · `{var}` punta a «{valore}», fuori da\n"
                      f"      /run/secrets/. Il suffisso _FILE dice «è un path», ma la\n"
                      f"      garanzia è il tmpfs: un path qualunque non ce l'ha.")

    if not errori:
        print(f"  ✓ {len(dichiarati)} segreti, tutti montati e consegnati come path in "
              f"/run/secrets/ — nessuno per valore")
    return 1 if errori else 0


def test_i_segreti_non_passano_per_valore() -> None:
    """Il gancio che rende questo file un test PER PYTEST, non solo per la mano.

    Senza, `uvx pytest tools/tests/` raccoglie il file e non esegue niente: nessuna
    funzione `test_*`, nessun errore, verde.
    """
    assert main() == 0


def test_la_sonda_distingue_il_segreto_dalla_sua_omonimia() -> None:
    """La controprova, e il caso che decide la forma del presidio.

    `OAUTH_ACCESS_TOKEN_LIFETIME: "900"` contiene TOKEN ed è una durata: un presidio
    costruito sui nomi sospetti griderebbe su di lei, e *un guardiano che grida viene
    disattivato*. Qui non può succedere, perché l'insieme viene dalla DICHIARAZIONE.
    """
    finto = """secrets:
  telegram_bot_token:
    file: ./secrets/telegram_bot_token.txt
services:
  bot:
    environment:
      TELEGRAM_BOT_TOKEN_FILE: /run/secrets/telegram_bot_token
      OAUTH_ACCESS_TOKEN_LIFETIME: "900"
    secrets:
      - telegram_bot_token
"""
    assert secrets_dichiarati(finto) == ["telegram_bot_token"]
    nomi = [v for _, v, _ in assegnazioni_environment(finto)]
    assert nomi == ["TELEGRAM_BOT_TOKEN_FILE", "OAUTH_ACCESS_TOKEN_LIFETIME"]

    # e la sezione `secrets:` di un SERVIZIO non definisce niente: se finisse fra i
    # dichiarati, il presidio inseguirebbe un nome che nessuno ha definito.
    assert "bot" not in secrets_dichiarati(finto)


if __name__ == "__main__":
    sys.exit(main())
