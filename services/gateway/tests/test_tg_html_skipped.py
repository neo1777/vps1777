"""L'estrattore HTML di Telegram deve DICHIARARE quello che scarta.

Era l'unico dei tre estrattori di `archive_indexer.py` a non emettere nemmeno uno
`_Skip`: `claude-code` ne emette quattro tipi, `claude-conversations` tre,
`bundle-workfiles` cinque. Qui un `div.message` senza `id` — markup cambiato, export
parziale, frammento troncato — **portava via con sé il testo, e nessuno lo contava**.

Perché conta, e non è pignoleria: `tools/collaudo-quadratura.py` esiste per quadrare
l'ingest, e dichiara a chiare lettere che *«dal solo DB non si distingue un DOPPIONE
COLLASSATO da un MESSAGGIO PERSO»*. Un drop non contabilizzato è esattamente ciò che
rende cieco quel confronto: i conti tornano perché il messaggio non è mai esistito.
"""
from __future__ import annotations

import sqlite3
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import archive_indexer  # noqa: E402

# Un export con un messaggio buono, uno SENZA id (il caso che spariva) e uno con id
# ma senza testo (sticker: scarto legittimo, e va contato lo stesso).
_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"></head><body>
<div class="page_wrap">
 <div class="page_header"><div class="content"><div class="text bold">
Chat Di Prova
 </div></div></div>
 <div class="history">
  <div class="message default clearfix" id="message-10">
   <div class="body">
    <div class="pull_right date details" title="02.03.2024 13:10:36 UTC+01:00">13:10</div>
    <div class="from_name">
Neo1777
    </div>
    <div class="text">
questo entra
    </div>
   </div>
  </div>
  <div class="message default clearfix">
   <div class="body">
    <div class="pull_right date details" title="02.03.2024 13:11:00 UTC+01:00">13:11</div>
    <div class="from_name">
Ema
    </div>
    <div class="text">
SEGRETO questo NON ha id e prima spariva
    </div>
   </div>
  </div>
  <div class="message default clearfix" id="message-12">
   <div class="body">
    <div class="pull_right date details" title="02.03.2024 13:12:00 UTC+01:00">13:12</div>
    <div class="from_name">
Ema
    </div>
    <div class="media_wrap clearfix"><a class="sticker_wrap" href="stickers/s.webp">s</a></div>
   </div>
  </div>
 </div>
</div></body></html>"""


def _indicizza(tmp_path: Path) -> Path:
    zp = tmp_path / "ChatExport.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("ChatExport_2026-08-03/messages.html", _HTML)
    db = tmp_path / "out.db"
    archive_indexer.index_file(str(zp), str(db))
    return db


def _skipped(db: Path) -> list[tuple]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return conn.execute(
            "SELECT source, reason, detail, ts FROM skipped ORDER BY reason").fetchall()
    finally:
        conn.close()


def test_il_messaggio_senza_id_lascia_una_lapide(tmp_path):
    """Il caso del rilievo: prima non entrava in `messages` E non compariva da
    nessun'altra parte."""
    righe = [r for r in _skipped(_indicizza(tmp_path)) if r[1] == "no-msg-id"]
    assert len(righe) == 1, _skipped(_indicizza(tmp_path))
    assert righe[0][0] == "telegram-html"
    assert righe[0][3] == "2024-03-02T13:11:00+01:00", "il ts serve a ritrovarlo nell'export"


def test_anche_lo_scarto_legittimo_si_conta(tmp_path):
    """Sticker e service message: previsti dal docstring della classe. Contarli
    costa nulla e rende il totale quadrabile — è ciò che fanno gli altri due."""
    righe = [r for r in _skipped(_indicizza(tmp_path)) if r[1] == "empty"]
    assert len(righe) == 1
    assert righe[0][0] == "telegram-html"


def test_il_dettaglio_non_porta_il_TESTO_del_messaggio(tmp_path):
    """Scelta deliberata, diversa dagli altri estrattori (che salvano `str(d)[:200]`):
    la tabella `skipped` serve a QUADRARE, e per quello bastano la forma e il ts.
    Copiare il testo di un messaggio personale in una seconda tabella non aggiunge
    niente alla quadratura e allarga ciò che il DB contiene."""
    for _, _, detail, _ in _skipped(_indicizza(tmp_path)):
        assert "SEGRETO" not in detail
        assert "spariva" not in detail
        assert "len=" in detail, detail


def test_i_messaggi_buoni_entrano_ancora(tmp_path):
    """Controprova di polarità: una guardia che scarta anche il legittimo è peggio
    del difetto che cura."""
    db = _indicizza(tmp_path)
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        righe = conn.execute("SELECT content FROM messages").fetchall()
    finally:
        conn.close()
    assert len(righe) == 1
    assert righe[0][0] == "[Neo1777] questo entra"


def test_il_conto_quadra(tmp_path):
    """La proprietà che il rilievo chiedeva: entrati + scartati = quelli che c'erano.
    Prima il terzo messaggio non compariva in nessuno dei due addendi."""
    db = _indicizza(tmp_path)
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        entrati = conn.execute("SELECT count(*) FROM messages").fetchone()[0]
        scartati = conn.execute(
            "SELECT count(*) FROM skipped WHERE source='telegram-html'").fetchone()[0]
    finally:
        conn.close()
    assert entrati + scartati == 3, f"entrati={entrati} scartati={scartati}, nell'export erano 3"


def test_reindicizzare_non_duplica_le_lapidi(tmp_path):
    """Le lapidi hanno una chiave: due passate sullo stesso export non le raddoppiano
    (stessa garanzia che `test_skipped_ledger` chiede agli altri estrattori)."""
    zp = tmp_path / "ChatExport.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("ChatExport_2026-08-03/messages.html", _HTML)
    db = tmp_path / "out.db"
    archive_indexer.index_file(str(zp), str(db))
    prima = len(_skipped(db))
    archive_indexer.index_file(str(zp), str(db))
    assert len(_skipped(db)) == prima


# ───────── il collasso degli uid: rilievo di b82df434 sulla #77 ─────────
#
# `_uid` impasta (source, reason, detail, ts) e `flush_skips` fa INSERT OR IGNORE.
# Se due scarti diversi producono lo stesso uid, il secondo NON entra — e la
# tabella che serve a quadrare porta un numero più piccolo del vero. È lo stesso
# difetto che questa PR cura, spostato di una tabella: e peggiore, perché un
# conteggio che sembra una misura tranquillizza chi quadra.

_ALBUM = """<!DOCTYPE html>
<html><head><meta charset="utf-8"></head><body>
<div class="page_wrap">
 <div class="page_header"><div class="content"><div class="text bold">
Album
 </div></div></div>
 <div class="history">
  <div class="message default clearfix" id="message-19">
   <div class="body">
    <div class="pull_right date details" title="02.03.2024 13:09:00 UTC+01:00">13:09</div>
    <div class="from_name">
Ema
    </div>
    <div class="text">
ecco l'album
    </div>
   </div>
  </div>
  <div class="message default clearfix" id="message-20">
   <div class="body">
    <div class="pull_right date details" title="02.03.2024 13:10:00 UTC+01:00">13:10</div>
    <div class="from_name">
Ema
    </div>
    <div class="media_wrap clearfix"><a class="photo_wrap" href="photos/1.jpg">a</a></div>
   </div>
  </div>
  <div class="message default clearfix" id="message-21">
   <div class="body">
    <div class="pull_right date details" title="02.03.2024 13:10:00 UTC+01:00">13:10</div>
    <div class="from_name">
Ema
    </div>
    <div class="media_wrap clearfix"><a class="photo_wrap" href="photos/2.jpg">b</a></div>
   </div>
  </div>
  <div class="message default clearfix">
   <div class="body">
    <div class="from_name">
Ema
    </div>
    <div class="text">
perso uno, senza data
    </div>
   </div>
  </div>
  <div class="message default clearfix">
   <div class="body">
    <div class="from_name">
Ema
    </div>
    <div class="text">
perso due, senza data
    </div>
   </div>
  </div>
 </div>
</div></body></html>"""


def _indicizza_html(tmp_path: Path, html: str) -> Path:
    zp = tmp_path / "Album.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("ChatExport_2026-08-03/messages.html", html)
    db = tmp_path / "album.db"
    archive_indexer.index_file(str(zp), str(db))
    return db


def test_due_media_nello_stesso_secondo_NON_collassano(tmp_path):
    """Un album di foto ha per costruzione lo stesso mittente e lo stesso secondo,
    e nel ramo `empty` la lunghezza del testo è sempre 0: senza l'id nel dettaglio
    le quattro parti dell'uid sarebbero identiche e resterebbe UNA riga."""
    righe = [r for r in _skipped(_indicizza_html(tmp_path, _ALBUM)) if r[1] == "empty"]
    assert len(righe) == 2, righe


def test_due_messaggi_persi_SENZA_data_NON_collassano(tmp_path):
    """Il caso peggiore: nel ramo `no-msg-id` l'id non c'è per definizione, e se
    manca anche il `ts` restano solo source/reason/len — uguali per costruzione."""
    righe = [r for r in _skipped(_indicizza_html(tmp_path, _ALBUM)) if r[1] == "no-msg-id"]
    assert len(righe) == 2, righe


def test_il_discriminante_e_STABILE_fra_re_ingest(tmp_path):
    """⚠️ La cura del collasso non deve diventare il difetto opposto: se il
    discriminante cambiasse a ogni passata, `INSERT OR IGNORE` smetterebbe di fare
    da ledger e ogni ricarica gonfierebbe la tabella — altrettanto silenzioso."""
    zp = tmp_path / "Album.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("ChatExport_2026-08-03/messages.html", _ALBUM)
    db = tmp_path / "album.db"
    archive_indexer.index_file(str(zp), str(db))
    prima = _skipped(db)
    archive_indexer.index_file(str(zp), str(db))
    assert _skipped(db) == prima, "il re-ingest ha cambiato o duplicato le lapidi"


def test_il_dettaglio_dei_media_non_porta_contenuto(tmp_path):
    """`id=` e `n=` sono identificatori, non contenuto: la scelta di `_forma()` —
    niente testo personale nella seconda tabella — resta intatta anche curando il
    collasso."""
    for _, _, detail, _ in _skipped(_indicizza_html(tmp_path, _ALBUM)):
        assert "perso" not in detail and "album" not in detail, detail
        assert "len=" in detail
