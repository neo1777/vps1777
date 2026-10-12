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
  percorso d'ingest: uno speaker vuoto in uscita è un bug, non un caso. (La issue #279
  che qui era citata come viva è **chiusa dal 06/09**: la riga era vera quando è stata
  scritta il 05/09, oggi manderebbe a cercare un difetto già curato.)

## ⚠️ Cosa sappiamo GIÀ — non serve ridircelo

Questo repo tiene un registro dei rilievi di sicurezza in **`security/findings.yml`**:
81 voci, **69 chiuse**, e le **12 qui sotto non chiuse** (9 parziali, 3 accettate), ognuna con data, motivo e
stato. Sono già state trovate, discusse e classificate: segnalarle di nuovo consuma il
giro senza aggiungere niente.

| ID | stato | cosa resta aperto |
|---|---|---|
| H4 | partial | solo il contatore di fallimenti GLOBALE, scartato per scelta (farebbe l'auto-lockout dell'owner); `forwarded_allow_ips` per profilo è fatto |
| H5 | partial | solo il push off-site dei backup, lasciato all'owner; chiave age fuori dall'host e solo il recipient sulla VPS sono fatti |
| H12 | partial | l'operator resta root-equivalente via il gruppo `docker`; la whitelist sudo è fatta, e un ritorno a `NOPASSWD:ALL` è una regressione |
| H16 | partial | se il PC non ha bcrypt, la password viaggia in chiaro (dentro SSH) invece dell'hash |
| H22 | partial | un'installazione nuova gira per tag finché non fa il primo update: gli installer non verificano i digest |
| H24 | **accepted** | approvazione manuale dei rilasci: con un solo account non sarebbe un confine; la copre la quarantena di 48 ore dell'auto-update (fino al 27/12/2026) |
| H28 | **accepted** | secondo fattore (TOTP o passkey) sul pannello admin |
| H35 | partial | nella CSP della Mini App restano `style-src 'unsafe-inline'` e `frame-ancestors`: chiuderli senza un client Telegram reale romperebbe la Mini App |
| H50 | partial | il gateway esce ancora su Internet con gli ingressi caddy e cloudflared (rete `ingress`); chiuso solo col profilo Tailscale |
| H51 | partial | la finestra cieca fra due giri del check giornaliero; una sonda continua verso Internet si può fare, non è decisa |
| H52 | partial | le voci senza `natura` restano fuori dalla regola «un comportamento si chiude con una prova eseguita»: quante sono lo dice il contatore ◍ di `security/check_findings.py` |
| H56 | **accepted** | seconda metà di H14: nello snapshot pre-update `archive-data` resta in chiaro |

`partial` = curata a metà, e il file dice quale metà. `accepted` = rischio **accettato
consapevolmente**, con la ragione scritta accanto: non è una svista.

**Cosa È utile, invece**: se una di queste è più grave di come l'abbiamo classificata,
o se la metà «curata» di una `partial` non regge alla prova, dillo — quello è un
contributo. E leggi `security/findings.yml` prima di aprire un rilievo: se l'ID c'è
già, il valore sta nel dire *perché la nostra classificazione è sbagliata*, non nel
riscoprire il fatto.

## Conoscenze del repo (per non segnalare il voluto come difetto)

- Gli **errori parlanti** sono un pattern deliberato: un messaggio d'errore qui spiega
  causa e cura, anche a costo di essere lungo. Non suggerire di accorciarli.
- Le **docstring narrative** (con storia, date, «PERCHÉ ESISTE») sono lo stile del
  repo, non verbosità da ripulire.
- I messaggi utente sono in **italiano** per scelta; il codice e gli identificatori in
  inglese.
- `features.yaml` è un **ledger con prova bidirezionale in CI**: ogni `verify` è una
  prova macchina (`path_exists`, `file_contains` con un pattern **regex**, `python_def`,
  `grep_count`, `mcp_tool`…), non una stringa libera. Una voce senza prova verificabile
  è un difetto.
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
