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

- **python3** (il mini-server, zero dipendenze esterne)
- **ssh** (OpenSSH client)
- **sshpass** — solo se accedi alla VPS con password
  (WSL/Linux: `sudo apt install sshpass`; Mac: `brew install hudochenkov/sshpass/sshpass`)

## Come funziona

```
Browser (UI form)  ──HTTP 127.0.0.1──►  mini-server Python  ──SSH──►  VPS
   semafori live          /api/check  (test connessione)
   pulsante Installa      /api/deploy (lancia deploy.sh, streaming)
   schermata finale       parse RESULT_* dall'output
```

Il browser non può fare SSH (sandbox): il mini-server locale fa da ponte.
Tutto resta su `127.0.0.1` — le credenziali non lasciano il tuo PC. Il
server lancia `deploy.sh` (lo stesso del flusso CLI) in modalità
non-interattiva, passando i valori del form via variabili d'ambiente.

## Flusso UI

1. **La tua VPS** — IP, utente, password → *Verifica connessione* (semaforo verde)
2. **Admin** — email (la password è generata e mostrata alla fine)
3. **Ingress** — Tailscale (key) / Caddy (dominio) / Cloudflared (token)
4. **Bot Telegram** — opzionale
5. Quando tutti i semafori sono verdi, **Installa** si attiva → avanzamento
   live → schermata con URL, password admin, URL connector claude.ai.

## Sicurezza

- Bind solo su `127.0.0.1` (non raggiungibile dalla rete).
- Le password viaggiano solo PC→localhost→SSH, mai verso terzi.
- Per uso condiviso/non fidato, preferisci il flusso CLI (`./deploy.sh`).
