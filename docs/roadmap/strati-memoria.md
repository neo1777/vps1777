# Strati di memoria — roadmap (non prodotto)

> **Cos'è questo documento.** Le due iniziative che riguardano la **memoria a
> strati** di Neo, emerse dal *paper su archive1777* (§7 "la memoria a strati").
> Come il doc [skill-sopra-archivio](skill-sopra-archivio.md): sono **istruzioni
> da studiare e completare**, non codice di prodotto. Vivono a cavallo tra
> `bibliotecario1777`, il NotebookLM e (per Stregatto) un progetto a sé.
>
> **Stato:** bozza. L'approfondimento con ricerca reale è per una sessione
> dedicata. [paper] = dal paper · [inferenza] = da validare · [aperto] = filo
> aperto dichiarato da Neo, poco documentato: da ricostruire in sessione.

## Il quadro: la freschezza scalare

Il paper ha misurato che **ogni strato di memoria è una fotografia che si
stinge**, a velocità diverse [paper §7]:

| Strato | Natura | Freschezza misurata |
|---|---|---|
| `nb_list` / `doctor` (live) | stato reale | oggi |
| notebook di dominio (es. vps-1777) | memoria semantica curata | ~aggiornata |
| archivio, ramo Telegram | memoria episodica verbatim | lag ~1 giorno |
| archivio, ramo claude-ai | memoria episodica verbatim | lag ~2-4 giorni |
| **catalogo `masterIndex1777`** | mappa dell'account | **fermo (mesi)** |
| skill descriptions | indice degli indici | a release |

**Scoperta centrale:** il **delta tra strati è esso stesso il segnale
diagnostico**. Lo strato *pensato per orientare* (il catalogo) è il più stantio:
interrogato su vps1777 rispondeva con l'architettura della generazione precedente
(systemd/mcp1777) mentre vps1777 è ormai Docker+OAuth. [paper §7]

---

## B1 — Sync automatico del masterIndex1777

**Cosa fa.** Mantiene **aggiornato il catalogo** `masterIndex1777` (il notebook
NotebookLM che indicizza *cosa c'è e dove* nell'account), oggi curato a mano e
quindi fermo. Vive in **`bibliotecario1777`** (il bibliotecario dell'account
NotebookLM), che è già la skill responsabile del catalogo. [paper §7, §11 racc. 8]

**Il problema che risolve.** Il paper ha osservato che il sync del bibliotecario
**non gira da settimane**: il catalogo descrive un'architettura superata. È
esattamente il "secondo tempo" (curare, connettere, ricordare) che `agora1777`
dice che Neo salta sistematicamente — e che rende gratis il primo tempo. Neo
stesso aveva già chiesto questo sync il 7 giugno. [paper §7; agora1777]

**Come funziona (traccia).** [inferenza — da validare in sessione]
- `nb_list` / `nb_describe` / `cross_notebook_query` per fotografare lo stato
  reale dell'account (contenuto, non titoli — lezione di agora1777).
- Diff contro il masterIndex corrente → cosa è nuovo, rinominato, sparito.
- Aggiornamento **incrementale e datato** del catalogo (estende, non riscrive —
  Principio 9 di `setaccio`).
- Possibile trigger: on-demand da `bibliotecario1777`, o schedulato.

**Da decidere in sessione.** Se è puramente una procedura di `bibliotecario1777`
o se merita automazione (cron/skill); come si àncora alla disciplina di
freschezza (ogni voce del catalogo datata); il rapporto con **B2** (se Stregatto
diventa il quarto strato, il catalogo deve indicizzarne la freschezza).

**Confine.** **Non è vps1777**: tocca NotebookLM e il bibliotecario, non il
server. vps1777 lo cita solo come contesto (l'archivio è uno degli strati che il
catalogo dovrebbe mappare).

**Stato:** problema attivo e ben circoscritto; caso d'uso già misurato dal paper.

---

## B2 — Stregatto v2 come quarto strato (memoria vettoriale)

**Cosa fa.** Aggiunge una **memoria semantica/vettoriale** accanto agli strati
esistenti — archivio (episodico verbatim), NotebookLM (curato), skill
descriptions (indice) — basata su **Stregatto** (Cheshire Cat AI), nella sua
**v2**. [aperto — filo di Neo dell'8 lug: "memoria per vps1777 via Stregatto v2";
paper §12 "future work"]

**Il problema che risolve.** [inferenza] L'archivio FTS5 è potente sul *match
lessicale* (parole esatte, con le trappole documentate: quoting, doppia lingua,
niente stemming). Una memoria **vettoriale** aggiunge il *match semantico* —
trovare per significato anche senza le parole giuste — che è complementare, non
sostitutivo. Il paper chiude proprio suggerendo "Stregatto v2 come quarto strato,
con la stessa disciplina di freschezza".

**Cosa serve ricostruire in sessione (è il punto più aperto).**
- **Cos'è "Stregatto v2" per Neo**: quale versione/fork, cosa cambia dalla v1,
  dove gira (locale? vps1777? un container a sé?), quale interfaccia.
- Il rapporto con vps1777: strato **dentro** l'ecosistema (un altro MCP dietro il
  gateway?) o servizio **parallelo**.
- La disciplina di freschezza applicata a un indice vettoriale (quando si
  re-embedda, come si data uno snapshot semantico).
- Il costo (embedding, storage, risorse — la VPS è 4GB; vincolo hardware già
  visto per l'OCR).

**Come approfondire.** Ricerca su `archive1777` di tutto ciò che Neo ha già
scritto su "stregatto"/"cheshire"/"memoria vettoriale" (usa il *protocollo dello
zero* e le due lingue), più lo stato attuale del progetto Stregatto upstream.

**Confine.** Probabilmente il **più grande** dei fronti e il più indipendente:
va trattato come progetto a sé, non come feature vps1777.

**Stato:** filo aperto poco documentato → la sessione dedicata inizia con la
**ricostruzione** prima della progettazione.

---

## Fonti

- *Paper sperimentale su archive1777* (2026-07-11), §7, §9, §12.
- Skill: `bibliotecario1777`, `agora1777`, `setaccio` (`~/.claude/skills/`).
- Memoria di progetto: `vps1777-archive-mcp-search`.
- Da recuperare in sessione: il filo "Stregatto v2 / memoria vps1777" (8 lug) via
  `archive1777` + stato upstream di Cheshire Cat AI.
