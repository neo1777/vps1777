# AGENTS.md — vps1777

> 🇬🇧 English: [AGENTS.md](AGENTS.md). Questo file è il sorgente italiano;
> l'inglese è la sua traduzione, e `mise run check` è rosso se resta indietro.

Il server self-hosted 1777: gateway, archivio, notebook e bot su una VPS

Questo file è per gli agenti che lavorano su una copia del repo. È corto apposta: dice il
perché delle scelte, le guardie e le trappole, e rimanda a dove stanno le cose (DD-P8.3).
Lo stato del lavoro non sta qui.

## Cosa leggere
- I comandi non sono elencati qui: `mise tasks ls --json` li dà con la loro descrizione, e
  `mise tasks info test --json` dice l'argomento `filtro` dei test. La fonte è `mise.toml`.
- Le regole del contratto 1777, col loro grado e il «visto rosso», stanno in `RIGHE.it.md`.
  Qui si nominano, non si ricopiano.
- Le sigle fra parentesi (Ka.10, AP.5…) dicono da quale decisione del template viene una
  regola: le spiega `tools/1777/GLOSSARIO.it.md`.

## Vincoli
- **Prima di dire «fatto»: `mise run check`.** Verde, o non è fatto. È quello che fa la CI.
- Dopo un clone o un pull: `mise run setup`. È idempotente e installa anche l'hook di git:
  senza, i controlli locali non girano, e nessuno te lo dice.
- `mise run setup` prepara questa copia di lavoro: **non** è il deploy
  e **non** crea `.env`. Se il repo ha anche uno script setup.sh, quello è un altro gesto e non si
  confonde con questo.
- L'hook si scavalca con `git commit --no-verify` solo sapendo perché: la CI ripete tutto.
- Nessuna chiave nel codice che va al client (Ka.10). `tools/1777/segreti.sh` guarda la forma e
  stampa file, riga e regola, mai il valore.
- Un controllo nuovo nasce col suo guasto costruito in `tools/1777/prova-controlli.sh`. Finché
  non è visto rosso si chiama «controllo proposto» (AP.5).
- Un rito che trova qualcosa lo deposita: `python3 tools/1777/rilievi.py deposita --rito … --cosa … --responsabile …`
  (R.1). Il registro è `RILIEVI.ndjson` (pigro: nasce al primo deposito).
- **In `mise.toml` un `run` è una riga che chiama.** mise passa ogni `run` per Tera, e un
  `${#…}` di bash rompe quel task e chi ne dipende (`check` non parte; conformità [tera] lo dice).
  La logica va in uno script in `tools/`; se proprio serve bash inline, fra `{% raw %}` e `{% endraw %}`.
- Uno strumento di sistema che serve ai comandi (per esempio `age` per i test) va in `[tools]` di
  `mise.toml`, fissato, poi `mise lock`: **mai** uno step apt in CI, o la CI diverge dal locale.
  Anche il runner della CI è fissato (`runs-on`, mai `-latest`).
- python non è in `[tools]`: `python3` resta quello di sistema. Il python di uv (`uv sync`,
  `uv run`, `uvx`) è fissato da `UV_PYTHON` in `[env]` di `mise.toml`, senza toccare il PATH.
- Lingua (K5): di questo file, di `RIGHE.it.md` e del glossario l'italiano è il sorgente e
  l'inglese la traduzione. Chi cambia l'italiano aggiorna anche l'inglese, poi
  `python3 tools/1777/lingue.py registra`: finché la traduzione è indietro, `check` è rosso.
  Issue e PR verso fuori in inglese.

## Scelte già prese
- **mise** per toolchain e comandi, versione fissata in tre posti: una rottura non ci tocca
  finché non alziamo noi la versione, a lotti (M.1, Ka.5).
- **L'hook nella cartella comune di git**, mai `core.hooksPath` relativo: quello lascia senza
  hook, in silenzio, i worktree nuovi (Kc.2).
- **copier senza `_tasks`**: quello che un task farebbe lo fa `mise run setup`, a mano (D1).
- **Il test esce ≠0 se il filtro non trova niente**: un verde senza test non è un verde (K-b).

## Dove sta cosa
- i comandi: `mise.toml` · i controlli del contratto 1777, tutti in una cartella: `tools/1777/` · l'hook: `tools/hooks/`
- le righe del contratto e C3: `RIGHE.it.md`; C3 per le macchine: `tools/1777/visto-rosso.tsv` (pigro: lo scrive `tools/1777/prova-controlli.sh`)
- le sigle: `tools/1777/GLOSSARIO.it.md` · le impronte delle traduzioni: `tools/1777/traduzioni.json`
- da quale versione del template è nato il repo: `.copier-answers.yml` (si aggiorna con `copier update`, a lotti, DD-P8.6)
- il tracker: le issue del repo, coda unica per la deriva; le etichette nascono quando servono (pigro)
