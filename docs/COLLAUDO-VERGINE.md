# Collaudo su VPS vergine — il test definitivo

> Runbook del **test end-to-end su macchina formattata**: dall'host vuoto allo stack
> validato, con le verifiche mirate sulle cure entrate fino alla 0.43.x. L'ordine è
> quello deciso il 02/08: **prima** formattazione + reinstallazione, **poi** il campione
> cieco del voice-tagging (che si tara sui dati ricaricati, non su quelli vecchi).

## 0 · Prima di formattare — ciò che dopo non si recupera

| Cosa | Chi | Note |
|---|---|---|
| Backup dei dati veri (DB archivio, profilo NotebookLM, secrets) | proprietario | [BACKUP-RESTORE.md](BACKUP-RESTORE.md); i DB rigenerabili dal re-ingest possono anche non essere salvati |
| Fotografia dello stato della macchina viva | fatta | baseline raccolta il 17/08 in sola lettura (fuori repo, canale operativo) |
| Credenziali che ruotano col format (password root/utente, chiavi ssh) | proprietario | la rotazione al format è decisa: annotare le nuove fuori dalla macchina |
| **Fotografia `pre-format` delle 9 prove empiriche** — sulla VPS VIVA, via ssh | chiunque, PRIMA del format | `bash tools/prove-empiriche/lancia-tutte.sh --fase pre-format` → scrive `onboarding/prove-empiriche-pre-format.json`. **È l'unico gesto di questa tabella che scade col format**: dopo, il comportamento della macchina vecchia non è più misurabile. Copiare il json fuori dalla VPS |

## 1 · Installazione (host vuoto → stack su)

I 4 step di [INSTALL.md](INSTALL.md) — oppure l'installer grafico. Il punto che questo
collaudo deve provare: `setup.sh` risolve la versione da **releases/latest** e tira
**immagini firmate** da ghcr — i sorgenti clonati e le immagini scaricate devono
dichiarare **lo stesso numero**.

A macchina formattata e **prima** dell'installer, la seconda fotografia:

```bash
bash tools/prove-empiriche/lancia-tutte.sh --fase macchina-nuda
```

poi i 4 step:

```bash
git clone https://github.com/neo1777/vps1777.git && cd vps1777 && ./setup.sh
vps1777 version         # atteso: tag == container == releases/latest
```

## 2 · Le verifiche mirate — una per cura, con l'esito atteso

Il criterio di tutte: **rileggere lo stato dell'oggetto**, mai fidarsi dell'exit 0 del
comando che lo attiva (è il filo della release 0.43.0).

| # | Cura da provare | Comando | Atteso |
|---|---|---|---|
| 1 | fail2ban vivo su Debian 12 (jail sshd `backend=systemd`, #200) | `systemctl is-active fail2ban && sudo fail2ban-client status sshd` | `active` + jail con `Currently banned` leggibile — **non** «Have not found any log file» |
| 2 | unit abilitate secondo `VPS1777_FEATURES` (setup = deploy = engine) | `systemctl list-unit-files 'vps1777-*' --state=enabled` | `check-update.timer`, `update.path`, `secrets-check.timer` (+ `auto-update.timer` se feature attiva) |
| 3 | auto-update ripara (catena #101 #104 #125 #155) | `sudo systemctl start vps1777-check-update.service && journalctl -u vps1777-check-update -n 20` | exit 0; nessun `Failed … sudo -n install` |
| 4 | self-update CLI | `vps1777 check && vps1777 status` | canale coerente, nessun errore di copia della CLI |
| 5 | reboot-survival | `sudo reboot` → attendere → `docker compose ps` | tutti i container `Up`, ingress raggiungibile |
| 6 | connector claude.ai end-to-end | dal client: `list_databases` via MCP | risponde (dopo il re-ingest: i DB nuovi) |

### 2b · La terza fotografia, e il confronto che è il vero verdetto

```bash
bash tools/prove-empiriche/lancia-tutte.sh --fase post-install
```

Le tre fasi scrivono **tre file distinti** (`onboarding/prove-empiriche-<fase>.json`) —
per costruzione: con un file solo la seconda foto cancellerebbe la prima. Il verdetto del
collaudo non è «post-install è verde»: è il **confronto** — ciò che era rosso sul vivo
(pre-format) e che l'installazione pulita doveva curare, ora è verde? Le 9 prove sono
l'unico strato che tocca il sistema reale (docker, rete, systemd veri): in CI non possono
girare per costruzione, e queste tre date sono la risposta a «da quanto non le lanciamo?».

## 3 · Re-ingest e quadratura dell'archivio

Upload da `/admin/archive` ([ARCHIVE.md](ARCHIVE.md)) annotando **il numero che l'upload
stampa** per ogni fonte, poi:

```bash
python3 tools/collaudo-quadratura.py <db> --sorgente N [--ingest-n N]
```

- La quadratura conta **messaggi E caratteri** (un ingest che leggesse solo `text`
  quadrerebbe sui messaggi e perderebbe il 63% dei caratteri senza dirlo).
- I numeri di riferimento noti valgono per l'export dell'08/07: **su un export nuovo si
  rimisura sull'export vero**, non si riusano i vecchi.

**Canary del tokenizer** — i DB ricostruiti da questo ingest nascono con
`tokenchars '+#'` (`archive_indexer.py`), quindi:

```
check_term("C++")   →  collapsed: false     (sui DB vecchi era true)
```

## 4 · Dopo il collaudo

1. **Campione cieco del voice-tagging** (50 messaggi classificati a mano) — ora, non
   prima: l'archivio su cui si tara è quello appena ricaricato.
2. Dichiarare l'esito del collaudo dove il lavoro è tracciato, con data e numeri.

## Se qualcosa non torna

[TROUBLESHOOTING.md](TROUBLESHOOTING.md) — e per i fallimenti delle unit di update il
journal è la fonte: `journalctl -u vps1777-auto-update -n 50`.
