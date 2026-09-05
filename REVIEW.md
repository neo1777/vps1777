# REVIEW.md — istruzioni per la code review di vps1777

Queste regole guidano `/code-review` (la review locale di Claude Code) su questo repo.
Non descrivono il progetto — per quello c'è il README — ma dicono al revisore **cosa
pesa qui** e cosa è rumore.

## Cosa merita «Important»

Riserva la severità alta per ciò che in questo repo fa danni veri:

- **Errori silenziosi**: eccezioni ingoiate, `or []`/default che trasformano un errore
  in uno zero plausibile, exit code ignorati, scritture non verificate. È la classe di
  difetto più costosa della storia di questo repo: uno «0» che sembra un risultato.
- **Perdita o corruzione di dati**: ingest/re-ingest dell'archivio (dedup per uuid),
  backup/restore, migrazioni, scritture su volumi condivisi.
- **Sicurezza**: secret in chiaro o loggati, authz mancante su endpoint del gateway,
  path traversal su file passati dai tool MCP, injection (SQL/FTS5/shell), indebolimento
  dell'hardening esistente (cap_drop, tmpfs, ProtectSystem, no-new-privileges).
- **Contratto MCP**: cambi che rompono la forma delle risposte dei tool (`search`,
  `count`, `canonico`, `studio_*`) o il loro comportamento dichiarato nelle docstring.
- **Colonne derivate dell'archivio**: `speaker`/`voice` devono uscire POPOLATE da ogni
  percorso d'ingest (issue #279): uno speaker vuoto in uscita è un bug, non un caso.

## Conoscenze del repo (per non segnalare il voluto come difetto)

- Gli **errori parlanti** sono un pattern deliberato: un messaggio d'errore qui spiega
  causa e cura, anche a costo di essere lungo. Non suggerire di accorciarli.
- Le **docstring narrative** (con storia, date, «PERCHÉ ESISTE») sono lo stile del
  repo, non verbosità da ripulire.
- I messaggi utente sono in **italiano** per scelta; il codice e gli identificatori in
  inglese.
- `features.yaml` è un **ledger con prova bidirezionale in CI**: i campi `verify` sono
  **regex**, non stringhe libere. Una voce senza prova verificabile è un difetto.
- Nei testi destinati a GitHub, «Chiude #N» in italiano NON chiude la issue: la parola
  che GitHub legge è `Closes`. Segnalalo se lo trovi in template o script.
- L'update di produzione passa SOLO dalla unit systemd dedicata, mai da root nudo:
  qualunque suggerimento di «basta lanciare X da root» è un difetto, non una semplificazione.
- Dentro i container `cap_drop: ALL` nega CAP_CHOWN anche a root: le riparazioni di
  ownership si fanno dal host sul mountpoint. Non proporre chown in-container.

## Cosa saltare

- `docs/en/` — traduzioni generate, allineate da `tools/aggiorna-traduzioni.py`.
- `releases/`, `backups/`, `var/`, `images.lock`, `uv.lock` (per i lock esiste
  `tools/lock-salti.py`).
- Lo stile dei commenti e la lunghezza delle funzioni negli script di `tools/`:
  sono strumenti operativi, la leggibilità narrativa lì è un valore.

## Tetti e forma

- Massimo **5 nit** per review: se ce ne sono di più, tieni i 5 che insegnano di più.
- Ogni finding con `file:riga` e uno scenario concreto di fallimento (input → effetto),
  non un'opinione. Se non sai costruire lo scenario, declassalo a nit.
- Se un difetto ha un test facile, proponi il test insieme alla cura: qui ogni cura
  viaggia con la sua prova.
