# RIGHE.md — le righe del contratto 1777 in questo repo

> 🇬🇧 English: [RIGHE.md](RIGHE.md). Questo file è il sorgente italiano;
> l'inglese è la sua traduzione, e `mise run check` è rosso se resta indietro.

La tabella delle righe del template (DD-P8.1). Ogni riga dice a che tipi si applica (C1), che
grado ha e fin dove arriva (C2), se il suo controllo è stato visto rosso (C3), se l'ha decisa
un fatto o un valore (C4), il ciclo solo dove c'è (C5, AP.2), la via d'uscita (C6), il gemello
(C7), la fonte con la data (C8), e a chi serve con il test che la tiene viva (C10).
Le sigle (Ka.1, DD-P8.3, F.9…) le spiega `tools/1777/GLOSSARIO.it.md`: sono le decisioni
del template da cui viene ogni riga.

**C3 è derivata, mai scritta a mano (AP.1).** Nella tabella, per un controllo, la cella dice solo
«derivata: <id>»: il «sì» o il «no» li scrive `tools/1777/prova-controlli.sh` nel blocco in fondo,
con **dove** è stato visto (in locale, o «CI run <id>» in GitHub Actions) e **quando**.
Per le macchine: `tools/1777/visto-rosso.tsv` (pigro: lo scrive la prova, anche come artefatto del job).
Un run di CI si porta qui con `gh run download <id> -n visto-rosso` e `bash tools/1777/prova-controlli.sh --c3-da <file>`.
Per una promessa C3 non si applica. Finché un controllo non è visto rosso sul suo guasto
costruito, si chiama **controllo proposto** (AP.5).

Il triage (C9) è il cancello d'ingresso, non una colonna (AP.3): le righe scartate stanno
in fondo, col motivo.

Legenda di C2: **promessa** (la tiene chi lavora) · **segnale** (un controllo lo dice, non
ferma) · **blocco scavalcabile** (ferma, ma si passa con un gesto dichiarato) · **blocco**.
Raggio: commit locale · merge (CI) · release · agente.

| riga | cosa | C1 tipi | C2 grado · raggio | C3 visto rosso | C4 | C5 ciclo | C6 via d'uscita | C7 gemello | C8 fonte · data | C10 attore · test |
|---|---|---|---|---|---|---|---|---|---|---|
| Ka.1 | i 7 comandi (setup, dev, test, lint, build, check, release); AGENTS.md nomina `check` e `mise tasks ls --json`, non i 7 | repo, tutti gli stack | segnale · merge | derivata: `comandi` | fatto (i nomi); valore (mise, M.1) | — | M.1: si passa a just + mise per la toolchain | Scripts to Rule Them All, target GNU | DD-P8.8, 28/09/2026 | un agente che arriva trova i comandi senza chiedere · conformita [comandi] |
| Ka.4, Ka.11 | ogni task ha una description di una riga, che dice anche cosa NON è | repo | segnale · merge | derivata: `descrizione` | fatto | — | se una description diventa un paragrafo, si accorcia; non si toglie | `mise tasks ls` (la colonna c'è già) | DD-P8.8, 28/09/2026 | chi legge `mise tasks ls` capisce senza aprire il file · conformita [descrizione] |
| DD-P8.9 (1, 3) | i comandi nominati in AGENTS.md, e i file nominati fra backtick in AGENTS.md, in questo file e nel glossario, esistono secondo una fonte indipendente; o sono dichiarati «pigri» | repo | segnale · merge | derivata: `file-nominati` | fatto | — | se un nome è ambiguo, si toglie il backtick, non il controllo | nessuno cercato | DD-P8.9, 27/09/2026 | un agente non insegue un file che non c'è · conformita [file] |
| DD-P8.9 (4) | fail-loud: se manca uno strumento il controllo lo dice ed esce 2, mai verde | repo | segnale · merge | derivata: `fail-loud` | fatto | — | — | il «NON MISURATO» di vps1777 | DD-P8.9, 27/09/2026 | chi legge un verde sa che è stato misurato · conformita senza mise → 2 |
| DD-P8.9 (2) | ogni controllo di questa tabella ha la sua prova in `tools/1777/prova-controlli.sh` | repo | segnale · merge | derivata: `prova` | fatto | ad ogni controllo nuovo · checkpoint: `check` · brief: la riga qui | — | prova-controlli delle skill 1777 | DD-P8.9, AP.1, AP.5, 27-28/09/2026 | chi aggiunge un controllo non lo lascia decorativo · conformita [prova] |
| DD-P8.3 | AGENTS.md unico; CLAUDE.md solo con `@AGENTS.md` | repo | segnale · merge | derivata: `claude-import` | fatto (Claude Code non legge AGENTS.md se c'è un CLAUDE.md) | — | il link simbolico, se regge con copier, git e ogni macchina | spec AGENTS.md | DD-P8.3, 27/09/2026 | Claude Code legge le stesse regole degli altri agenti · conformita [claude-import] |
| Ka.3 | `setup` è idempotente: due volte di fila, la seconda esce 0 e non cambia file tracciati | repo | segnale · merge (job prova-controlli) | derivata: `setup-idempotente` | fatto | dopo ogni pull · checkpoint: la prova | — | script/setup di Scripts to Rule Them All | DD-P8.8, 28/09/2026 | chi fa pull rilancia setup senza paura · prova-controlli |
| Kc.2, Kc.5 | `setup` chiama `tools/hooks/installa.sh` (il filo) | repo | segnale · merge | derivata: `filo` | fatto | — | — | `prepare` di Husky (l'altro filo) | DD-P8.8, 28/09/2026; T4 | l'hook si installa dentro un gesto che si fa già · conformita [filo] |
| Kc.1-Kc.4 | l'hook nella cartella comune: sporco fermato, pulito passa, worktree coperto; fail-loud; chiama i comandi del contratto; niente test completo | repo | blocco scavalcabile · commit locale (chi scavalca: chiunque, con `--no-verify`) + segnale · merge (job prova-controlli, a tre tempi su clone fresco) | derivata: `hook` | fatto (misurato da T4) | — | se il filo si perde ancora, Husky `prepare` nei TS (Kc.3) | Husky, lefthook, prek; il modello di vps1777 | DD-P8.8, 28/09/2026; T4 27/09/2026 | chi committa vede il rosso prima del push · prova-controlli [hook] |
| Ka.5, K-a | la versione di mise fissata: `min_version`, le action per sha (mise-action con `version`, checkout, upload-artifact), e `mise.lock` che fissa ogni strumento di `[tools]`; gli step `run:` di check.yml sono solo comandi del contratto (niente apt: uno strumento di sistema sta in `[tools]`); il runner fissato (`runs-on`, mai `-latest`, F2.4) | repo | segnale · merge | derivata: `ci-mise` | fatto (T3: 9 rotture dichiarate in 6 mesi) | aggiornamento a lotti (DD-P8.6) | M.1 | mise-action `version` + `sha256` | DD-P8.8, 28/09/2026; T3 27/09/2026; F2.4 29/09/2026 | una release di mise o una nuova immagine del runner non rompono la CI da sole · conformita [ci] |
| F.4, F2.4 | python non è in `[tools]` (il retrofit); il python di uv è fissato da `UV_PYTHON` in `[env]` (o da `.python-version`), senza toccare il PATH | repo Python | segnale · merge | derivata: `ci-mise` | fatto (senza, uv usa il python del runner, che cambia con l'immagine) | aggiornamento a lotti | — | `.python-version` di uv | F.4, F2.4, 29/09/2026 | CI e locale giudicano con lo stesso python · conformita [ci] |
| K-b, Kb.1 | `test` con un filtro che non trova niente esce ≠0 | repo | segnale · merge | derivata: `filtro-vuoto` | fatto (pytest 5, Dart 79; vitest con l'involucro) | — | — | pytest `-k` (5 da solo) | DD-P8.8, 28/09/2026 | un verde senza test non passa · prova-controlli |
| Kb.2 | nessun file di test senza asserzioni; un Dart con solo `expectLater` non è rosso | repo | segnale · merge | derivata: `asserzioni` | fatto; è un pavimento, non una prova | — | — | [mai cercato] | DD-P8.8, Pr.4, 28/09/2026 | chi legge un test sa che guarda qualcosa · asserzioni.py |
| Ka.10 | i segreti, per forma e su più righe: `define` di `*_KEY`, `loadEnv(…, '')`, `import.meta.env.VITE_*KEY`, `--dart-define` con `*_KEY`, `.env` come asset o in git; stampa file, riga, regola, mai il valore | repo | segnale · merge + blocco scavalcabile · commit locale | derivata: `segreti-forma` | fatto (T7: la regola di riga manca AI Studio) | — | — | gitleaks, trufflehog (valori); security-vite (forma, su una riga) | DD-P8.8, 28/09/2026; T7 27/09/2026 | una chiave non arriva al client · segreti.sh |
| Ka.8 (idea) | le righe del contratto nei file condivisi: `.env` ignorato da git | repo | segnale · merge | derivata: `gitignore-env` | fatto | — | — | l'anti-tamper di projen | T7 27/09/2026; Ka.8 non decisa | `.env` non entra in git per sbaglio · conformita [gitignore] |
| F.9 | il repo non dice da quale cartella di casa è nato: `_src_path` in `.copier-answers.yml` è il remote del template | repo | segnale · merge (rosso se il repo è pubblico; nota se è privato) | derivata: `src-path` | fatto (nessun controllo del primo repo provato lo fermava) | — | redigere a mano prima del primo commit, sapendo che `copier update` si spegne | — | F.9, 29/09/2026 | un percorso personale non esce su un repo pubblico · conformita [src-path] |
| F.3 | ogni task si lascia leggere da mise (che passa ogni `run` per Tera); la logica sta in uno script, un `run` è una riga che chiama | repo | segnale · merge | derivata: `tera` | fatto (un `${#…}` nella run di lint ha spento `check`; `mise tasks ls` e `mise tasks validate` restano verdi, lo dice solo `mise run --dry-run`, misurato il 29/09) | — | — | — | F.3, 29/09/2026 | chi aggiunge un comando non spegne `check` · conformita [tera] |
| K5 | lingua: italiano sempre, sorgente; inglese anche, se il repo è pubblico (it,en): i due file ci sono, si rimandano, hanno la stessa forma, e l'impronta del sorgente è quella registrata in `tools/1777/traduzioni.json` | repo | segnale · merge | derivata: `lingua` | valore (scelta del proprietario, 27/09/2026) | a ogni modifica dell'italiano · checkpoint: `check` | — | vps1777 (docs/en/MANIFEST.json) | DD-P8.7, 27/09/2026; F2.3, 29/09/2026 | chi contribuisce da fuori legge un inglese che non è rimasto indietro · conformita [lingua] |
| F2.3 | ogni sigla di questi documenti è spiegata nel glossario | repo | segnale · merge | derivata: `glossario` | fatto (una prova sul campo ne ha contate più di cento, che fuori non si risolvevano) | — | se una sigla serve una volta sola, si scrive la cosa per esteso | — | F2.3, 29/09/2026 | chi arriva da fuori legge le fonti delle regole · conformita [glossario] |
| R.1 | ogni rito che rileva deposita in `RILIEVI.ndjson`; `check` conta gli aperti da più di 14 giorni, col denominatore e la data | repo, tutti i riti | segnale (il conto) · promessa con rito (il deposito, dove non c'è uno script) | derivata: `rilievi` | valore (una nota del proprietario su DD-P8.2); il 14 non è misurato | trigger: un rito che rileva · checkpoint: `check` · deposito: `RILIEVI.ndjson` (pigro: nasce al primo deposito) | se la coda cresce più di quanto si svuota, si alza la soglia di cosa è un rilievo; se al primo mese più di metà supera i 14 giorni, il 14 si misura | un registro degli aperti in un altro repo (interno) | R.1, 28/09/2026 | un rilievo non resta nel verbale di un giorno · rilievi.py conta |
| M.1 | mise per toolchain e comandi | repo | promessa | non si applica (promessa) | valore (scelta del proprietario, 28/09/2026) | aggiornamento a lotti | 2 rotture di uno dei 7 comandi in 2 repo entro 6 mesi, a versione fissata; o contributori che rifiutano mise → just + mise per la toolchain | just, Task, make (T3) | M.1, 28/09/2026 | — · la prova differenziale (stesso commit, mise vecchio e nuovo) |
| D1 | copier senza `_tasks`, `_migrations`, `_jinja_extensions` | template | promessa (verificata dalla prova del template) | non si applica (promessa) | fatto (chiedono `--trust`; Renovate gratuito non li esegue) | — | — | copier-uv | DD-P8.6, 27/09/2026 | un aggiornamento non esegue codice del template · prova-template.sh (sta nel template e non in questo repo: per questo senza backtick) |
| Ka.6 | gli scheletri per stack | — | **segnaposto: non ancora deciso** | non si applica | valore | — | — | T1 | DD-P8.8: non decisa | — |
| Ka.8 | il retrofit, il passo d'adozione | — | **segnaposto: non ancora deciso** (qui c'è solo il minimo: `_skip_if_exists`, e le risposte `hook_propri`, `hook_marcatore`, `setup_crea_env`, `scheletro`, `python_da_mise`, `python_uv`) | non si applica | valore | — | — | projen, nx init, copier `_skip_if_exists` | DD-P8.8: non decisa | — |

## Scartate al triage (AP.3), col motivo
- `mise generate git-pre-commit`: ha cambiato comportamento il 20/09/2026 (Kc.5, T3).
- Husky come installatore: assorbito da `prepare` → `tools/hooks/installa.sh` (Kc.3); non copre i worktree nuovi (T4).
- `core.hooksPath` relativo: lascia senza hook i worktree che non hanno `tools/hooks/` (Kc.2).
- Il controllo «l'hook c'è» su un clone senza setup: è rosso sempre, quindi spento (T4); lo sostituisce la prova a tre tempi.

## C3 · visto rosso
«dove, quando»: «locale» se la prova è girata su una macchina, «CI run <id>» se è girata in GitHub Actions.

<!-- C3:inizio — scritto da tools/1777/prova-controlli.sh, non a mano (AP.1) -->
Nessuna prova ancora: tutti i controlli sono **proposti** (AP.5). Lancia `bash tools/1777/prova-controlli.sh`.
<!-- C3:fine -->
