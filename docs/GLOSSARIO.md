# Glossario — le parole di vps1777, in ordine di apparizione

> Per chi arriva ora: le altre pagine usano queste parole senza rispiegarle.
> Qui ognuna ha due righe. Le convenzioni di scrittura sono in fondo.

## La macchina

- **VPS** — il server (tuo o in affitto) su cui vps1777 gira.
- **Container** — una "scatola" isolata in cui gira un servizio (Docker). vps1777
  ne usa sei: gateway, archive-mcp, nb1777-mcp, nb1777-bot, ocr, backup.
- **Immagine** — il contenuto pronto e versionato di un container: aggiornare
  vuol dire sostituire l'immagine, non modificare la scatola.
- **Volume** — il disco dati di un container: sopravvive quando il container
  viene ricreato. Qui vivono i DB dell'archivio, i cookie NotebookLM, gli strati
  della memoria.
- **Compose** (`compose*.yaml`) — il file che dichiara quali container esistono,
  con quali volumi e reti.
- **healthy** — il container risponde al proprio controllo di salute; `docker ps`
  lo mostra accanto allo stato.
- **Unit systemd** — un servizio del sistema operativo dell'host. L'update gira
  dentro una unit (`vps1777-auto-update.service`) come utente non-root.

## Versioni e rilasci

- **Repo** — la cartella del progetto versionata con git (su GitHub).
- **PR** (pull request) — una proposta di modifica al repo, numerata (#251).
- **CI** — i controlli automatici che girano su ogni PR: test, lint, ledger.
- **Gate / presidio** — uno di quei controlli, che può bloccare («il verdetto di
  un gate si legge, non si aggira»).
- **Merge** — la proposta entra nel ramo principale (`main`).
- **Tag** — l'etichetta di versione su un commit (`v0.44.0`). I tag sono
  immutabili per regola.
- **Release / bundle** — il pacchetto pubblicato per quel tag: immagini su ghcr
  + bundle di file firmato (cosign). `vps1777 update` installa **quello**, mai
  il sorgente.
- **Deploy** — mettere in esercizio la release sulla VPS (qui: l'update).
- **Snapshot pre-update** — la copia dei volumi fatta un attimo prima di un
  update, per il rollback. Si tengono le ultime due (n, n-1).
- **Rollback** — tornare alla versione precedente se l'update va male
  (automatico al fallimento del health-gate, o `vps1777 rollback`).

## I dati

- **Backup core / archivio** — due livelli, entrambi cifrati (`age`, chiave
  privata FUORI dalla VPS): il core (piccolo: config, secrets, volumi leggeri,
  strati memoria) ogni notte; l'archivio (i DB grandi) ogni 7 giorni. Vedi
  [BACKUP-RESTORE.md](BACKUP-RESTORE.md).
- **DB (archivio)** — un archivio di conversazioni indicizzato per la ricerca
  full-text; se ne possono caricare molti.
- **Ingest** — caricare una fonte (export, zip, file) dentro un DB dell'archivio.
- **Export** — lo scarico dei propri dati da un servizio (es. l'export
  dell'account claude.ai, o di Telegram Desktop).
- **description** — la scheda di ogni DB (cosa contiene, come va usato),
  leggibile e aggiornabile dai tool.

## MCP e tool

- **MCP** — il protocollo con cui un assistente (Claude o altri) si collega a
  servizi esterni. Nella pratica: il "connettore" che dà a una chat dei tool.
- **Tool** — una funzione che **l'assistente** chiama durante la chat (non un
  comando da terminale). In una chat col connettore puoi dire: «chiama il tool
  `canonico` con full=true» e l'assistente lo fa e ti mostra il risultato.
- **Gateway** — il servizio esposto di vps1777: fa l'autenticazione (OAuth) e
  smista le chiamate MCP verso i servizi interni.
- **archive-mcp / archive1777** — i tool di ricerca sull'archivio (il passato).
- **nb1777** — i tool NotebookLM + il canonico della memoria.

## La memoria 1777 (dettaglio: [MEMORIA-1777.md](MEMORIA-1777.md))

- **Disciplina** — le regole di memoria (attribuzione, freschezza, canonico),
  il "blocco" che si incolla nelle superfici. Vive nel prodotto, in tre
  **tagli**: PIENO (superfici con MCP), LITE (progetti), MICRO (canali brevi).
- **Canonico** — il posto unico che dice quale versione della disciplina è
  quella buona: il file `disciplina.md`, servito dal tool `canonico`.
- **stale** — "vecchio": una superficie che porta una versione superata.
- **Strati** `fatti.md` / `errata.md` — chi è l'utente / i falsi ricordi
  corretti. Locali all'installazione, mai nel repo.
- **Superficie** — un posto dove il blocco è incollato: un `CLAUDE.md`, le
  preferenze dell'account, le istruzioni di un Project.
- **Ack** — la ricevuta «superfici aggiornate a vX.Y»: spegne il promemoria
  Telegram. La dà l'owner (bottone «✓ Fatto» o tool `memoria_ack`).

## Come leggere questa documentazione

- `testo così` è un nome esatto (file, comando, tool); un percorso che finisce
  in `.md` è una pagina da leggere, `.sh`/`.py`/`.yaml` sono codice o config —
  citati per dire **dove** sta una cosa, non da leggere per forza.
- Nei comandi: `<argomento>` va sostituito, `[opzionale]` si può omettere. Le
  alternative si scrivono per esteso («`stato`, `importa` o `mostra`»), non con
  la barra `|`, che nel terminale ha un altro significato.
- `tool(par=valore)` descrive una chiamata di tool MCP fatta dall'assistente,
  non una riga da digitare.
