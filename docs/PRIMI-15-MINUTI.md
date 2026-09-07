# Primi 15 minuti — vps1777 sul tuo PC, senza affittare una VPS

> **La quarta via.** Le tre installazioni del [README](../README.it.md) chiedono tutte
> la stessa cosa: una VPS Linux vera, con IP e password di root. Prima di spendere,
> questa pagina ti fa vedere il prodotto **acceso**, sulla tua macchina, in pochi minuti
> — e ti dice, senza girarci intorno, **cosa in locale non potrai vedere**.

Ogni comando di questa pagina è stato eseguito su un ambiente pulito il **07/09/2026**
(container Debian 12 nudo, Docker 29.8.0, utente non-root con uid 1000), e i tempi qui
sotto sono quelli **misurati lì**. Dove il tuo risultato può essere diverso, è scritto.

---

## In due righe: cosa ottieni e cosa no

| ✅ In locale vedi | ❌ In locale NON vedi |
|---|---|
| I **5 servizi** in piedi e `healthy` | L'**ingress HTTPS pubblico** (Tailscale Funnel / Caddy / Cloudflare) |
| Il **pannello admin** e le sue quattro schede (NotebookLM, update, audit, archive) | I **connector su claude.ai**: per collegarli, claude.ai deve raggiungerti da Internet |
| I **due endpoint MCP** che rispondono `401` (ci sono, e chiedono l'autenticazione) | Il **bot Telegram** (serve un token da @BotFather) |
| Che un segreto sbagliato dà `404` e non `401` (non conferma il percorso) | **NotebookLM** (serve il profilo `auth.json`) |

🔑 **La differenza in una frase**: in locale monti e accendi il **motore**; la
**promessa** del README — *un solo URL HTTPS pubblico da incollare in claude.ai* — è
l'ingress, e l'ingress ha bisogno di una macchina raggiungibile da Internet. Non è un
dettaglio che ti nascondiamo per farti provare: è il pezzo che costa una VPS.

## Ti serve

- **Linux** con **Docker Engine + Compose v2** (`docker compose version` deve rispondere).
- **~2 GB** di disco per le immagini (misurato: `2.001GB` a stack in piedi; il download è
  meno, sono compresse) e una connessione: si scaricano 5 immagini da GHCR.
- **Il tuo utente normale, non `root`.** Non è una raccomandazione di stile: i container
  girano come **uid 1000**, e se installi da root i secret nascono `root:root 600` e il
  gateway non riesce a leggerli (lo stack resta in `Restarting`). Il primo utente di una
  Linux desktop *è* uid 1000, quindi da utente normale il problema non esiste. Se il tuo
  uid è diverso, la cura è in fondo a questa pagina.

---

## I cinque passi

### 1 · I prerequisiti — `~12 secondi`

```bash
sudo apt install -y git python3 python3-bcrypt
```

`setup.sh` calcola con `bcrypt` l'hash della tua password admin. Su Debian 12 e Ubuntu
23.04+ **non basta `python3-pip`** (vale PEP 668: pip c'è, ed è l'installazione a essere
vietata): il pacchetto giusto è `python3-bcrypt`. Su Fedora: `sudo dnf install python3-bcrypt`.

> **Deve apparire**: `python3 -c "import bcrypt"` non dice niente ed esce 0.
> *(misurato: 12s — sul mio banco `git` era già installato)*

### 2 · Il repo — `~6 secondi`

```bash
git clone https://github.com/neo1777/vps1777.git
cd vps1777
```

### 3 · Il wizard — `~1 minuto di macchina, più il tempo che ci metti a rispondere`

```bash
./setup.sh
```

Ti fa **sei domande**, in quest'ordine. Per una prova in locale:

| # | Domanda | Cosa rispondere in locale |
|---|---|---|
| 1 | `Email admin OAuth (il TUO Gmail)` | una email qualsiasi: in locale non c'è nessun OAuth di Google da soddisfare |
| 2 | `TELEGRAM_OWNER_ID` | **vuoto** — ti avvisa che bot e Mini App restano **negati a tutti**, ed è giusto così |
| 3 | `Quale ingress? [1/2/3]` | **1** (Tailscale): è l'unico che in locale **non aggiunge nessun container** — Tailscale girerebbe sull'host, e qui non lo installiamo |
| 4 | `Vuoi che generi io una password admin random?` | **s** — la stampa a schermo: **copiala adesso**, non te la ripropone |
| 5 | `TELEGRAM_BOT_TOKEN` | **vuoto** |
| 6 | `Procedo ora?` | **s** |

⚠️ **Conta le domande mentre rispondi, non prepararle in anticipo.** Se rilanci
`setup.sh` una seconda volta salta quelle a cui ha già una risposta (`.env` esiste, i
secret ci sono) — e chi aveva le risposte pronte le vede **scalare di posto**. *Misurato
il 07/09: a un rilancio la mia risposta alla domanda 6 è finita nella 5, e il wizard si è
salvato una `s` come token del bot.* Non fa danni permanenti — si svuota il file
`secrets/telegram_bot_token.txt` — ma è l'inciampo più facile di questa pagina.

> **Deve apparire**, in quest'ordine:
> `Installerò la release v0.48.1 (pull da ghcr, nessuna build)` → i secret generati uno
> per uno → il pull delle 5 immagini → `[✓] Stack avviato. Stato:` con la tabella dei
> container.
> *(misurato: **47 secondi** dal lancio all'ultimo container avviato, con le risposte
> date da uno script. Il grosso è lo scaricamento delle 5 immagini: sulla tua rete può
> essere molto di più, ed è l'unico passo che non posso promettere.)*

> ⚠️ **Alla fine ti chiede la password di `sudo`** («Installo il canale di aggiornamento
> (CLI vps1777 + timer)…»): serve a installare il comando `vps1777` in `/usr/local/bin`
> e quattro unit systemd. **Su una VPS vera è il pezzo che tiene aggiornata la macchina;
> per una prova sul tuo PC non serve.** Puoi dargliela, oppure premere **Ctrl-C**:
> *misurato — `setup.sh` esce (codice 130), **lo stack resta su** e il pannello risponde
> `200`.* Lo stack è già avviato quando quel prompt arriva.

### 4 · Guarda che è vivo — `immediato`

```bash
docker compose -f compose.yaml -f compose.ingress.tailscale.yaml ps
```

> **Deve apparire**: **cinque** container `Up … (healthy)` — `gateway`, `archive-mcp`,
> `nb1777-mcp`, `nb1777-bot`, `ocr` — e sotto `PORTS`, per il gateway,
> **`127.0.0.1:8080->8080/tcp`**: la porta sta sul **loopback**, non su `0.0.0.0`.
> `nb1777-bot` risulta `healthy` anche col token vuoto *(misurato)*: il container è vivo,
> e senza `TELEGRAM_OWNER_ID` il bot è comunque negato a tutti — te l'ha detto il wizard.

Se uno dei container resta `Restarting`, salta a *[Se non torna](#se-non-torna)* qui sotto.

### 5 · Entra nel pannello — `~1 minuto`

Apri **`http://127.0.0.1:8080/admin/login`** e accedi con l'email che hai dato e la
password che il wizard ha stampato.

> **Deve apparire**: il login riesce (redirect), e le quattro schede rispondono —
> `/admin/nlm`, `/admin/update`, `/admin/audit`, `/admin/archive`.
> *(misurato: `GET /admin/login` → `200`; `POST` col login vero → `302`; le quattro
> pagine, con la sessione, → `200`, coi titoli `vps1777 · NotebookLM`, `· update`,
> `· audit`, `· Archive`)*

E i due connettori MCP, che sono il cuore del prodotto:

```bash
SEC=$(cat secrets/gateway_secret.txt)
curl -s -o /dev/null -w "archive → %{http_code}\n" -X POST http://127.0.0.1:8080/$SEC/archive/mcp
curl -s -o /dev/null -w "nb1777  → %{http_code}\n" -X POST http://127.0.0.1:8080/$SEC/nb1777/mcp
curl -s -o /dev/null -w "segreto sbagliato → %{http_code}\n" -X POST http://127.0.0.1:8080/pippo/archive/mcp
```

> **Deve apparire**: `401`, `401`, **`404`**. *(misurato)* I primi due dicono «ci sono, e
> senza autenticazione non entri»; il terzo è il dettaglio che conta: con un segreto
> sbagliato il gateway risponde **404 e non 401**, cioè non ti conferma che quel percorso
> esista.

---

## Quando hai visto abbastanza — smontare

```bash
docker compose -f compose.yaml -f compose.ingress.tailscale.yaml --profile ingress.tailscale down -v
```

> **Deve apparire**: i cinque container rimossi e i volumi cancellati (`-v`: se lo ometti
> restano i dati). Le immagini restano nella cache di Docker: `docker image prune -a` se
> vuoi indietro anche quei ~2 GB. *(misurato: 0 container e 0 volumi rimasti)*
> La cartella `vps1777/` la puoi cancellare — dentro ci sono i tuoi secret di prova.

---

## Se non torna

**Uno o più container in `Restarting`, e nei log `PermissionError: [Errno 13] Permission
denied: '/run/secrets/gateway_secret'`.** Hai installato da `root` (o il tuo uid non è
1000): i container girano come uid **1000** e non riescono a leggere i secret.

```bash
chown 1000:1000 secrets/*.txt
docker compose -f compose.yaml -f compose.ingress.tailscale.yaml --profile ingress.tailscale up -d
```

⚠️ **Non** `chown $(id -u):$(id -g)`: serve l'uid **di dentro il container**, non il tuo.
Se lanci quel comando da root non cambi niente e resti fermo credendo di aver curato.
Il caso completo è in [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

**`manifest unknown` sul pull.** Stai lanciando `docker compose` **senza** il `.env` che
`setup.sh` scrive: senza `VPS1777_TAG` il default è `dev`, che su GHCR non esiste. Lancia
prima `./setup.sh`.

Il resto: [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

---

## E adesso? Il pezzo che il locale non può darti

Quello che hai in mano è lo stack completo, **senza la porta d'ingresso**. Per avere la
cosa che il README promette — *un URL HTTPS pubblico da incollare in claude.ai* — servono
una macchina raggiungibile da Internet e un ingress:

- [INSTALL.md](INSTALL.md) — l'installazione vera, passo per passo;
- [INGRESS.md](INGRESS.md) — le tre vie all'HTTPS: Tailscale Funnel, Caddy, Cloudflare;
- e **quando ce l'hai**, la domanda che chiude il cerchio si fa **da fuori**, dal tuo PC:

  ```bash
  ./tools/collaudo-da-fuori.sh https://tuo-url-pubblico
  ```

  quattro controlli in cinque secondi — risponde da Internet, TLS valido, il pannello è
  quello di vps1777, la porta 8080 di fallback si è richiusa. Su un bersaglio locale
  (`127.0.0.1`) **si rifiuta di rispondere**, e lo dice: da qui dentro quella domanda non
  ha soggetto, e un verdetto sarebbe su un'altra cosa.
