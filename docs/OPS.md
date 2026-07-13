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

## Aggiornamenti — canale gestito

Il canale primario di aggiornamento è la CLI host **`vps1777 update`**
(installata da installer/deploy.sh) o il pulsante nel pannello admin → tab
**Update**: backup age + snapshot pre-update, pull con verifica digest,
migrazioni, health-gate 180s, **rollback automatico** se lo stack non torna
in salute. Manuale completo: [UPDATE.md](UPDATE.md).

Log dell'updater: `journalctl -u vps1777-update -u vps1777-check-update`.

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

### `ops.autoupdate` — auto-update (Watchtower) — declassato

[Watchtower](https://containrrr.dev/watchtower/) fa auto-pull + restart graceful
dei container vps1777 quando cambia un tag. Modalità label-only: tocca solo
i container opt-in (gateway, archive-mcp, nb1777-mcp, nb1777-bot).

> **Non supportato in concomitanza col canale gestito**: Watchtower bypassa
> backup, migrazioni, health-gate, changelog e rollback. Resta opt-in, ma il
> canale primario è `vps1777 update` / pulsante admin ([UPDATE.md](UPDATE.md));
> `vps1777 update` ti avvisa se lo trova attivo.

```bash
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
