# secrets/ — i valori non entrano MAI in git

Questa cartella contiene i segreti dell'installazione. **I `.txt` sono
gitignorati e nessun valore è mai entrato nella storia del repo** (verificato).
`setup.sh` li genera se mancano ed è idempotente: non tocca i file già presenti,
quindi rilanciarlo non invalida un'installazione viva.

| file | a cosa serve | chi lo monta |
|---|---|---|
| `gateway_secret.txt` | canale interno gateway ↔ upstream (`/internal/nlm/*`: stato **e installazione** dei profili NotebookLM) | gateway, nb1777-mcp, bot |
| `archive_desc_secret.txt` | **solo** il canale `set_description` (archive-mcp → gateway) | gateway, archive-mcp |
| `oauth_signing_secret.txt` | firma dei token OAuth | gateway |
| `admin_password_bcrypt.txt` | hash della password admin | gateway |
| `telegram_bot_token.txt` | token del bot | bot |

## Perché due segreti e non uno (D9, 20/07/2026)

`archive_desc_secret` è **deliberatamente separato** da `gateway_secret`.
Riusare quest'ultimo sarebbe stato più comodo — ed è ciò che la prima
implementazione aveva fatto — ma quel segreto apre anche il canale dei profili
NotebookLM: montarlo su `archive-mcp`, per una funzione che scrive un campo di
testo, significa che un `archive-mcp` compromesso eredita **anche quel potere**.
Privilegio minimo, anche fra servizi di casa: si riusa il *pattern*, non il
*segreto*.

Non c'è fallback dell'uno sull'altro: se `archive_desc_secret` manca, il canale
non scrive (fail-closed). Un fallback silenzioso rimetterebbe in piedi l'esatto
ampliamento di privilegio che questa separazione esiste per evitare.

## Se manca un file

Lo stack **non parte** (il compose dichiara il secret) → health-gate rosso →
auto-rollback. Sembra una release rotta, ma manca solo un file: rilancia
`setup.sh`, che lo genera senza toccare gli altri.
Un file **vuoto** è peggio di uno assente: lo stack parte e il canale resta
fail-closed, cioè un difetto di provisioning travestito da bug del codice.

## Rotazione

Sostituire il contenuto e riavviare i servizi che lo montano (tabella sopra).
`archive_desc_secret` tocca solo gateway e archive-mcp: ruotarlo non ha
effetti sul resto — che è, in pratica, il vantaggio di averlo separato.
