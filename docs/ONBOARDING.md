# Onboarding — vps1777

Dopo `./deploy.sh`, lo stack gira ma è "dormiente": mancano le credenziali
(Tailscale, bot, NotebookLM). Le configuri **dal pannello web**, senza terminale
(tranne un comando finale di applicazione).

## Flusso

```
┌─────────────────────────────────────────────────────────────────┐
│  1. ./deploy.sh           (dal PC, ~6 domande, build + avvio)    │
│         ↓                                                        │
│  2. http://<IP_VPS>:8080/admin/setup   (browser, login admin)   │
│     inserisci: Tailscale key · bot token · carica auth.json     │
│     → Salva                                                     │
│         ↓                                                        │
│  3. ./deploy.sh --apply   (dal PC, applica tutto via SSH)       │
│     tailscale up · URL · restart · chiude la porta 8080         │
│         ↓                                                        │
│  4. https://<host>.ts.net/admin/setup   (tutto verde)          │
│     + connector claude.ai                                       │
└─────────────────────────────────────────────────────────────────┘
```

## 1. Deploy

Vedi [INSTALL.md](INSTALL.md). Al termine, lo stack è su e la porta 8080
è aperta sull'host per il pannello di setup.

## 2. Pannello /admin/setup

Apri `http://<IP_VPS>:8080/admin/setup`, login con l'email admin e la
password (stampata dal deploy o nel tuo password manager).

Il pannello mostra **lo stato dei componenti** a semafori e i form per:

| Sezione | Cosa inserisci | Dove lo prendi |
|---|---|---|
| Tailscale Funnel | pre-auth key `tskey-auth-...` | [login.tailscale.com/admin/settings/keys](https://login.tailscale.com/admin/settings/keys) |
| Bot Telegram | token + owner id | [@BotFather](https://t.me/BotFather) + [@userinfobot](https://t.me/userinfobot) |
| URL pubblico | (opzionale) solo per Caddy/Cloudflared con dominio tuo | — |
| NotebookLM | upload `auth.json` (bottone dedicato) | `nlm login` sul tuo PC |

Clicca **Salva configurazione**. I valori vanno in un file temporaneo
(`onboarding/pending.json`) sulla VPS, in attesa di applicazione.

> **NotebookLM è già attivo al volo**: l'upload di `auth.json` da `/admin/nlm`
> non richiede `--apply`, il servizio lo legge alla prossima chiamata.

## 3. Applica

Dal tuo PC, nella cartella del repo:

```bash
./deploy.sh --apply
```

Cosa fa (via SSH):
- scrive i veri Docker secret (`ts_authkey`, `telegram_bot_token`) e `.env`
- `tailscale up` con la key → ricava l'URL `*.ts.net`
- imposta `PUBLIC_BASE` con quell'URL
- riavvia i servizi **senza** la porta 8080 (la chiude)
- cancella `pending.json`
- stampa l'URL HTTPS finale

## 4. Verifica + connector

Apri `https://<host>.ts.net/admin/setup` → tutti i semafori verdi.

Poi su [claude.ai](https://claude.ai) → Settings → Integrations → Add connector:
```
https://<host>.ts.net/<GATEWAY_SECRET>/archive/mcp
https://<host>.ts.net/<GATEWAY_SECRET>/nb1777/mcp
```
(il `GATEWAY_SECRET` è stampato dal deploy; login OAuth con email+password admin.)

E manda `/start` al tuo bot Telegram.

## Perché questo flusso (e non tutto-web)?

Il gateway gira in un container **non privilegiato**: per sicurezza non ha
accesso al Docker daemon né ai secret host (un container con quei poteri =
root sull'host, inaccettabile per un servizio esposto a internet).

Quindi la separazione è netta e voluta:
- **raccolta dati** → pannello web (nessun privilegio, solo scrittura di un file)
- **applicazione** → `deploy.sh --apply` dal tuo PC (ha già SSH+sudo)

È il miglior compromesso sicurezza/comodità senza componenti privilegiati
sulla VPS.
