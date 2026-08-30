# Memoria 1777 — il canonico nel prodotto

> **Stato**: introdotto in **v0.44.0** (2026-08-30). Canonico corrente: la riga di titolo di
> [`services/nb1777-mcp/app/memoria_1777/disciplina.md`](../services/nb1777-mcp/app/memoria_1777/disciplina.md)
> — è l'unico posto che conta; questa pagina spiega come usarlo, non lo ripete.

Vedi anche: [NB1777.md](NB1777.md) §6 (i tool `canonico`, `memoria_check`, `memoria_ack` e le
notifiche) · [BACKUP-RESTORE.md](BACKUP-RESTORE.md) (gli strati locali stanno nel core notturno) ·
[SECURITY.md](../SECURITY.md) §Dati a riposo.

## Il perché, prima del come

Un agente con memoria sbaglia in un modo preciso: non ricorda *poco*, ricorda cose **false** — e più
memoria ha, più le amplifica. L'11/07/2026 un audit ha trovato che «l'utente è un programmatore C++»
era la voce di un terzo dentro un transcript incollato, letta come se l'avesse detta lui; e che un
libro «in pausa al capitolo 19» era la battuta di un personaggio simulato, mai ratificata, mentre era
finito da mesi. La cura non è stata *aggiungere ricordi*: è stata mettere in ogni sessione **le regole
per giudicarli** — chi parla (ATTRIBUZIONE), quando era vero (FRESCHEZZA), e come accorgersi che le
regole stesse sono vecchie (CANONICO). Quelle regole sono la **disciplina di memoria 1777**.

Se la disciplina sta *dentro* ogni superficie (ogni `CLAUDE.md`, le preferenze cloud, i Project),
nasce la domanda «quale delle N copie è quella buona?». Il **canonico** è il posto designato che la
dà. Fino a 0.43 era un notebook NotebookLM; da 0.44.0 è **un file del prodotto**.

## Cosa spedisce vps1777, e cosa no

La separazione è quella di `/usr` contro `/etc`: **si spedisce il meccanismo, non il contenuto**.

| Cosa | Natura | Dove vive | Chi lo aggiorna |
|---|---|---|---|
| `disciplina.md` — le regole, in tre tagli (PIENO / LITE / MICRO) | **prodotto**: neutro, vale per chiunque | nel repo, dentro l'immagine `nb1777-mcp` (`app/memoria_1777/`) | una release di vps1777 (bump della `vX.Y` in testa + riga in «Storia») |
| `fatti.md` — chi è l'utente di *questa* installazione | **dato**: personale ma stabile | volume dati di nb1777-mcp, `/var/lib/nlm/memoria-1777/` | l'amministratore, con `vps1777 memoria importa fatti <file>` |
| `errata.md` — i falsi corretti, con la fonte che li genera ancora | **dato** | idem | `vps1777 memoria importa errata <file>` |
| persone, famiglia, il personale | — | **in nessun canonico** | — |
| lo stato dei progetti | volatile | nei singoli `CLAUDE.md` di progetto | chi lavora al progetto |
| il passato | già indicizzato | `archive1777` — si interroga, non si duplica | — |

I due strati locali **non sono nel repo per costruzione** (non `.gitignore`: proprio un altro posto),
entrano nel **backup notturno cifrato** come tutto il volume dati di nb1777-mcp, e non richiedono git: un
utente che installa vps1777 dal bundle li riempie con la CLI e basta. Due esempi con le istruzioni
dentro: [`fatti.esempio.md`](../services/nb1777-mcp/app/memoria_1777/fatti.esempio.md) e
[`errata.esempio.md`](../services/nb1777-mcp/app/memoria_1777/errata.esempio.md).

## Come lo usa una sessione

1. **All'avvio**, se la versione in testa al blocco che porta potrebbe essere vecchia, chiama
   `canonico` (o `doctor`, che lo inietta): riceve `{version, date, note, sede}`.
2. **Il verdetto**: `memoria_check("v2.4")` → `{canonico, stale, delta}`; se è stale, parte un ping
   Telegram all'owner (max 1 per coppia di versioni al giorno).
3. **La cura** (nuova in 0.44.0): `canonico(full=true, taglio="pieno"|"lite"|"micro")` restituisce
   il **testo** della disciplina nel taglio chiesto e i due strati locali, ognuno con la sua
   `origine` (`prodotto · neutra` / `locale · non nel prodotto`). La sessione si allinea **in
   contesto, subito**, senza aspettare che le superfici vengano aggiornate a mano — che restano da
   fare, e va detto a chi parla.
4. **L'ack**: quando l'owner ha aggiornato a mano le superfici cloud (claude.ai non ha connettori
   in ogni Project), lo dichiara con il bottone «✓ Fatto» del bot **o** con il tool `memoria_ack("v2.5")`
   da una sessione. ⚠️ Il tool si chiama **solo su dichiarazione esplicita** («ho incollato»): un ack
   scritto senza il fatto dietro è la dichiarazione senza verifica che la disciplina vieta.

Fino a 0.43 una sessione stale sapeva il **numero** e non il **testo**: il verdetto senza la cura. È
il guadagno vero della migrazione, più della privacy.

## Come lo amministra chi ha la VPS

```bash
vps1777 memoria stato                      # versione della disciplina, strati presenti, ack cloud
vps1777 memoria mostra disciplina          # il canonico che il tool serve (dall'immagine)
cp services/nb1777-mcp/app/memoria_1777/fatti.esempio.md ~/fatti.md && $EDITOR ~/fatti.md
vps1777 memoria importa fatti ~/fatti.md   # carica (sostituisce) lo strato; verifica i byte scritti
vps1777 memoria importa errata ~/errata.md
vps1777 memoria mostra fatti
```

`importa` passa da `docker compose exec` (non `docker cp`): il file nasce dell'utente `app` del
container, scrittura atomica (`.parziale` → `mv`), e l'esito è il **conteggio dei byte riletto dal
volume** confrontato col file, non l'exit code. Uno strato vuoto **non si carica** (cancellerebbe
quello buono in silenzio): per toglierlo, si cancella il file nel volume.

## Versionare la disciplina

- Le regole cambiano → cambia la `vX.Y` nella riga di titolo di `disciplina.md`, si aggiunge una riga
  in «Storia» (data + cosa cambia), e i tre tagli portano in testa la nuova versione. Un test
  (`test_il_file_del_prodotto_esiste_e_si_legge`) lo verifica; un altro
  (`test_il_canonico_del_prodotto_e_neutro`) vieta riferimenti non neutri nei tagli.
- Il bump esce con una release: **il canonico si aggiorna aggiornando vps1777**, per tutti.
- Dopo il bump il bot ricorda all'owner le superfici cloud, finché non arriva l'ack. Le superfici
  su disco (i `CLAUDE.md`) le allinea la prima sessione Claude Code che chiama `canonico(full=true)`
  — o l'owner, incollando il taglio giusto.
- **Lo storico** v2.2 → v2.4 (11-13/07/2026) resta nel notebook NotebookLM `claudemd1777`, in sola
  lettura. Non è un errore che sia là: nel luglio 2026, con un format della VPS imminente, un
  canonico su Google sopravviveva alla macchina e un file *sulla* VPS no. La terza via — un file
  *nel repo*, servito dalla VPS — non era sul tavolo allora; oggi vince su ogni colonna (sopravvive
  al format via GitHub e backup, ha `git log`, non passa da Google, è testato in CI, non dipende da
  `nlm`).

## Cosa NON fa

- Non è memoria: non contiene il passato (è nell'archivio) né lo stato dei progetti.
- Non raggiunge un Project claude.ai **senza** connettore MCP: lì resta la mano dell'owner, e il
  promemoria Telegram è la rete sotto quel buco.
- Non fonde gli strati: `full=true` li restituisce **separati e marcati** — la sessione deve sapere
  cosa è prodotto e cosa è dell'installazione, e non copiare i fatti dentro il blocco.
