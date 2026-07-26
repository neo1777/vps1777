# tools/prove-empiriche/ — le conclusioni che solo il sistema vivo può chiudere

**Scritte da setaccio (`abdd732a`) il 26/07/2026, round-1 e round-2 del loop-audit.**

## Perché esistono
Un audit su un sistema in produzione arriva a un punto dove la lettura del codice non basta:
*«il gateway esce su Internet?»*, *«egress lascia entrare?»*, *«lo snapshot resta in chiaro?»* sono
domande a cui **nessuna riga risponde** — servono una misura. Il kit chiama queste azioni **empiriche**
e le distingue dalle **cartacee**: una cartacea diventa un commit, un'empirica diventa un comando.

**E una prova DESCRITTA la deve tradurre chi ha la macchina; una ESEGUIBILE la lancia.** Questa cartella
esiste per non far pagare a Neo il lavoro di scriverle (lezione C9 di `02-LOOP-SU-CODICE.md`).

## Come si lanciano
```bash
cd ~/vps1777           # o dove sta il repo sulla VPS
bash tools/prove-empiriche/prova-1-gateway-non-esce.sh
```
**Exit code, uguale per tutte:** `0` = PASS · `1` = FAIL (con l'impatto scritto) · `2` = **non eseguibile**
(prerequisito mancante) — e il 2 è il valore che conta più degli altri: *distingue «non c'è niente» da «non
ho saputo vedere», che è il difetto per cui una guardia muta è peggio di nessuna guardia.*

## Le sei prove
| | cosa misura | invasiva? |
|---|---|---|
| **1** `gateway-non-esce` | il gateway raggiunge Internet? (se sì, un gateway bucato esfiltra i 5 secret che monta) | no — solo richieste in uscita |
| **2** `egress-non-entra` | su `egress` si esce ma non si entra? È **la lacuna che l'audio del round-2 ha dichiarato**: *«il vero isolamento NAT di egress non è stato testato dal vivo»* | no |
| **3** `health-deep-solo-interni` | `/health?deep` è chiuso agli esterni, e un `X-Forwarded-For` iniettato non fa passare per interni | no — due GET |
| **4** `snapshot-in-chiaro` | quanti snapshot pre-update ci sono, che età, se cifrati. **Osserva, non provoca** | no — sola lettura |
| **5** `sandbox-update-service` | prima di stringere `vps1777-update.service` con `ProtectSystem=strict`: quali path scrive davvero il codice, se `~/.sigstore` esiste, se l'ultimo backup ha contenuto (dove `PrivateTmp` romperebbe in silenzio). **Nata dal round-4** — dice *cosa serve* | no — solo lettura + `find`/`stat` |
| **6** `sandbox-strict-regge-sul-kernel` | costruisce con `systemd-run` la sandbox proposta dall'audio (`ProtectSystem=strict` + i path) e prova a scrivere: cosa consente il kernel e cosa nega, con una controprova negativa su `/etc` e `/usr/bin`. **Nata dallo stesso round, sullo stesso bersaglio** — dice *se la stretta regge* | sì — richiede `sudo`/root; nessun update reale lanciato |

## ⚠️ COSA QUESTE PROVE NON SONO — leggere prima di fidarsi di un verde
- 🔴 **Non sono state eseguite sul target.** Di ognuna è verificata la **sintassi** (`bash -n`) e la logica è
  scritta sui meccanismi reali letti nel codice (nomi dei *servizi* compose, non dei container: i
  `container_name` non sono dichiarati, quindi indovinarli sarebbe stato un errore). **Nessuna ha girato su
  una VPS viva** — chi le lancia la prima volta è il loro primo collaudo, e va saputo.
- 🔴 **La 2 e la 3 hanno un limite strutturale dichiarato dentro lo script**: girano **sulla** VPS, e la
  domanda vera («è raggiungibile da Internet?») si risponde solo **da fuori**. Lo dicono nel loro output
  invece di far credere il contrario. *Una prova che tace il proprio punto cieco è peggio di una che manca.*
- 🔴 **La 4 non provoca un update fallito.** Sarebbe la prova più forte del claim-72h, ed è invasiva su una
  macchina in produzione: **provocare un guasto sul server di qualcuno non è una decisione tecnica.** Se
  Neo la vuole, si progetta insieme con una finestra e un rollback pronto.
- Nessuna stampa segreti: dove serve un valore si misura **forma, conteggio o codice di stato**.

## Se una fallisce
Il FAIL stampa **l'impatto**, non solo l'esito — e il fix candidato quando esiste. Un fallimento qui non è
un bug dello script: è la risposta che l'audit statico non poteva dare. **Portatelo al round come finding
con la misura allegata**, che è l'unica prova dello stesso piano del difetto (`aperti.sh`, piano `vivo`).
