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
| **Decidere la cifratura del disco/volume** (H56) | proprietario | l'unica cura per lo snapshot pre-update in chiaro che non rompe il rollback si fa **sul disco, al format** (es. LUKS sul volume dati): dopo, il treno è passato fino al prossimo format. *Decisione presa al format del 23/08/2026: provato Debian 13 coi volumi cifrati, la VPS era instabile → Debian 12, dischi in chiaro, rischio accettato (voce `H56` del registro)* |
| **Fotografia `pre-format` delle 9 prove empiriche** — sulla VPS VIVA, via ssh | chiunque, PRIMA del format | ⚠️ un'installazione fatta con `deploy.sh`/installer **non ha `.git` né (se vecchia) le prove**: si portano dal PC. Dal PC: `scp -r tools/prove-empiriche <vps>:/root/pf/tools/` poi sulla VPS `cd /root/pf && VPS1777_REPO=/home/vps1777/vps1777 bash tools/prove-empiriche/lancia-tutte.sh --fase pre-format` → copiare fuori `onboarding/prove-empiriche-pre-format.json`. **È l'unico gesto che scade col format** |

## 1 · Installazione (host vuoto → stack su)

Due vie equivalenti, ed **entrambe devono funzionare** — il collaudo della vergine
collauda anche la via che si sceglie:

- **installer grafico** (dal PC, zero comandi): `installer/launch.sh` → form → Installa
  ([installer/README.md](../installer/README.md));
- **CLI dal PC**: `./deploy.sh` (trasferisce il repo via tar-over-ssh: sulla VPS **non
  c'è `.git`** — è normale, non un difetto);
- (la terza, manuale sulla VPS con `git clone` + `setup.sh`, resta per chi fa a mano).

Il punto che il collaudo deve provare, per qualunque via: la versione risolta da
**releases/latest** e le **immagini firmate** da ghcr dichiarano **lo stesso numero**.

> **Intoppi visti al primo collaudo reale (23-27/08/2026)** — tutti dopo un'installazione
> riuscita, nessuno un difetto dell'installazione; i dettagli in
> [TROUBLESHOOTING.md](TROUBLESHOOTING.md):
> 0. il **recipient age** non rinasce col format: il primo `vps1777 update` si ferma
>    fail-safe sul backup finché non ricopi la chiave PUBBLICA dal PC in
>    `tools/age-recipients.txt` (mai generare la coppia sulla VPS —
>    [BACKUP-RESTORE.md](BACKUP-RESTORE.md));
> 1. l'URL `*.ts.net` può non risolvere per decine di minuti se un resolver pubblico ha
>    **cache negativa** (chiesta prima che il record nascesse) — diagnosi con `dig` su
>    resolver diversi, cura col purge di 1.1.1.1;
> 2. i **connector claude.ai** della macchina precedente sono doppiamente morti (secret
>    rigenerato + hostname eventualmente cambiato): si ricreano, non si «riconnettono»;
> 3. ricreandoli, il flusso passa dalla **consent OAuth** — che fino alla `0.43.1` su
>    Chrome moriva in silenzio al click su Autorizza (`H69`, curato in `0.43.2`): fu il
>    primo attraversamento reale di quel ramo dalla sua nascita (`0.33.0`).

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
Un esempio del confronto che conta: una `pre-format` su una versione vecchia può avere
**rosse attese** (es. prova-8 su 0.40.x: le cure sulle unit sono entrate dopo) — sulla
vergine quelle stesse prove **devono** diventare verdi: è la misura che il format ha
comprato le cure, non un dettaglio.

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

---

## Esito del primo collaudo (22-27/08/2026) — COMPLETO, con numeri

**La macchina**: VPS formattata due volte (Debian 13 + volumi LUKS provato e
scartato per instabilità → Debian 12, dischi in chiaro: decisione H56, rischio
accettato dall'owner il 23/08). Installazione con l'**installer grafico** dallo
zip di `main`, STEP 8/8 compreso il reboot test: v0.43.1 → poi **0.43.2 e
0.43.3 via canale update** (backup age + firma cosign a ogni salto).

**Le sei verifiche mirate: 6/6 verdi.** fail2ban attivo col backend journal
(643 ban reali al 27/08) · 4 unit enabled coi timer schedulati · canale update
esercitato due volte sul vivo · CLI coerente (corrente == latest) · reboot
survival (STEP 8) · connector claude.ai end-to-end col bottone vero.

**Le tre fotografie**: pre-format 5✅·1🔴·3⚪ (22/08, v0.40.x) · macchina-nuda
0/0/9 (23/08, primo format; il secondo format non ha la sua foto — dichiarato) ·
**post-install 7✅·0🔴·2⚪** (27/08, v0.43.2). Il confronto che è il verdetto:
la **prova-8 rossa sul vivo è verde sulla vergine**. La **prova-9** (fail-closed
+ rollback, col consenso dell'owner e il servizio giù per la durata del
rollback) è passata **alla prima esecuzione della sua storia**: gate sabotato →
rifiuto → rollback → versione di prima, 5 container su. La prova-6 resta
parziale by design (§③: aspetta la misura del dump su un backup reale).

**L'archivio**: profilo NotebookLM ripristinato da `/admin/nlm`; 10 DB
ricaricati (1 upload dal pannello + 9 tar-over-ssh, procedura del backup) e
**quadratura 10/10 per sha256** contro il MANIFEST del 22/08 — 365.763
messaggi · 936.749.829 caratteri, identici al byte. I DB drop-in conservano il
tokenizer vecchio (canary `check_term("C++") → collapsed: true`): il re-ingest
fresco, quando si farà, va su nomi diversi.

**Il raccolto — otto difetti veri trovati e curati DAL collaudo stesso**, tutti
mai visti prima perché i rami che li contenevano non erano mai stati attraversati
da un azzeramento vero: #208 (secret in una via su tre) · #209 (installer e
porta occupata) · `H69` (consent OAuth muta su Chrome, `form-action`) · `H70`
(la card update oscurata dal refresh fallito) · #214 (chiave age assente
dall'installer grafico) · prova-8 (falso rosso sulle unit template) · prova-9
(path di state.json sbagliato dalla nascita) · #218 (tabella archive che sfonda
il riquadro). Più gli intoppi d'ambiente documentati (cache DNS negativa,
connector doppiamente morti, recipient age da rimettere: #213).

**Il registro a fine collaudo**: 70 voci — 59 chiuse, 9 parziali, 2 accettate,
0 aperte. `H50` e `H54` chiuse con misure in produzione; `H56` accettata con
decisione datata.

**Fase 4 — il campione cieco del voice-tagging: FATTO (27/08/2026, sera).**
46 messaggi `speaker=human` (25 random + 21 stratificati sulle classi rare),
giudice l'owner in cieco, interattivo. Prerequisito scoperto strada facendo: i
DB drop-in erano di luglio, PRIMA del voice-tagging — `migrate_v2_to_v3` sui 10
DB (365.763 messaggi classificati, il grande in 118s). L'esito, che è la
ragione per cui il campione esisteva:
- **`own` regge: 17/20** — ed è il 93% dell'archivio: l'accuratezza pesata
  reale è alta;
- **`character` è rotta: 0/5 (+3 dubbi), a confidenza 0.85** — frasi normali
  dell'owner classificate «personaggio»: regola sistematicamente troppo larga;
- **`pasted_ai` non è MAI emessa** (0 su tutto l'archivio human) mentre il
  giudice l'ha usata 8 volte: il testo-AI incollato finisce in
  `pasted_transcript`/`mixed`/`own` — la distinzione che più serviva manca;
- `mixed` ↔ `pasted_transcript` si confondono fra loro (1/5 e 2/7): meno grave,
  l'informazione «c'è dell'incollato» resta giusta.
- accordo globale sui 37 giudizi confidenti: 20/37 (54%) — il numero grezzo è
  basso APPOSTA: il campione sovracampiona le classi dove l'euristica rischia.

**Il golden-set che la Fase 2 aspettava ora esiste**: 46 voci (uuid +
etichetta macchina + etichetta owner + dubbi dichiarati), SENZA testi — i
contenuti restano nei DB privati. Depositato in `data/` del volume archive
sulla macchina e nel backup locale (`golden-voice-2026-08-27.json`).

**La taratura sul gold: FATTA (27/08/2026, sera stessa).** Accordo sui 37
confidenti da 20/37 a **30/37**, falsi cari (own→pasted/character) da 4 a
**0**. Le due cure, entrambe dettate dalla misura e non dall'opinione:
- `character` ora vuole DUE segnali — il project GDR **e** la recitazione nel
  testo (azione fra asterischi singoli): il nome del progetto dice il dominio,
  non che quel messaggio è recitato. own passa a 21/21.
- `pasted_ai` ha imparato l'italiano: tick di automazione (`[… TICK …]`) e
  prompt-template («Sei un…», «Ruolo:», heading+elenchi+grassetti — anche con
  le newline collassate in doppi spazi, come fa uno degli ingest). 6/7 sui
  casi veri del gold; il settimo è un testo emotivo senza segnali formali,
  falso negativo accettabile per principio.
- `mixed` ↔ `pasted_transcript` restano com'erano: fuori dall'ordine di
  taratura, e ogni ritocco lì sposta equilibri misurati.

Il gold è ora il **test di accettazione**: `tools/tests/test_voice_golden.py`
(skippa dove gold e DB non ci sono — in CI — e si arma con
`VPS1777_GOLDEN_VOICE` + `VPS1777_GOLDEN_DB_DIR`). Impatto misurato a secco
su due DB reali: 432 righe su 13.797 e 1.339 su 61.100 cambiano classe, in
massima parte i CRON TICK ripetuti (1.201) e i prompt-template di ruolo —
campionati a mano, nessuna voce spontanea fra loro. Il retag degli archivi
vivi arriva con la release che porta questa taratura in produzione.

**Resta**: il completamento della prova-6 §③.
