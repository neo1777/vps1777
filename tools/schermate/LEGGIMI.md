# Le schermate del README

Le immagini in `docs/img/` sono schermate **vere del prodotto, con dati inventati**: nessun
indirizzo, nome o notebook di qualcuno. Si rifanno così, da un PC con Docker non necessario:

```bash
bash tools/schermate/avvia.sh /tmp/schermate            # gateway, installatore e un nb1777-mcp FINTO, in locale
CHROME=$(command -v google-chrome) uv run --python 3.12 --with playwright python tools/schermate/scatta.py /tmp/schermate
# le immagini escono in /tmp/schermate/scatti/: si riducono e si copiano in docs/img/
```

- `avvia.sh` lancia il gateway col suo codice (`python -m app`) e segreti di prova scritti lì dentro, in
  chiaro: valgono solo per quella istanza locale, che muore a fine lavoro. Il pannello è mostrato come
  appare dietro HTTPS (`GATEWAY_PUBLIC_BASE` di esempio).
- `finto_upstream.py` risponde al posto di nb1777-mcp con cinque notebook inventati.
- `scatta.py` guida un Chrome senza finestra: il modulo dell'installatore compilato, la scheda Update
  del pannello, la scheda Notebook della Mini App (con l'SDK di Telegram sostituito e un accesso
  firmato con la chiave di prova), e l'immagine di anteprima dei link da `anteprima.html`.

**Quando rifarle.** `docs/img/schermate.json` registra la versione e l'impronta di `installer/ui.html`
al momento dello scatto. `tools/tests/test_schermate_del_readme.py` diventa rosso se l'installatore
cambia o se la versione sale di un gradino (0.98 → 0.99): o si rifanno, o si conferma che valgono
ancora aggiornando quel file.

L'immagine `anteprima-social.png` (1280×640) non è usata dal README: è quella da caricare in
GitHub → Settings → Social preview.
