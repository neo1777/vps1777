# vps1777 installer — UI locale

Installer grafico che gira **sul tuo PC**: compili un form, verifichi la
connessione, clicchi **Installa**, segui l'avanzamento live e a fine
installazione vedi tutti i dati per collegarti.

## Avvio

| Sistema | Come |
|---|---|
| Windows | doppio-click su `launch.bat` |
| Linux / Mac | doppio-click su `launch.sh` (o `bash installer/launch.sh`) |
| WSL | `bash installer/launch.sh` |

Si apre il browser su `http://127.0.0.1:8777`. Se non si apre da solo,
vai a quell'indirizzo a mano.

## Cosa serve sul PC

- **python3** — Windows: da [python.org](https://python.org) (spunta "Add to PATH"); Linux/Mac: già presente
- **paramiko** — libreria SSH Python; i launcher la installano da soli se manca

**Niente altro**: nessun bash, nessun sshpass, nessun WSL. Funziona su
**Windows / Mac / Linux nativo**.

## Come funziona

```
Browser (UI form)  ──HTTP 127.0.0.1──►  installer.py + engine.py  ──SSH (paramiko)──►  VPS
   semafori live          /api/check    (test connessione)
   pulsante Installa      /api/deploy   (engine esegue gli step via SSH, streaming)
   schermata finale       parse RESULT_* dall'output
```

Il browser non può fare SSH (sandbox): il mini-server locale fa da ponte.
L'**engine Python** (`engine.py`, basato su paramiko) si connette alla VPS,
carica il repo via SFTP ed esegue gli step (prepara Docker + hardening, genera
secret, build+up, **installa Tailscale sull'host** + Funnel, reboot test)
**direttamente via SSH**. Tutto resta su `127.0.0.1` — le credenziali non
lasciano il tuo PC.

> **Cross-OS vero**: la VPS è Linux e riceve comandi shell standard; il PC
> esegue solo Python (paramiko + urllib + stdlib). Per questo gira anche su
> **Windows nativo**, dove non esistono bash/sshpass.

> **Il deploy sopravvive al refresh**: l'installazione gira in un thread sul
> mini-server locale; se aggiorni o chiudi la pagina e riapri `127.0.0.1:8777`,
> la console si riaggancia e l'install prosegue.

## Flusso UI

1. **La tua VPS** — IP, utente, password → *Verifica connessione* (semaforo verde)
2. **Admin** — email (la password è generata e mostrata alla fine)
3. **Ingress** — Tailscale (**auth-key** semplice *oppure* OAuth client; vedi checklist prerequisiti) / Caddy (dominio) / Cloudflared (token)
4. **Bot Telegram** — opzionale (semaforo verde solo dopo "Verifica bot" reale)
5. Quando i semafori sono verdi, **Installa** si attiva → avanzamento live →
   schermata con URL, password admin, URL connector claude.ai.

## Dopo l'installazione

- Su [claude.ai](https://claude.ai) → Settings → Integrations → **Add**, incolla
  gli URL connector (devono essere **HTTPS** — il Funnel li serve così) e fai
  login con email + password admin.
- **`archive` espone 2 tool** (`search`, `get_conversation`); **`nb1777` ne espone 35** — aggiungi entrambi i connector se li vuoi tutti.
- I connector **persistono** ai restart del gateway (registrazioni DCR salvate su disco): li aggiungi una volta sola.

## Sicurezza

- Bind solo su `127.0.0.1` (non raggiungibile dalla rete).
- Le password viaggiano solo PC→localhost→SSH, mai verso terzi.
- Per uso condiviso/non fidato, preferisci il flusso CLI (`./deploy.sh`).
