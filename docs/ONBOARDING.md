# Onboarding — vps1777

Dopo `./deploy.sh`, lo stack gira ma è "dormiente": mancano le credenziali
(Tailscale, bot, NotebookLM). Le configuri **dal pannello web**, senza terminale
(tranne un comando finale di applicazione).

## Flusso

```
┌─────────────────────────────────────────────────────────────────┐
│  1. ./deploy.sh           (dal PC, ~6 domande, pull + avvio)     │
│         ↓                                                        │
│  2. http://<IP_VPS>:8080/admin/setup   (browser, login admin)   │
│     inserisci: Tailscale key · bot token · profilo nlm (tgz)    │
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
| Tailscale Funnel | OAuth client (Client ID + Secret) — vedi [INGRESS.md](INGRESS.md) per i prerequisiti account | [login.tailscale.com/admin/settings/oauth](https://login.tailscale.com/admin/settings/oauth) |
| Bot Telegram | token + owner id | [@BotFather](https://t.me/BotFather) + [@userinfobot](https://t.me/userinfobot) |
| URL pubblico | (opzionale) solo per Caddy/Cloudflared con dominio tuo | — |
| NotebookLM | upload del **profilo nlm** (tar.gz, bottone dedicato) | `nlm login` sul tuo PC → `tar czf nlm-profile.tgz profiles/default` |

Clicca **Salva configurazione**. I valori vanno in un file temporaneo
(`onboarding/pending.json`) sulla VPS, in attesa di applicazione.

> **NotebookLM è già attivo al volo**: l'upload del profilo da `/admin/nlm`
> non richiede `--apply`, il servizio lo legge alla prossima chiamata.

## 3. Applica

Dal tuo PC, nella cartella del repo:

```bash
./deploy.sh --apply
```

Cosa fa (via SSH):
- scrive `TS_AUTHKEY` in `.env` (dall'OAuth client o dalla key) + il Docker secret `telegram_bot_token`
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

> **Aggiornamenti già pronti**: l'installer ha attivato il canale di update
> (comando `vps1777 update`, tab **Update** del pannello, check giornaliero con
> notifica Telegram). Quando esce una release ti arriva un avviso; aggiorni con
> un comando o un click, con backup e rollback automatici. Vedi [UPDATE.md](UPDATE.md).

## Perché questo flusso (e non tutto-web)?

Il gateway gira in un container **non privilegiato**: per sicurezza non ha
accesso al Docker daemon né ai secret host (un container con quei poteri =
root sull'host, inaccettabile per un servizio esposto a internet).

Quindi la separazione è netta e voluta:
- **raccolta dati** → pannello web (nessun privilegio, solo scrittura di un file)
- **applicazione** → `deploy.sh --apply` dal tuo PC (ha già SSH+sudo)

È il miglior compromesso sicurezza/comodità senza componenti privilegiati
sulla VPS.
