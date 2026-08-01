#!/usr/bin/env python3
"""Gate anti-leak: fallisce se nel repo entra roba che online non ci può stare.

Perché esiste
-------------
Il `.gitignore` non basta, per due motivi precisi:
  1. non ferma `git add -f`, e soprattutto
  2. non fa NULLA per un file già tracciato — una volta dentro, è dentro.
Serve un controllo che giri a ogni PR e dica "no" prima del merge, non dopo.

Il vettore vero, quello che ci ha morso: gli **export di sessione** (il transcript
di una chat di lavoro, `AAAA-MM-GG-HHMMSS-<slug>.txt`). Non sembrano segreti — sono
`.txt` con un nome innocuo — ma dentro ci passa tutto ciò che si è detto lavorando:
password incollate, IP, path locali, dati personali. È il file più pericoloso del
repo proprio perché non ha l'aria di esserlo.

Due regole
----------
  R1  nessun file tracciato con la forma di un export di sessione;
  R2  nessun materiale credenziale VERO dentro i file tracciati.

R2 distingue il **segnaposto** dal **materiale**: la doc deve poter scrivere
`tskey-auth-...` per spiegare cosa incollare. Un gate che grida al lupo sui
segnaposto viene disattivato in una settimana, e allora non protegge più niente.
Per questo i pattern pretendono lunghezza e alfabeto reali, non i puntini.

Output
------
Riporta **dove**, mai **cosa**. I log della CI di un repo pubblico sono pubblici:
un guardiano che stampa il segreto che ha trovato lo pubblica lui stesso.

Uso:  python3 security/check_no_leaks.py     (exit 1 = trovato qualcosa)
Stdlib only, come il resto di security/.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# ── R1 — roba che per natura non appartiene al repo ───────────────────────────
# a) `/export` di Claude Code produce: 2026-07-14-084038-<slug-della-prima-riga>.txt
SESSION_EXPORT = re.compile(r"(^|/)\d{4}-\d{2}-\d{2}-\d{6}-.*\.txt$")

# b) I transcript di sessione veri e propri: stessa classe degli export (la
#    conversazione integrale, password incollate comprese). Su una macchina di
#    lavoro ne girano a centinaia: la probabilità che uno finisca in un `add`
#    non è teorica.
SESSION_JSONL = re.compile(r"\.jsonl$")

# c) Database. Un `archive.db` committato per sbaglio non è "un file grosso": è
#    l'intero archivio — decine di migliaia di messaggi — in un oggetto solo.
#    Sono dati di un'installazione, non del progetto: non entrano, punto.
DATABASE = re.compile(r"\.(db|sqlite3?)(-wal|-shm)?$")

# Unica via d'uscita, stretta di proposito: una fixture di test piccola può
# essere un .jsonl legittimo. Un transcript vero non ci sta dentro il tetto.
FIXTURE_DIR = re.compile(r"(^|/)tests?/(fixtures?|data)/")
FIXTURE_MAX_BYTES = 64 * 1024

# ── R2 — materiale credenziale vero (non i segnaposto) ────────────────────────
# Ogni pattern pretende alfabeto+lunghezza reali, così `tskey-auth-...` nella doc
# non lo fa scattare ma `tskey-auth-kA9f…` sì.
SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("auth-key Tailscale", re.compile(r"tskey-[a-z]+-[A-Za-z0-9]{8,}")),
    ("token bot Telegram", re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b")),
    ("chiave age privata", re.compile(r"AGE-SECRET-KEY-1[A-Z0-9]{50,}")),
    (
        "chiave privata PEM",
        re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----"),
    ),
    # sshpass con password letterale. `-e` (da env) è la forma giusta e passa;
    # `-p "$VAR"`, `-p '<password>'` e `-p …` sono segnaposto e passano.
    (
        "password letterale in sshpass",
        re.compile(r"""sshpass\s+-p\s*['"]?(?![$<{.…])[^\s'"`$<>]{6,}"""),
    ),
    # 🔴 AGGIUNTO IL 01/08 (`abdd732a`) — il buco lo ha nominato l'audio `de03744a` del
    # round-10, che però lo attribuiva all'esenzione R3. Non c'entrava: una stringa di
    # connessione con la password dentro **non era coperta in NESSUN file del repo**,
    # esente o no. *Fatto vero, causa sbagliata — e la causa sbagliata è ciò che rende
    # un rilievo facile da archiviare: si smonta la causa e si butta anche il fatto.*
    # 🛡️ La password dev'essere REALE, come per gli altri pattern: `$VAR`, `${…}`,
    # `<password>`, `changeme`, `xxx` e `pass` sono segnaposto e passano.
    # 📏 MISURATO PRIMA DI ENTRARE, sui 176 file del corpus `6d9f9d5`: **0 match** —
    # e la controprova su 12 casi (4 devono scattare, 8 devono tacere) dà 12/12.
    # *Uno zero su un repo intero è il risultato di cui fidarsi meno: senza la
    # controprova sarebbe indistinguibile da un pattern che non sa dire di sì.*
    (
        "stringa di connessione con credenziali",
        re.compile(
            r"\b(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|redis|rediss"
            r"|amqps?|clickhouse)://[A-Za-z0-9._%-]+:"
            r"(?![\$<{*.…]|xxx|yyy|pass(?:word)?[@:]|changeme|segreto|placeholder"
            r"|redacted)[^\s'\"`@/\\]{6,}@"
        ),
    ),
]

# File che PARLANO dei pattern per mestiere (questo gate, e il registro dei
# rilievi che cita le evidenze). Allowlist stretta e motivata: se cresce, è un
# segnale che qualcosa non va — non una comodità.
# ⚠️ VALE SOLO PER R2 (materiale credenziale), e la restrizione è il fix di H60:
# era GLOBALE, quindi `security/findings.yml` non veniva scansionato affatto —
# ed è esattamente il file in cui il 27/07 è vissuto per otto ore un indirizzo
# pubblico, in `main` e in tre release. Un'esenzione concessa per una ragione
# («questo file cita i pattern dei segreti») si era estesa a tutte le ragioni.
# ⭐ La forma: un'allowlist per FILE esenta da OGNI regola; quella per REGOLA
# esenta da una sola. La prima è comoda da scrivere e cieca da usare.
# 📌 È un dict e non un set perché la ragione sta NEL DATO: finché stava nel
# commento qui sopra, il test poteva pretenderla da IP_AMMESSI e TSNET_AMMESSI
# (che erano dict) e non da qui — e i due elenchi senza presidio erano proprio
# quelli per FILE, cioè i più larghi. Un commento non è controllabile.
ALLOWLIST_R2 = {
    "security/check_no_leaks.py": "questo gate: i pattern dei segreti li contiene per mestiere",
    "security/findings.yml": "il registro dei rilievi: cita le evidenze dei pattern",
}

# ── R3 — indirizzi dell'AMBIENTE: mai, in nessuna forma ───────────────────────
# La regola che ci siamo dati è più stretta di «niente segreti»: nessun indirizzo,
# hostname o URL della macchina, né in un esempio né in un output di prova. Fino a
# H60 era una regola scritta e non presidiata, e infatti è stata violata dal commit
# che implementava la raccomandazione di un audit: documentando la PROVA di una
# misura ci è finito dentro l'ENDPOINT della misura.
# 📌 Ottetti 0-255 obbligatori: senza, «2.581.040.640» (byte di un backup) sarebbe
# un indirizzo. E le lookaround su punto/cifra evitano di ritagliare un pezzo di
# una versione o di un numero più lungo.
IPV4 = re.compile(
    r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?![\d.])"
)
# Un nome di tailnet reale identifica la RETE di una persona, non una macchina:
# per questo si guarda l'etichetta di mezzo. Il segnaposto a una sola etichetta
# (la forma con le parentesi angolari usata nel CHANGELOG) non combacia per
# costruzione; quello a due etichette usato nei test e in .env.example è
# dichiarato qui sotto per nome.
# 🔴 PRIMA QUESTA REGEX NON COMBACIAVA MAI: il `\b` stava in una stringa non-raw,
# quindi cercava un carattere di backspace. Sempre verde, per costruzione — la
# stessa classe che questo file esiste per impedire. L'ha trovata il suo test al
# primo giro, e solo perché fra i casi ce n'era uno che DOVEVA diventare rosso.
# Il segnaposto di tailnet usato in tutto il repo dal round-6 (commit 3b3b4b2, che
# tolse il nome vero). Sta qui per nome e col perché: senza, il gate era rosso su
# tre file legittimi — e un gate che grida al lupo viene spento, che è scritto
# venti righe più su e vale anche per chi lo scrive.
TSNET_AMMESSI = {"tailnet-esempio": "segnaposto del repo dal round-6, non è una rete reale"}
TSNET = re.compile(r"\b[a-z0-9][a-z0-9-]*\.[a-z0-9][a-z0-9-]*\.ts\.net\b", re.I)

# Indirizzi che NON sono ambiente, uno per uno e col perché — mai una regex
# generica «tanto sono esempi». Un'eccezione dichiarata è una cosa con un nome;
# una soglia allargata è N cose senza nome.
IP_AMMESSI = {
    "1.1.1.1": "resolver pubblico Cloudflare, bersaglio delle prove di rete",
    "8.8.8.8": "resolver pubblico Google, idem",
    "6.6.6.6": "indirizzo di comodo nei test dell'header X-Forwarded-For",
    "1.2.3.4": "esempio nella doc di deploy.sh e nei test OAuth",
    "4.1.2.1": "NON è un indirizzo: è il §4.1.2.1 di OAuth 2.0 citato in oauth.py",
}


# I DUE file in cui un indirizzo può comparire per mestiere: questo gate, che i
# pattern li contiene, e il suo test, che deve provare che un indirizzo pubblico
# venga fermato — e non può farlo senza scriverne uno.
# ⚠️ È un'esenzione per REGOLA e non per file, che è la distinzione con cui H60 si
# cura: `security/findings.yml` resta esente da R2 (cita i pattern dei segreti) ma
# NON da R3, ed è lì che l'indirizzo era finito.
# 🔴 E il prezzo va detto: questi due file sono l'unico posto dove un indirizzo
# vero potrebbe nascondersi senza che nessuno lo veda. Sono due, sono corti, e si
# leggono con gli occhi — un'esenzione che non si può leggere a mano è troppo larga.
# 📌 Dict come ALLOWLIST_R2, e per la stessa ragione: di tutti e quattro gli
# elenchi di esenzione questo è quello che il commento qui sopra dichiara più
# pericoloso, ed era l'unico che nessun test guardava.
ALLOWLIST_R3 = {
    "security/check_no_leaks.py": "questo gate: gli indirizzi di esempio li contiene per mestiere",
    "tools/tests/test_no_leaks.py": (
        "il test del gate: deve provare che un indirizzo pubblico venga fermato, "
        "e non può farlo senza scriverne uno"
    ),
}


def tsnet_da_ignorare(nome: str) -> bool:
    """True se il nome combaciato usa il segnaposto dichiarato del repo.

    È una funzione e non due righe dentro il loop apposta: l'esenzione di un
    presidio è la parte che va provata per prima, perché è l'unica che può
    renderlo cieco senza farlo sembrare rotto.
    """
    return nome.lower().rsplit(".ts.net", 1)[0].rsplit(".", 1)[-1] in TSNET_AMMESSI


def indirizzo_da_ignorare(ip: str) -> bool:
    """True se non è un indirizzo dell'ambiente di qualcuno.

    Il criterio è «può identificare una macchina reale?», non «sembra finto».
    """
    if ip in IP_AMMESSI:
        return True
    try:
        o = [int(x) for x in ip.split(".")]
    except ValueError:  # pragma: no cover — la regex lo esclude
        return True
    if o[0] in (0, 127) or o == [255, 255, 255, 255]:
        return True                                    # loopback e riservati
    if o[0] == 10 or (o[0] == 172 and 16 <= o[1] <= 31) or (o[0] == 192 and o[1] == 168):
        return True                                    # RFC 1918, reti private
    if o[0] == 169 and o[1] == 254:
        return True                                    # link-local
    if 224 <= o[0] <= 239:
        return True                                    # multicast
    # RFC 5737: gli indirizzi che esistono APPOSTA per la documentazione.
    if (o[0], o[1], o[2]) in ((192, 0, 2), (198, 51, 100), (203, 0, 113)):
        return True
    return False

BINARY_HINT = b"\x00"


def tracked_files() -> list[str]:
    # `--others --exclude-standard` aggiunge i file NUOVI e non ignorati: senza,
    # il gate rispondeva sul repo com'è e non su come sta per diventare. Misurato
    # il 27/07 nel modo peggiore — ha detto verde mentre in un file appena creato
    # veniva riscritto l'indirizzo che H60 aveva appena tolto. In CI la differenza
    # non si vede (là è tutto tracciato); in locale, prima di `git add`, è la
    # differenza fra un presidio e un condono.
    out = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        capture_output=True, check=True
    ).stdout
    return [p for p in out.decode("utf-8", "replace").split("\0") if p]


def main() -> int:
    problems: list[str] = []

    for path in tracked_files():
        # R1 — la forma del nome basta a bocciarlo: non serve guardarci dentro.
        if SESSION_EXPORT.search(path):
            problems.append(
                f"  [R1] {path}\n"
                f"       → export di sessione tracciato. Un transcript di lavoro non va nel repo:\n"
                f"         dentro ci finisce tutto quello che ci si è detti lavorando.\n"
                f"       → toglilo (`git rm --cached`) e tienilo fuori dal repo."
            )
            continue

        if DATABASE.search(path):
            problems.append(
                f"  [R1] {path}\n"
                f"       → database tracciato. Non è «un file grosso»: è l'intero contenuto\n"
                f"         di un'installazione (un archivio può valere decine di migliaia di\n"
                f"         messaggi) in un oggetto solo. I dati non stanno nel repo.\n"
                f"       → `git rm --cached` e tienilo fuori. Nessuna eccezione prevista."
            )
            continue

        if SESSION_JSONL.search(path):
            size = Path(path).stat().st_size if Path(path).is_file() else 0
            if FIXTURE_DIR.search(path) and size <= FIXTURE_MAX_BYTES:
                pass  # fixture piccola e in chiaro sotto tests/: legittima
            else:
                why = (
                    f"supera il tetto fixture ({size} B > {FIXTURE_MAX_BYTES} B)"
                    if FIXTURE_DIR.search(path)
                    else "sta fuori da tests/fixtures/"
                )
                problems.append(
                    f"  [R1] {path}\n"
                    f"       → .jsonl tracciato che {why}.\n"
                    f"         È la stessa classe degli export di sessione: un transcript\n"
                    f"         integrale, password incollate comprese.\n"
                    f"       → se è davvero una fixture, mettila in tests/fixtures/ e tienila\n"
                    f"         piccola; se è un transcript, fuori dal repo."
                )
                continue

        p = Path(path)
        if not p.is_file():
            continue
        try:
            raw = p.read_bytes()
        except OSError:
            continue
        if BINARY_HINT in raw[:8192]:  # binario: niente scansione testuale
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue

        # R3 gira anche sui file esenti da R2 — vedi il commento su ALLOWLIST_R2 —
        # e salta solo i due che gli indirizzi li contengono per mestiere.
        if path in ALLOWLIST_R3:
            if path in ALLOWLIST_R2:
                continue
            for label, pattern in SECRET_PATTERNS:
                for m in pattern.finditer(text):
                    line = text.count("\n", 0, m.start()) + 1
                    problems.append(f"  [R2] {path}:{line} → sembra {label}.")
                    break
            continue
        for m in IPV4.finditer(text):
            ip = m.group(0)
            if indirizzo_da_ignorare(ip):
                continue
            line = text.count("\n", 0, m.start()) + 1
            problems.append(
                f"  [R3] {path}:{line}\n"
                f"       → un indirizzo IP pubblico (valore non stampato di proposito).\n"
                f"       → la regola è più stretta di «niente segreti»: nessun indirizzo\n"
                f"         dell'ambiente, nemmeno in un esempio o in un output di prova.\n"
                f"       → se serve un esempio, usa RFC 5737 (192.0.2.x, 198.51.100.x,\n"
                f"         203.0.113.x): esistono apposta e non sono di nessuno.\n"
                f"       → se è un bersaglio di test noto, aggiungilo a IP_AMMESSI COL PERCHÉ."
            )
            break
        for m in TSNET.finditer(text):
            if tsnet_da_ignorare(m.group(0)):
                continue
            line = text.count("\n", 0, m.start()) + 1
            problems.append(
                f"  [R3] {path}:{line}\n"
                f"       → un nome di tailnet reale (valore non stampato di proposito).\n"
                f"       → nella doc si scrive `<host>.ts.net`: identifica la forma,\n"
                f"         non la rete di una persona."
            )
            break

        if path in ALLOWLIST_R2:
            continue

        for label, pattern in SECRET_PATTERNS:
            for m in pattern.finditer(text):
                line = text.count("\n", 0, m.start()) + 1
                # Riporta la POSIZIONE, mai il valore: questo output finisce in un log pubblico.
                problems.append(
                    f"  [R2] {path}:{line}\n"
                    f"       → sembra {label} (valore non stampato di proposito).\n"
                    f"       → se è un segnaposto per la doc, rendilo evidente (`tskey-auth-...`);\n"
                    f"         se è vero: NON basta toglierlo — quel segreto va considerato bruciato\n"
                    f"         e va RUOTATO. La storia di git non dimentica."
                )
                break  # un rilievo per file/pattern basta a bocciare la build

    if problems:
        print("✗ gate anti-leak: trovata roba che online non ci può stare\n")
        print("\n".join(problems))
        print(
            "\nPerché la build è rossa: quello che finisce in un repo pubblico è pubblico\n"
            "da subito, e rimuoverlo dopo non lo disfa — resta nella storia, nei diff delle\n"
            "PR e in ogni clone. Il momento per fermarlo è adesso, non al prossimo audit."
        )
        return 1

    print("✓ gate anti-leak: nessun export di sessione tracciato, nessun materiale credenziale.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
