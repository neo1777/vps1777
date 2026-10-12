# secrets/ — i valori non entrano MAI in git

Questa cartella contiene i segreti dell'installazione. **I `.txt` sono
gitignorati e nessun valore è mai entrato nella storia del repo** (verificato).
`setup.sh` li genera se mancano o sono vuoti ed è idempotente: non tocca quelli già
pieni (tranne `telegram_webapp_secret.txt`, che ricalcola sempre dal token), quindi
rilanciarlo non invalida un'installazione viva.

| file | a cosa serve | chi lo monta |
|---|---|---|
| `gateway_secret.txt` | il segmento segreto delle URL dei connettori (`/<SECRET>/<servizio>/mcp`) **e** il canale interno verso nb1777-mcp (`/internal/*`: stato **e installazione** dei profili NotebookLM, notifiche del bot) | gateway, nb1777-mcp, bot |
| `archive_desc_secret.txt` | **solo** il canale `set_description` (archive-mcp → gateway) | gateway, archive-mcp |
| `oauth_signing_secret.txt` | firma dei token OAuth | gateway |
| `admin_password_bcrypt.txt` | hash della password admin | gateway |
| `telegram_bot_token.txt` | token del bot | bot |
| `telegram_webapp_secret.txt` | chiave **derivata** dal token (HMAC_SHA256 con chiave «WebAppData») con cui si verifica la Mini App: non si scrive a mano | gateway |
| `cloudflared_token.txt` | token del tunnel (solo ingresso Cloudflare) | cloudflared |
| `cf_api_token.txt` | token API Cloudflare per la sfida DNS-01 (solo feature `caddy-dns01`) | caddy |

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

Per `gateway_secret`, `oauth_signing_secret`, `admin_password` e `telegram_bot_token`
usa `./tools/rotate-secret.sh <nome>`: scrive il valore nuovo e riavvia chi lo monta. Per
il token del bot rideriva anche la chiave della Mini App: cambiare a mano solo il token
la rompe (il bot risponde, la Mini App rifiuta tutti). Ruotare `gateway_secret` cambia
le URL dei connettori, che vanno aggiornate in ogni client.

A mano restano `archive_desc_secret` — sostituisci il contenuto e riavvia gateway e
archive-mcp — e i token Cloudflare, i cui servizi stanno negli overlay (procedura in
[docs/SECRETS.md](../docs/SECRETS.md)). `archive_desc_secret` tocca solo gateway e
archive-mcp: ruotarlo non ha effetti sul resto — che è, in pratica, il vantaggio di
averlo separato.
