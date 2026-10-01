# Onboarding — vps1777

Dopo `./deploy.sh`, lo stack gira ma è "dormiente": mancano le credenziali
(Tailscale, bot, NotebookLM). Le configuri **dal pannello web**, senza terminale
(tranne un comando finale di applicazione).

## Flusso

```
┌─────────────────────────────────────────────────────────────────┐
│  1. ./deploy.sh           (dal PC, ~6 domande, pull + avvio)     │
│         ↓                                                        │
│  2. <pannello>/admin/setup   (browser, login admin)             │
│     via Funnel, dominio HTTPS o tunnel SSH (vedi §2)            │
│     inserisci: Tailscale key · bot token · profilo nlm (tgz)    │
│     → Salva                                                     │
│         ↓                                                        │
│  3. ./deploy.sh --apply   (dal PC, applica tutto via SSH)       │
│     tailscale up · verifica Funnel · URL · restart              │
│         ↓                                                        │
│  4. https://<host>.ts.net/admin/setup   (tutto verde)          │
│     + connector claude.ai                                       │
└─────────────────────────────────────────────────────────────────┘
```

## 1. Deploy

Vedi [INSTALL.md](INSTALL.md). Al termine, lo stack è su. La porta 8080 del
gateway è pubblicata **solo sul loopback** della VPS (`127.0.0.1`): la governa
`GATEWAY_BIND` col profilo Tailscale (`compose.ingress.tailscale.yaml`) e
`ONBOARDING_BIND` con Caddy e Cloudflared (`compose.onboarding.yaml`). Da
Internet la 8080 non si raggiunge; alla fine `deploy.sh` stampa come aprire il
pannello nel tuo caso.

## 2. Pannello /admin/setup

Come ci arrivi dipende dal profilo:

| Caso | Indirizzo |
|---|---|
| Tailscale, auth-key data al deploy | `https://<host>.ts.net/admin/setup` — il Funnel è già attivo |
| Caddy o Cloudflared | `https://<tuo-dominio>/admin/setup` — il proxy serve HTTPS dal primo avvio |
| HTTPS non ancora pronto (Tailscale senza key, certificato non emesso) | tunnel SSH dal tuo computer: `ssh -L 8080:127.0.0.1:8080 <utente>@<IP_VPS>`, poi `http://127.0.0.1:8080/admin/setup` |

> Con Caddy o Cloudflared, `ONBOARDING_BIND=0.0.0.0` nel `.env` della VPS
> rimette la porta su tutte le interfacce (`http://<IP_VPS>:8080/admin/setup`).
> È un compromesso dichiarato: pannello e login viaggiano in HTTP, quindi
> password e sessione admin passano in chiaro finché non c'è HTTPS. Toglila
> appena il pannello risponde in HTTPS.

Login con l'email admin e la password: il deploy la stampa se lo lanci da un terminale;
se l'output va altrove (una pipe, un log, un agente) la scrive in
`~/.config/vps1777/admin-password-<data>.txt`, leggibile solo dal tuo utente, e ti dice
dove (H75). Copiala nel password manager e cancella il file.

Il pannello mostra **lo stato dei componenti** a semafori e i form per:

| Sezione | Cosa inserisci | Dove lo prendi |
|---|---|---|
| Tailscale Funnel | **Auth-key** (`tskey-auth-…`). La prendi diretta dalle Keys, oppure te la genera un OAuth client (*Modalità B* in [INGRESS.md](INGRESS.md)) — ma nel form va **sempre la key**, non il Client ID | [login.tailscale.com/admin/settings/keys](https://login.tailscale.com/admin/settings/keys) |
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
- valida la forma di ogni valore di `pending.json`, poi scrive `TS_AUTHKEY` e
  `TELEGRAM_OWNER_ID` in `.env`, il Docker secret `telegram_bot_token` e la
  chiave derivata `secrets/telegram_webapp_secret.txt`, con cui il gateway
  verifica la Mini App senza avere il token ([MINIAPP.md](MINIAPP.md))
- `tailscale up` con la key → ricava l'URL `*.ts.net`, attiva il Funnel e
  controlla **da questo PC** che risponda davvero
- dopo un `tailscale up` riuscito azzera `TS_AUTHKEY` in `.env`: la key è
  monouso, e il nodo resta nel tailnet senza di lei (H15)
- imposta `PUBLIC_BASE` con quell'URL (o con quello che hai dato nel pannello)
- riavvia i servizi (`docker compose up -d`). Con Caddy o Cloudflared il
  riavvio è senza `compose.onboarding.yaml`, quindi la 8080 sull'host si chiude
  del tutto. Col profilo Tailscale il gateway resta su `127.0.0.1:8080`,
  raggiunto solo dal Funnel. Se il Funnel **non** risponde, come ripiego scrive
  `GATEWAY_BIND=0.0.0.0` e la 8080 si apre in HTTP su tutte le interfacce,
  perché la macchina resti raggiungibile: quando il Funnel risponde, riporta
  `GATEWAY_BIND=127.0.0.1` nel `.env` e ricrea il gateway
- cancella `pending.json`
- stampa l'URL HTTPS finale

## 4. Verifica + connector

Apri `https://<host>.ts.net/admin/setup` → tutti i semafori verdi.

Poi su [claude.ai](https://claude.ai) → Settings → Integrations → Add connector:
```
https://<host>.ts.net/<GATEWAY_SECRET>/archive/mcp
https://<host>.ts.net/<GATEWAY_SECRET>/nb1777/mcp
```
(il `GATEWAY_SECRET` lo consegna il deploy: a schermo se lo lanci da un terminale, altrimenti
in un file `600` — con le URL dei connettori già composte — che la riga `RESULT_SECRET_FILE=`
nomina (H77); login OAuth con email+password admin.)

> ⚠️ **Dopo una reinstallazione** questi URL cambiano SEMPRE (il secret è
> rigenerato; e l'hostname, se il device Tailscale è stato ricreato): i connector
> esistenti su claude.ai vanno ricreati con l'URL nuovo — non torneranno a
> funzionare da soli. Vedi [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

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
