"""I due tetti sul body non devono scavalcarsi — stdlib-only, offline.

Il sistema ha DUE tetti, in due file e due linguaggi:

    services/gateway/app/archive_indexer.py   MAX_UPLOAD_BYTES   (il massimo LEGITTIMO)
    ingress/Caddyfile                         request_body max_size  (il tetto ASSOLUTO)

Il secondo deve restare **sopra** il primo. Se scende sotto, Caddy diventa il primo
decisore e risponde 413 a un upload che il gateway accetterebbe: la logica per-path
del gateway non verrebbe mai raggiunta, e il sintomo sarebbe un errore in produzione
su un caso legittimo.

⚠️ Perché un test e non solo un commento (rilievo di b82df434 sulla #122, accolto —
e la sua riga accanto a `MAX_UPLOAD_BYTES` resta, non è alternativa a questa):
`MAX_UPLOAD_BYTES` È GIÀ CAMBIATO una volta, 1 GB → 4 GB il 20/07, perché un bundle
reale da 2,6 GB moriva. Può crescere ancora. E la #93, mergiata oggi, esiste proprio
perché *«fra le due volte la lezione era GIÀ scritta, con la coordinata e il rimedio
in chiaro — e non ha impedito la seconda»*: una riga si legge quando si rilegge il
file, non quando la mano digita il numero.

🔑 E il parser del Caddyfile IGNORA I COMMENTI, che non è un dettaglio: in quel file
`max_size` compare quattro volte e tre sono dentro commenti (esempi della misura su
`respond` vs `reverse_proxy`). Un parser ingenuo leggerebbe `1KB` da un commento e
dichiarerebbe il tetto violato — o peggio, in un altro ordine, lo dichiarerebbe
rispettato. È lo stesso difetto per cui H48 mi ha dato una CI rossa stanotte, preso
dal verso opposto.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

_RADICE = Path(__file__).resolve().parents[3]
_INDEXER = _RADICE / "services" / "gateway" / "app" / "archive_indexer.py"
_CADDYFILE = _RADICE / "ingress" / "Caddyfile"

# 🔬 LE UNITÀ DI CADDY SONO DECIMALI, e non è un dettaglio da pignoli: MISURATO il
#   09/08 su caddy:2.8-alpine (rilievo di b82df434, verificato da me con una prova
#   discriminante invece di crederci sulla parola):
#       max_size 1KB · body  990 byte → HTTP 200
#       max_size 1KB · body 1010 byte → HTTP 413    ⇒ 1KB = 1000, non 1024
#   ⇒ `5GB` sono 5·10⁹ = 5.000.000.000, mentre `MAX_UPLOAD_BYTES` è 4·2³⁰ =
#     4.294.967.296. Il margine REALE è 705.032.704 byte ≈ 672 MiB, non «1 GB» come
#     verrebbe da leggere. La prima versione di questo file mappava `gb → 1024³` e
#     avrebbe dichiarato un tetto di Caddy più alto del vero: il verdetto oggi non
#     cambia (5·10⁹ > 4·2³⁰ comunque), ma il margine sì — e il margine è il motivo
#     per cui questo test esiste.
_UNITA = {
    "": 1, "b": 1,
    "kb": 1000, "mb": 1000**2, "gb": 1000**3, "tb": 1000**4,
    # Caddy accetta anche le binarie esplicite; se un domani il Caddyfile le usa,
    # questo test le legge invece di sbagliare in silenzio.
    "kib": 1024, "mib": 1024**2, "gib": 1024**3, "tib": 1024**4,
}


def _in_byte(testo: str) -> int:
    """«5GB» → byte, con le unità DECIMALI di Caddy (vedi la misura sopra)."""
    m = re.fullmatch(r"(\d+)\s*([a-zA-Z]*)", testo.strip())
    assert m, f"valore non riconosciuto: {testo!r}"
    unita = m.group(2).lower()
    assert unita in _UNITA, (
        f"unità «{m.group(2)}» non riconosciuta in ingress/Caddyfile: questo test "
        f"non sa convertirla e quindi NON sta verificando il tetto. Estendi _UNITA."
    )
    return int(m.group(1)) * _UNITA[unita]


def _intero(nodo: ast.AST) -> int:
    """Valuta un'espressione di soli interi e moltiplicazioni/somme.

    ⚠️ `ast.literal_eval` NON basta qui, e la prima versione di questo file ci è
    cascata: la costante è scritta `4 * 1024 * 1024 * 1024`, cioè un `BinOp`, e
    `literal_eval` accetta solo letterali → `ValueError: malformed node`.
    Il fallimento era PLAUSIBILE (il test rosso diceva «i tetti si scavalcano»),
    e letto dal solo nome avrebbe fatto "curare" un Caddyfile che è corretto.
    Qui si accetta il minimo indispensabile e lo si dichiara, invece di usare
    `eval` su un sorgente.
    """
    if isinstance(nodo, ast.Constant) and isinstance(nodo.value, int):
        return nodo.value
    if isinstance(nodo, ast.BinOp) and isinstance(nodo.op, (ast.Mult, ast.Add, ast.Pow)):
        a, b = _intero(nodo.left), _intero(nodo.right)
        return a * b if isinstance(nodo.op, ast.Mult) else (a + b if isinstance(nodo.op, ast.Add) else a ** b)
    raise AssertionError(
        f"MAX_UPLOAD_BYTES è scritto in una forma che questo test non sa leggere "
        f"({ast.dump(nodo)[:60]}…). Non è un difetto del codice: è questo test che "
        f"va esteso — e finché non lo è, NON sta verificando niente."
    )


def _max_upload_bytes() -> int:
    """Legge la costante dal sorgente con `ast` — senza importare il modulo.

    Stessa tecnica di `test_xff_trust_list.py`: il valore non si riscrive qui, o il
    test misurerebbe una copia invece dell'originale.
    """
    albero = ast.parse(_INDEXER.read_text(encoding="utf-8"))
    for nodo in ast.walk(albero):
        if isinstance(nodo, ast.Assign):
            for t in nodo.targets:
                if isinstance(t, ast.Name) and t.id == "MAX_UPLOAD_BYTES":
                    return _intero(nodo.value)
    raise AssertionError(
        "MAX_UPLOAD_BYTES non trovato in archive_indexer.py: è stato spostato o "
        "rinominato, e questo test stava per confrontare il tetto di Caddy con un "
        "valore che non esiste più."
    )


def _caddy_max_size() -> int:
    """Il `max_size` EFFETTIVO del Caddyfile, ignorando i commenti."""
    trovati = []
    for riga in _CADDYFILE.read_text(encoding="utf-8").splitlines():
        nuda = riga.strip()
        # ⚠️ Questa riga è una CINTURA, non la difesa che agisce — misurato con una
        #   mutazione: togliendola i test restano verdi, perché il `re.match` qui
        #   sotto è ANCORATO a inizio riga e un commento comincia per `#`. La tengo
        #   perché se un domani quel `match` diventasse un `search` (o il regex
        #   perdesse l'ancora) sarebbe l'unica cosa fra il parser e un `1KB` letto
        #   da un esempio nei commenti. Ma il merito, oggi, non è suo: dirlo evita
        #   che qualcuno tolga il regex ancorato credendo di essere coperto da qui.
        if nuda.startswith("#"):
            continue
        m = re.match(r"max_size\s+(\S+)", nuda)
        if m:
            trovati.append(_in_byte(m.group(1)))
    assert trovati, (
        "nessuna direttiva `max_size` attiva nel Caddyfile: il tetto assoluto davanti "
        "al gateway è sparito (o è rimasto solo dentro un commento)."
    )
    # Se ce ne fosse più d'una, decide la più bassa: è quella che taglia per prima.
    return min(trovati)


def test_il_tetto_di_caddy_sta_sopra_il_massimo_legittimo():
    upload = _max_upload_bytes()
    caddy = _caddy_max_size()
    assert caddy > upload, (
        f"Caddy taglia a {caddy} byte ma il gateway accetta upload fino a {upload}: "
        f"Caddy diventerebbe il primo decisore e risponderebbe 413 su un upload "
        f"legittimo. Alza `max_size` in ingress/Caddyfile sopra MAX_UPLOAD_BYTES."
    )


def test_il_parser_del_caddyfile_non_legge_i_commenti():
    """La controprova del parser, non della regola.

    Nel Caddyfile `max_size` compare anche dentro i commenti, con valori piccoli
    (`1KB`, dagli esempi della misura). Se il parser li leggesse, il test sopra
    fallirebbe per un motivo inventato — e qualcuno alzerebbe un tetto che non ne
    aveva bisogno.

    📌 Questo test asserisce l'ESITO (nessun valore da commento), non QUALE delle
    due difese lo ottiene: misurato con una mutazione, oggi agisce il regex
    ancorato e non lo `startswith("#")`. Scritto così resta vero anche se un
    domani cambia quale delle due tiene — un test che si legasse al meccanismo
    diventerebbe rosso per una rifattorizzazione innocua.
    """
    testo = _CADDYFILE.read_text(encoding="utf-8")
    nei_commenti = [r for r in testo.splitlines()
                    if r.strip().startswith("#") and "max_size" in r]
    assert nei_commenti, (
        "questo test presuppone che nel Caddyfile ci sia almeno un `max_size` dentro "
        "un commento: se non c'è più, non sta più provando niente e va tolto o rifatto."
    )
    assert _caddy_max_size() > 1024 * 1024, (
        "il parser ha raccolto un valore da un commento (gli esempi usano 1KB)"
    )


def test_i_valori_letti_sono_quelli_attesi_oggi():
    """Ancora al presente: se cambiano, questo test lo dice — e va aggiornato.

    Non duplica la regola (quella è il primo test): documenta lo stato al 09/08/2026,
    così un cambio silenzioso di uno dei due si nota nel diff invece che in produzione.
    """
    assert _max_upload_bytes() == 4 * 1024**3, "MAX_UPLOAD_BYTES non è più 4 GiB"
    assert _caddy_max_size() == 5 * 1000**3, "il max_size del Caddyfile non è più 5GB"
    # Il margine, scritto in chiaro perché è la grandezza che conta e nessuno la
    # calcola a mente: 5·10⁹ − 4·2³⁰ = 705.032.704 byte ≈ 672 MiB. NON 1 GB.
    assert _caddy_max_size() - _max_upload_bytes() == 705_032_704


# ─────────────────────── l'ancora della misura ───────────────────────
# 🔴 RILIEVO DI abdd732a sulla #123, curato qui: `_UNITA` non è una verità di Caddy,
#   è il risultato di UNA misura fatta su UNA immagine — `caddy:2.8-alpine` al digest
#   pinnato in compose.ingress.caddy.yaml. Finché quel digest non cambia la tabella non
#   può invecchiare. Ma i tre test sopra DERIVANO TUTTI da `_UNITA`: se l'immagine cambia
#   e le unità con lei, restano tutti e tre VERDI dichiarando un margine falso.
#   ⭐ *Tre test che condividono la stessa assunzione non sono tre verifiche* [abdd732a].
#
# ⏰ E non è un rischio remoto: `.github/dependabot.yml` ha `package-ecosystem:
#   docker-compose` su `/` — quel digest lo bumpa un giro AUTOMATICO, settimanale.
#   Senza questo test la finestra fra il bump e l'accorgersene è indefinita.
_DIGEST_MISURATO = "sha256:af32e97399febea808609119bb21544d0265c58a02836576e32a2d082c262c17"
_COMPOSE_CADDY = _RADICE / "compose.ingress.caddy.yaml"


def test_le_unita_sono_ancorate_all_immagine_su_cui_le_ho_misurate():
    """Se il digest di Caddy cambia, `_UNITA` torna un'ASSUNZIONE: qui si rompe.

    Non prova che le unità siano giuste — prova che l'oggetto su cui sono state
    misurate è ancora quello. È l'unico dei quattro test che non dipende da `_UNITA`,
    ed è per questo che esiste: rompe la catena di assunzioni condivise.
    """
    testo = _COMPOSE_CADDY.read_text(encoding="utf-8")
    riga = next((r for r in testo.splitlines()
                 if r.strip().startswith("image:") and "caddy" in r), None)
    assert riga, "immagine caddy non trovata in compose.ingress.caddy.yaml"
    assert _DIGEST_MISURATO in riga, (
        "Il digest di caddy è cambiato. `_UNITA` in questo file dice che Caddy usa unità\n"
        "DECIMALI (1KB = 1000): è il risultato di una misura fatta il 09/08 su\n"
        f"{_DIGEST_MISURATO[:23]}…, non una garanzia dell'upstream.\n"
        "\n"
        "  RIFAI LA MISURA prima di aggiornare questa costante:\n"
        "    Caddyfile di prova con `request_body { max_size 1KB }` + `reverse_proxy`\n"
        "    body  990 byte  → atteso 200\n"
        "    body 1010 byte  → atteso 413   (se dà 200, le unità sono diventate binarie)\n"
        "\n"
        "  ⚠️ `respond` NON va bene per la prova: il tetto scatta solo se qualcuno LEGGE\n"
        "     il body, e con `respond` nessuno lo legge → 200 anche oltre il tetto."
    )
