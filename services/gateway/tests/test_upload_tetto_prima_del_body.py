"""Il tetto sull'upload si guarda PRIMA di `request.form()`, o il danno è già fatto.

Gemello di `test_upload_spazio_disco.py`, e nasce dalla sua revisione (voce `2bd05092`,
`71d540e6`, 03/08): **quella guardia è giusta e guarda il posto sbagliato per questo
difetto.**

    la guardia dello spazio    shutil.disk_usage(db_dir)  →  il DISCO, dove va il .db
    dove transita il materiale  request.form() → Starlette spilla il multipart in /tmp
    e /tmp                      compose.yaml:43-52 lo monta come **tmpfs**, e il
                                commento lo dice — SENZA `size:` ⇒ default del
                                kernel: metà della RAM

⇒ Un upload da 4 GB, che `MAX_UPLOAD_BYTES` **ammette**, riempie la tmpfs prima che
`disk_usage` venga mai valutata. *Lo spazio era protetto dove si scrive il risultato,
non dove passa il materiale.*

🛡️ Perché il tetto sul `Content-Length` e non `tmpfs: size=`: quello richiede di sapere
quanta RAM ha la macchina — non misurabile da qui e diverso su ogni VPS. Questo non
dipende né dalla RAM né dalla versione di Starlette.

⚠️ E perché la guardia NON rifiuta quando l'header manca: «non l'ho potuto leggere» non è
«è troppo grande». A valle restano il tetto sul loop di scrittura e la guardia sul disco:
questa è una rete in più sul caso peggiore, non l'unica.

Stile stdlib-only come il resto della suite: la proprietà è **strutturale** — esiste un
controllo, e sta PRIMA della riga che legge il body. Un test funzionale non la
distinguerebbe da un rifiuto che arriva dopo, che è esattamente il difetto.
"""
from __future__ import annotations

from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
SRC = (APP / "admin.py").read_text(encoding="utf-8")


def _solo_codice(testo: str) -> str:
    """Toglie i commenti. Senza, il presidio legge la propria spiegazione.

    Non è teorico: questo file e il codice che verifica NOMINANO entrambi
    `content-length` e `request.form()` nei commenti, per spiegare l'ordine. Un
    controllo che li contasse vedrebbe la spiegazione al posto del meccanismo — è la
    stessa classe colta oggi in `security/confronta-installer.py` e nel presidio degli
    installer, due volte in due file diversi.
    """
    return "\n".join(r for r in testo.splitlines() if not r.lstrip().startswith("#"))


def _funzione(nome: str) -> str:
    """Il corpo di UNA funzione, non tutto il file.

    🔴 PROVATO, e il test è nato rosso per questo: `await request.form()` compare
       **cinque volte** in `admin.py` (righe 154, 393, 480, 648, 818) e la prima sta
       in `_require_admin`, seicento righe prima del punto che qui interessa. Un
       `find()` sul file intero confrontava l'ordine fra due punti di endpoint
       DIVERSI — e dava «il tetto sta dopo il body» su un codice in cui sta prima.
    ⭐ La sonda cercava la prima occorrenza in un file che ne ha molte: è la stessa
       classe della finestra di grep troppo corta e del `403` letto come «zero
       record». **Se l'oggetto è dentro una funzione, la finestra è la funzione.**
    """
    i = CODICE_FILE.find(f"async def {nome}(")
    assert i != -1, f"funzione {nome} non trovata: il test guarda un file che non conosce"
    # fino alla prossima definizione allo stesso livello (o alla fine)
    j = CODICE_FILE.find("\nasync def ", i + 1)
    k = CODICE_FILE.find("\ndef ", i + 1)
    fine = min(x for x in (j, k, len(CODICE_FILE)) if x != -1)
    return CODICE_FILE[i:fine]


CODICE_FILE = _solo_codice(SRC)
CODICE = _funzione("archive_view")


def test_il_controllo_sul_content_length_esiste():
    assert "content-length" in CODICE, (
        "nessuna lettura di Content-Length in admin.py: senza, il body viene "
        "materializzato in tmpfs prima che qualunque tetto possa parlare"
    )


def test_il_controllo_sta_PRIMA_della_riga_che_legge_il_body():
    """La proprietà che conta non è «esiste un tetto»: è DOVE sta.

    Un tetto dopo `await request.form()` non protegge niente — a quel punto Starlette
    ha già scritto il multipart su disco (tmpfs). *È l'ordine, non la presenza.*
    """
    i_tetto = CODICE.find("content-length")
    i_form = CODICE.find("await request.form()")
    assert i_form != -1, "riga `await request.form()` non trovata: il test guarda un file che non conosce"
    assert i_tetto != -1, "controllo su Content-Length assente"
    assert i_tetto < i_form, (
        f"il controllo sul Content-Length sta DOPO `request.form()` (posizioni "
        f"{i_tetto} vs {i_form}): a quel punto il body è già stato materializzato in "
        f"/tmp, che è una tmpfs. Il tetto ci sarebbe e non servirebbe a niente."
    )


def test_un_content_length_ASSENTE_non_e_un_rifiuto():
    """«non l'ho potuto leggere» ≠ «è troppo grande».

    È la stessa distinzione di `libero_mb` nella guardia sul disco (OSError → si
    prosegue) e della PR #76 sull'installer. Qui si verifica che il ramo esista: il
    controllo è dentro un `if` sulla presenza dell'header, non incondizionato.
    """
    i = CODICE.find("content-length")
    finestra = CODICE[i:i + 400]
    assert "is not None" in finestra, (
        "il controllo non distingue l'header ASSENTE: se `Content-Length` manca "
        "(transfer-encoding chunked) rifiuterebbe un upload legittimo, oppure "
        "solleverebbe su un `int(None)`"
    )


def test_un_content_length_ILLEGGIBILE_non_e_un_rifiuto():
    """Un header che non è un numero è un dato che non abbiamo, non un attacco."""
    i = CODICE.find("content-length")
    finestra = CODICE[i:i + 600]
    assert "ValueError" in finestra, (
        "nessun ramo per un Content-Length non numerico: un header malformato farebbe "
        "esplodere l'endpoint invece di essere trattato come «non misurabile»"
    )


def test_il_tetto_non_e_un_numero_nuovo():
    """La soglia deriva da `MAX_UPLOAD_BYTES`, che esiste già.

    Un secondo numero scritto a mano diverge dal primo al primo cambio, e diverge in
    silenzio: nessuno confronta due costanti che vivono in due file.
    """
    i = CODICE.find("content-length")
    finestra = CODICE[i:i + 800]
    assert "MAX_UPLOAD_BYTES" in finestra, (
        "il tetto non deriva da MAX_UPLOAD_BYTES: è un numero nuovo, e diverge dal "
        "tetto vero appena uno dei due cambia"
    )


def test_polarita_il_controllo_dell_ordine_sa_dire_di_NO():
    """Senza questa, «passa» e «non ha guardato niente» sono lo stesso risultato.

    Si costruisce il caso opposto — il tetto DOPO il body — e si verifica che il
    confronto lo bocci. È la polarità sul caso VERO: non una stringa che non esiste
    da nessuna parte, ma l'ordine sbagliato, che è ciò che può davvero succedere.
    """
    finto = "await request.form()\nx = headers.get('content-length')\n"
    i_tetto = finto.find("content-length")
    i_form = finto.find("await request.form()")
    assert not (i_tetto < i_form), (
        "su un sorgente in cui il tetto viene DOPO il body, il confronto lo dà per "
        "buono: non sta misurando l'ordine"
    )
