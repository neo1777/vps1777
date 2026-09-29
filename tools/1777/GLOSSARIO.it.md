# GLOSSARIO — le sigle del contratto 1777

> 🇬🇧 English: [GLOSSARIO.md](GLOSSARIO.md). Questo file è il sorgente italiano;
> l'inglese è la sua traduzione.

Le sigle di AGENTS.md e di RIGHE.md dicono da quale decisione del template viene una regola.
Le decisioni stanno nei documenti di lavoro di chi ha scritto il template (27-29/09/2026), che non
sono pubblicati: qui c'è quello che serve per leggerle. «n» sta per un numero.
`mise run check` è rosso se un documento usa una sigla che qui manca.

| sigla | cosa vuol dire |
|---|---|
| DD-P8.n | una decisione di design del template: .1 la tabella delle righe, .2 il grado di un cancello di giudizio, .3 il file per gli agenti, .6 distribuzione e aggiornamento, .7 i file per i contributori, .8 il contratto dei comandi e lo scheletro, .9 il controllo di conformità |
| Ka.n | le righe della DD-P8.8 sul contratto: .1 i 7 comandi, .3 `setup` idempotente, .4 e .11 una description per ogni task, .5 la versione di mise fissata, .6 gli scheletri per stack, .7 ogni task delega allo strumento dello stack, .8 il retrofit e il passo d'adozione, .9 gli argomenti dei test, .10 i segreti, .12 la radice di composizione nei Dart |
| Kb.n | le righe della DD-P8.8 sui test: .1 il filtro che non trova niente esce ≠0, .2 nessun test senza asserzioni |
| Kc.n | le righe della DD-P8.8 sull'hook di git: .1 la prova a tre tempi, .2 la cartella comune di git, .3 `prepare` nei TS, .4 niente test completo nell'hook, .5 `setup` installa l'hook |
| K-a, K-b | i due blocchi della DD-P8.8: K-a il contratto sopra scheletri per stack (la CI chiama solo i comandi del contratto), K-b il test col filtro vuoto |
| K5 | la lingua dei documenti per i contributori (la quinta voce della DD-P8.7) |
| AP.n | punti aperti, poi decisi: .1 C3 si deriva, .2 C5 solo dove c'è un ciclo, .3 il triage è un cancello e non una colonna, .5 un controllo mai visto rosso si chiama «proposto» |
| Cn | le colonne della tabella di RIGHE.md: C1 tipi, C2 grado e raggio, C3 visto rosso, C4 fatto o valore, C5 ciclo, C6 via d'uscita, C7 gemello, C8 fonte e data, C9 il triage, C10 attore e test |
| R.1 | ogni rito che trova qualcosa lo deposita in un registro che un controllo legge |
| M.1 | mise come strumento per toolchain e comandi, con le sue vie d'uscita |
| D1 | copier senza codice del template eseguito (niente `_tasks`, `_migrations`, `_jinja_extensions`) |
| Tn | le ricerche che hanno preparato le decisioni: T1 gli scheletri, T3 mise e just, T4 gli hook di git, T7 il retrofit e i segreti |
| Pr.n | le precisazioni scritte nelle righe dello scheletro: Pr.4 `expectLater` nei Dart, Pr.8 `.env.example` nei client Flutter |
| F.n | le frizioni della prima prova del template su un repo vero (vps1777, 29/09/2026): F.2 un file nominato che non c'era, F.3 un `run` che Tera non legge, F.4 il python di mise che copre quello di sistema, F.7 il marcatore dell'hook, F.8 uno step apt in CI, F.9 `_src_path` con una cartella di casa |
| F2.n | le frizioni della seconda prova (29/09/2026): F2.3 documenti in una lingua sola e sigle che fuori non si leggono, F2.4 il python di uv e il runner della CI non fissati |
