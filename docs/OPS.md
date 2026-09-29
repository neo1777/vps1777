# Ops — vps1777

Hardening di base (automatico) e profili operativi **opzionali**.

## Hardening di base (lo fa l'installer)

Durante il deploy, `step_prepare` applica un hardening minimo **sicuro** sull'host:

- **`unattended-upgrades`** — patch di sicurezza automatiche (scrive `/etc/apt/apt.conf.d/20auto-upgrades`, abilita il servizio).
- **`fail2ban`** — blocca i brute-force SSH (banna gli IP con troppi login falliti; non tocca chi si autentica correttamente).

> **Perché NON disabilitiamo password/root login via SSH.** L'installer si connette
> via **password** e si riconnette dopo il reboot di test sempre via password:
> disabilitare `PasswordAuthentication` o `PermitRootLogin` *durante* il deploy
> ti chiuderebbe fuori. È un hardening da fare **a mano dopo**, una volta caricata
> la tua chiave SSH:
> ```bash
> ssh-copy-id <user>@<IP_VPS>            # carica la tua chiave
> # poi sulla VPS, in /etc/ssh/sshd_config.d/99-hardening.conf:
> #   PasswordAuthentication no
> #   PermitRootLogin prohibit-password
> sudo systemctl restart ssh
> ```
> Fallo solo dopo aver verificato che il login a chiave funziona.

## Le feature dichiarate — cosa il reinstall riproduce (e perché non si perde nulla)

Le funzioni operative di vps1777 (backup notturno, auto-update sicuro, Portainer) sono
**dichiarate**, non attivate a mano una volta e poi dimenticate. La dichiarazione vive in
una riga del `.env` della VPS:

```
VPS1777_FEATURES=backup,autoupdate        # il default: backup + auto-update sicuro
```

L'installazione legge questa riga e accende le feature corrispondenti, su tutte le vie:
l'installer grafico, `deploy.sh`, il bootstrap e `setup.sh`, che dal 29/09 avvia anche gli
overlay delle feature (`compose.ops.backup.yaml` col profilo `ops.backup`) al primo giro.
Prima il backup partiva solo al primo update. Quindi un reinstall della VPS non riparte
"nudo": riproduce le feature dichiarate. Anche update e rollback la rileggono per intero:
ne ricavano i profili compose (`backup`, `portainer`) per lo `up` che fanno, e dal 29/09
accendono o spengono il timer dell'auto-update secondo la riga. Le altre unit le
reinstallano e ne lasciano l'abilitazione com'è: un operatore può averne spenta una di
proposito. L'installer grafico chiude con un **referto** che
le elenca (e `deploy.sh` con un blocco equivalente):

```
✓ Feature attive: backup=ON · auto-update sicuro=ON · portainer=OFF
```

> **Perché questa riga esiste — ed è il cuore del "non perdere funzioni".** Prima di v0.38.0
> queste erano profili **opt-in**: attivati a mano, e un reformat della VPS li perdeva **in
> silenzio** — nessun documento mentiva, ma la funzione spariva. È successo davvero con
> l'auto-update: declassato a giugno, il rimpiazzo mai costruito, e per un mese la VPS non si
> auto-aggiornava senza che nessuno se ne accorgesse.
>
> La cura non è "ricordarsi meglio" (la memoria di chi installa, o di una sessione di lavoro,
> muore). La cura è **lo stato dichiarato**: se una feature non c'è, o è **dichiarata** (e il
> referto lo mostra), o è un **bug che il reinstall non ha rispettato la dichiarazione** — mai
> "ci siamo dimenticati". `VPS1777_FEATURES` è alla VPS ciò che il **ledger delle feature**
> (`features.yaml`, verificato in CI) è al repo: la memoria che sopravvive a chi la scrive.

Per cambiare le feature, oggi, i gesti sono due e servono entrambi:

1. **Modifica `VPS1777_FEATURES`** nel `.env`: è ciò che il prossimo reinstall riprodurrà.
2. **Applica il cambio adesso**, perché nessun comando lo fa al posto tuo:
   - `autoupdate` — `sudo systemctl enable --now vps1777-auto-update.timer` per
     accenderlo, `sudo systemctl disable --now vps1777-auto-update.timer` per spegnerlo
     (l'operatore ha `systemctl` nella whitelist sudo). Senza questo passo la riga del
     `.env` cambia e il timer resta com'era.
   - `backup`, `portainer` — sono profili compose: la CLI li aggiunge ai `docker compose`
     di update e rollback, quindi entrano al prossimo update **che installa davvero** (a
     versione già corrente `vps1777 update` risponde «già aggiornato» e non tocca lo
     stack). Per accenderli subito, il comando della sezione [Profili
     opzionali](#profili-opzionali); per spegnerne uno, `docker rm -f vps1777-backup` (o
     `vps1777-portainer`): togliere il file dal comando non ferma un container già acceso,
     lo lascia lì come orfano.

Il referto lo stampa solo l'installazione: dopo un cambio a mano, lo stato vero lo dicono
`systemctl list-unit-files 'vps1777-*' --state=enabled` e `docker ps` — **l'assenza parla**
anche lì.

> ⚠️ **Non è una feature dichiarata: `vps1777-indice-notturno.timer`.** L'aggiornamento
> notturno dell'indice della ricerca per senso si accende a mano
> (`vps1777 indice-notturno --abilita`, vedi [UPDATE.md](UPDATE.md)) e non sta in
> `VPS1777_FEATURES`: un reinstall **non** lo riaccende. Dopo un reinstall va riacceso.

## Aggiornamenti — auto-update sicuro (di default) + on-demand

Da **v0.38.0** l'aggiornamento è **automatico e sicuro di default**, e resta anche
manuale quando vuoi. Tre pezzi, un solo motore (`vps1777 update`, con backup + verifica
firma/digest + migrazioni + health-gate 180s + **rollback automatico**):

| quando | chi lo fa | cosa fa |
|---|---|---|
| **ogni giorno, da solo** | `vps1777-auto-update.timer` → `.service` | applica l'update sicuro **senza che tu faccia nulla**, ma solo una release pubblicata da **almeno 48 ore** (quarantena, vedi [UPDATE.md](UPDATE.md)); il timer lo accende l'installazione se la feature `autoupdate` è dichiarata (`VPS1777_FEATURES`, default sì) |
| **ogni giorno, avvisa** | `vps1777-check-update.timer` | **controlla e notifica** su Telegram («aggiornamento disponibile»), non applica |
| **quando vuoi tu** | CLI `vps1777 update` o pulsante admin → tab **Update** | applica **on-demand**, stessa rete di sicurezza |

> **Sicuro** vuol dire una cosa precisa: ogni applicazione fa **backup + snapshot** prima,
> verifica la **firma cosign** e il **digest**, applica le **migrazioni**, e se lo stack non
> torna in salute entro 180s fa **rollback automatico** ripristinando i dati. È la differenza
> con Watchtower (sotto): l'auto-update sicuro NON è "pulla e riavvia e speriamo".

> **Default dichiarato, non ricordato.** L'auto-update sicuro è ON di default perché
> `autoupdate` è in `VPS1777_FEATURES` (`.env`). Un reinstall lo **riproduce** — non
> sparisce in silenzio. Per spegnerlo servono i due gesti di sopra: togli `autoupdate` da
> `VPS1777_FEATURES` (così il prossimo reinstall non lo riaccende) **e**
> `sudo systemctl disable --now vps1777-auto-update.timer` (così si spegne adesso: update
> e rollback non lo fanno). Verifica: `systemctl is-enabled vps1777-auto-update.timer` →
> `disabled`.

Log: `journalctl -u vps1777-auto-update -u vps1777-update -u vps1777-check-update`.

## Profili opzionali

Si attivano aggiungendo il file override + il `--profile`. Esempio con Tailscale:

```bash
docker compose -f compose.yaml -f compose.ingress.tailscale.yaml \
  -f compose.ops.portainer.yaml \
  --profile ingress.tailscale --profile ops.portainer up -d
```

> **Immagini di terzi — digest-pinnate.** Le immagini non-vps1777 usate nei compose
> (`alpine` per `ops.backup`, `caddy`, `cloudflared`, `portainer`, `watchtower`)
> sono **pinnate al digest** (`tag@sha256:…`) e tracciate da **Dependabot** (v0.27.0):
> l'aggiornamento arriva come PR verificabile, non come un `latest` che cambia sotto
> i piedi.

### `ops.portainer` — cruscotto visuale dei container

[Portainer CE](https://www.portainer.io/) dà una UI web per vedere/gestire
container, stack, log e volumi.

- **Non è esposto a internet**: è pubblicato **solo su `127.0.0.1`** della VPS.
  Ci accedi via **tunnel SSH** dal tuo PC:
  ```bash
  ssh -L 9443:127.0.0.1:9443 <user>@<IP_VPS>
  # poi apri https://localhost:9443 → al primo accesso crei l'utente admin
  ```
  > Per sicurezza Portainer **blocca la creazione dell'admin** se non la fai
  > entro pochi minuti dall'avvio del container. Se ti dice "timeout", riavvialo:
  > `docker restart vps1777-portainer` e riapri subito il tunnel.
- Monta il Docker socket (gli serve per gestire i container): è il motivo per
  cui **non si espone mai a internet**. Il gateway pubblico resta senza socket;
  Portainer è un tool admin separato e locale. Sta su rete `backend` (internal,
  nessun egress).

### `ops.autoupdate` — Watchtower (legacy, opt-in, **NON usare**)

[Watchtower](https://containrrr.dev/watchtower/) fa auto-pull + restart dei container quando
cambia un tag (modalità **label-only**: tocca solo i container opt-in — gateway, archive-mcp,
nb1777-mcp, nb1777-bot). **Fu l'auto-update d'origine, declassato il 10/06/2026** perché
**bypassa tutta la rete di sicurezza**: niente backup, niente migrazioni, niente health-gate,
niente rollback, niente changelog. Il suo posto è ora dell'**auto-update sicuro** (il timer sopra).

> ⚠️ **Resta come profilo opt-in solo per compatibilità, ma è NON supportato e sconsigliato.**
> Se lo attivi, `vps1777 update` ti avvisa che è in esecuzione e che confligge col canale
> gestito. **Non attivarlo:** riaccenderlo rifà l'errore che il declassamento del 10/06 ha
> corretto. Se ti serve l'auto-update, è già attivo di default in forma sicura — non serve
> Watchtower.

```bash
# solo se sai esattamente perché lo vuoi (e accetti di perdere backup/rollback):
docker compose ... -f compose.ops.watchtower.yaml --profile ops.autoupdate up -d
```

### `ops.backup` — backup volumi age-encrypted

Vedi [BACKUP-RESTORE.md](BACKUP-RESTORE.md).

Il container `backup` **non monta `docker.sock`** e **non installa `docker-cli`**
(finding H13): montare il socket darebbe a un container di servizio il controllo
root-equivalente dell'host. I volumi dati gli sono invece montati **direttamente
in sola lettura** sotto `/volumes/<nome>` e `backup.sh` li tara da lì
(`BACKUP_VOLUMES_DIR`). Lo stesso `backup.sh` resta *dual-context*: sull'**host**
dumpa via `docker run`, **dentro il container** usa i mount diretti. Col profilo
`ingress.caddy` esistono anche `caddy-data`/`caddy-config`: nel compose ci sono due
righe commentate da decommentare per includerli.

## Combinare i profili

I profili sono indipendenti e cumulabili. Aggiungi più `-f compose.ops.*.yaml`
e più `--profile ops.*` allo stesso comando.
