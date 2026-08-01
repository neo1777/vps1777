"""Test della regola R3 di security/check_no_leaks.py — gli indirizzi dell'ambiente.

Perché esiste: R3 nasce da H60, cioè da una regola che c'era ed era scritta
(«nessun indirizzo, hostname o URL della macchina, in nessuna forma») e che
nessun presidio applicava. È vissuta violata per otto ore in `main` e in tre
release di un repo pubblico.

⭐ Il metro qui è quello che ci siamo dati oggi: non basta che la sonda sappia
diventare rossa. Deve dare le risposte GIUSTE su casi costruiti — compresi
quelli che deve lasciar passare e quelli che non la riguardano affatto. La metà
dei casi qui sotto serve a impedire i FALSI rossi, perché un gate che grida al
lupo viene disattivato, e allora non protegge più niente.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "check_no_leaks", _ROOT / "security" / "check_no_leaks.py")
g = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(g)


# ───────────────────────────── quello che DEVE fermare ──────────────────────

def test_ferma_un_indirizzo_pubblico_qualunque():
    # La CLASSE di ciò che è sfuggito il 27/07: un indirizzo pubblico finito in
    # una nota che documentava una misura.
    # 🔴 LA PRIMA STESURA DI QUESTO TEST CI SCRIVEVA DENTRO L'INDIRIZZO VERO —
    # nel file che esiste per impedire quella cosa, sotto un commento che diceva
    # «non è scritto qui, si prova la CLASSE». E il gate ha detto VERDE, perché
    # scansionava solo i file già tracciati e questo era nuovo. Due difetti in un
    # gesto: il valore riscritto, e il presidio che non poteva vederlo.
    # ⭐ Un presidio che non guarda ciò che stai per aggiungere guarda solo i tuoi
    # errori passati.
    # 🔺 01/08: qui c'era ANCORA l'indirizzo vero della macchina — non nella
    # prima stesura (quella l'aveva già corretta il gate), ma nel valore rimasto
    # dentro il test dopo la cura. Il commento sopra racconta il difetto al
    # passato mentre il difetto era ancora due righe più giù.
    # ⭐ Trovato passando il CORPUS di un audit al gate PRIMA di caricarlo su un
    # servizio esterno: il presidio su ciò che entra in git non aveva mai guardato
    # ciò che ESCE dal disco. 93.184.216.34 è pubblico, di nessuno, e prova identico.
    for ip in ("93.184.216.34", "5.9.100.7", "185.199.108.153"):
        assert not g.indirizzo_da_ignorare(ip), ip


def test_ferma_un_nome_di_tailnet_reale_ma_non_il_segnaposto():
    # Due etichette = una rete di qualcuno. Una sola = il segnaposto del CHANGELOG.
    assert g.TSNET.search("macchina.tigre-lampo.ts.net")
    assert not g.TSNET.search("<host>.ts.net")
    assert not g.tsnet_da_ignorare("macchina.tigre-lampo.ts.net")


def test_il_segnaposto_del_repo_e_esentato_e_dichiarato_per_nome():
    # CIÒ CHE DEVE LASCIAR PASSARE: il segnaposto adottato dal round-6 vive in
    # .env.example e nei test del pannello admin. Senza questa esenzione il gate
    # sarebbe rosso su tre file legittimi — e un gate che grida al lupo viene
    # spento, che è scritto nel gate stesso.
    assert g.TSNET_AMMESSI, "l'esenzione esiste ma non è dichiarata per nome"
    for segnaposto, perche in g.TSNET_AMMESSI.items():
        assert perche, f"{segnaposto} esentato senza il perché scritto"
        assert g.tsnet_da_ignorare(f"qualcosa.{segnaposto}.ts.net")
    # …e l'esenzione NON deve allargarsi a un nome che le somiglia soltanto.
    uno = next(iter(g.TSNET_AMMESSI))
    assert not g.tsnet_da_ignorare(f"qualcosa.{uno}-vero.ts.net")


# ──────────────────── quello che deve LASCIAR PASSARE ───────────────────────

def test_lascia_passare_le_reti_private_e_il_loopback():
    for ip in ("127.0.0.1", "0.0.0.0", "10.1.2.3", "172.21.0.1", "172.31.255.1",
               "192.168.0.5", "169.254.1.1", "224.0.0.1", "255.255.255.255"):
        assert g.indirizzo_da_ignorare(ip), ip


def test_lascia_passare_gli_indirizzi_nati_per_la_documentazione():
    # RFC 5737: esistono apposta e non sono di nessuno. È la risposta da dare a
    # chi chiede «e allora come scrivo un esempio?».
    for ip in ("192.0.2.1", "198.51.100.42", "203.0.113.10"):
        assert g.indirizzo_da_ignorare(ip), ip


def test_lascia_passare_i_bersagli_di_test_dichiarati_uno_per_uno():
    for ip in ("1.1.1.1", "8.8.8.8", "6.6.6.6", "1.2.3.4"):
        assert g.indirizzo_da_ignorare(ip), ip
        assert g.IP_AMMESSI[ip], f"{ip} è ammesso ma senza il perché scritto"


# ─────────────── quello che NON LA RIGUARDA — i falsi rossi ─────────────────

def test_un_numero_di_sezione_non_e_un_indirizzo():
    # `§4.1.2.1` di OAuth 2.0 sta in services/gateway/app/oauth.py e combacia
    # con QUALUNQUE regex IPv4. È il falso rosso che avrebbe fatto disattivare
    # il gate alla prima settimana.
    assert g.indirizzo_da_ignorare("4.1.2.1")


def test_un_numero_lungo_non_diventa_un_indirizzo():
    # 2.581.040.640 sono i byte di un backup, scritti col separatore italiano.
    # Gli ottetti 0-255 obbligatori li escludono per costruzione: senza, il
    # registro dei rilievi sarebbe rosso per una dimensione di file.
    assert not g.IPV4.search("2.581.040.640")
    assert not g.IPV4.search("2.581.040.640 byte")


def test_una_versione_non_diventa_un_indirizzo():
    for testo in ("0.40.10", "v0.40.10", "ruff 0.15.22", "1.2.3", "28.0.4"):
        assert not g.IPV4.search(testo), testo


def test_un_indirizzo_non_si_ritaglia_da_dentro_un_numero_piu_lungo():
    # Senza le lookaround, «10.0.0.1.5» darebbe «10.0.0.1» e passerebbe come
    # privato — mascherando ciò che c'è davvero scritto.
    assert not g.IPV4.search("10.0.0.1.5")
    assert not g.IPV4.search("1.10.0.0.1")


# ────────────────── R2 · stringhe di connessione (01/08, `abdd732a`) ─────────
# 🔴 QUESTI SONO I PRIMI TEST DI R2 IN QUESTO FILE, e la scoperta vale più del
#   pattern che provano: fino a oggi qui si testava **solo R3**. Il file è esente
#   da R3 (deve contenere indirizzi veri per provare che vengono fermati) ma NON
#   da R2 — e non se n'era mai accorto nessuno, perché non conteneva materiale
#   credenziale. ⭐ *L'esenzione reggeva per una proprietà del CONTENUTO, non per
#   una decisione: bastava il primo test di R2 a farla cadere.*
# 🛡️ LA TECNICA, ed è il motivo per cui le stringhe sono spezzate: un caso di
#   prova scritto per intero **farebbe scattare il gate su questo stesso file** e
#   bloccherebbe ogni commit. Concatenandolo a runtime, la sequenza non esiste mai
#   nel sorgente — il gate legge il testo, il test vede la stringa intera.
#   *È l'unico modo di provare R2 qui dentro senza allargare l'allowlist: e
#   allargarla sarebbe stato esattamente il difetto che H60 ha già pagato.*

def _dsn(schema: str, pwd: str) -> str:
    """Compone un DSN a runtime: nel sorgente non esiste come sequenza."""
    return schema + "://app:" + pwd + "@" + "db.example.com:5432/prod"


def _r2(testo: str) -> bool:
    return any(p.search(testo) for _, p in g.SECRET_PATTERNS)


def test_r2_ferma_una_stringa_di_connessione_con_password_vera():
    assert _r2(_dsn("postgresql", "Kj3nR8vQx2Lm"))
    assert _r2(_dsn("mysql", "aB9xK2mQ7pLw"))
    assert _r2(_dsn("mongodb+srv", "Zx8Kq2mNv5Rt"))
    assert _r2(_dsn("redis", "Q7wErTy9UiOp"))


def test_r2_lascia_passare_i_segnaposto_di_una_stringa_di_connessione():
    # La metà che impedisce il falso rosso: se un gate grida al lupo sulla doc,
    # viene disattivato — e allora non protegge più niente.
    assert not _r2("postgresql://app:" + "$DB_PASSWORD" + "@db:5432/prod")
    assert not _r2("postgresql://app:" + "${DB_PASS}" + "@db:5432/prod")
    assert not _r2("postgres://user:" + "<password>" + "@host/db")
    assert not _r2("mysql://root:" + "changeme" + "@localhost/test")
    assert not _r2(_dsn("postgresql", "pass"))          # segnaposto corto
    assert not _r2("postgresql://app" + "@db:5432/prod")  # nessuna password


def test_r2_non_scatta_su_un_url_qualunque():
    # Un `://` con dentro i due punti non è una credenziale: senza questo caso il
    # pattern potrebbe prendere qualunque URL con una porta e nessuno lo saprebbe.
    assert not _r2("https://api.example.com:8443/v1/token")
    assert not _r2("http://localhost:17772/dati")


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {name}")
            except Exception as exc:  # noqa: BLE001
                fails += 1
                print(f"FAIL {name}: {exc}")
    raise SystemExit(1 if fails else 0)
