"""Un comando che esce ≠0 lo DICE, e l'avviso non può rompere il comando.

🔴 MISURATO il 03/08 (`b82df434`): il timer dell'auto-update è fallito alle 04:32, la
macchina è rimasta alla `0.40.14` con il bundle della `0.41.0` già scaricato — e
**nessuno l'ha saputo per dieci ore**. L'ha scoperto lei andando a leggere il journal,
non un avviso.

⇒ *Un auto-update che non aggiorna **e non lo dice** è peggio di un auto-update assente:
il secondo lo si sa, e si aggiorna a mano.*

🔑 **Perché nel CLI e non con `OnFailure=` nella unit**, che sarebbe la via
systemd-nativa: le unit nascono da tre installer e il loro elenco vive in almeno tre
posti. Aggiungere una unit destinataria significa toccarli tutti — la classe curata
oggi per la quarta volta sullo stesso blocco di hardening. **Qui è un punto solo, e
copre ogni modo di lanciare il comando: il timer, la mano, il pulsante admin.**

⚠️ E il limite di questa scelta è dichiarato nel codice: `OnFailure=` prenderebbe anche
il caso in cui il processo muoia **senza arrivare a quella riga** (OOM, SIGKILL,
timeout di systemd) — cioè il caso in cui la macchina sta peggio. *Questa cura non lo
copre.*

Stile stdlib-only: la CI esegue `tools/tests/` con `uvx pytest` senza dipendenze.
"""
from __future__ import annotations

import ast
from pathlib import Path

SRC = (Path(__file__).resolve().parents[1] / "vps1777.py").read_text(encoding="utf-8")


def _funzione(nome: str) -> ast.FunctionDef:
    """Il nodo `ast` di UNA funzione, per provarla senza importare il modulo.

    `vps1777.py` fa lavoro all'import e tira dentro il mondo: importarlo qui
    romperebbe la raccolta, e una suite che non raccoglie un test è verde.
    """
    albero = ast.parse(SRC)
    for n in ast.walk(albero):
        if isinstance(n, ast.FunctionDef) and n.name == nome:
            return n
    raise AssertionError(f"funzione {nome} non trovata: il test legge un file che non conosce")


def test_esiste_un_punto_unico_di_uscita_e_il_main_ci_passa():
    _funzione("_esci")
    # Il `__main__` deve usarlo: una funzione d'uscita che nessuno chiama è
    # esattamente il difetto trovato oggi due volte (classify_voice con nove test e
    # zero chiamanti, e `verifica()` del journal caldo).
    assert "_esci(main())" in SRC, (
        "`_esci` esiste ma il blocco __main__ non la usa: sarebbe codice presente e "
        "mai eseguito, che si legge come coperto"
    )
    assert "sys.exit(main())" not in SRC, (
        "il vecchio `sys.exit(main())` è ancora lì: se restano entrambi, quale dei due "
        "gira dipende da quale riga viene dopo — e non si vede leggendo"
    )


def test_avvisa_SOLO_quando_il_codice_e_diverso_da_zero():
    """Un avviso a ogni uscita sarebbe rumore, e il rumore si disattiva da solo."""
    f = _funzione("_esci")
    ifs = [n for n in ast.walk(f) if isinstance(n, ast.If)]
    assert ifs, "nessun ramo condizionale in _esci: avviserebbe anche sui successi"
    # Il primo `if` deve confrontare il codice con zero.
    testo = ast.dump(ifs[0].test)
    assert "codice" in testo and ("0" in testo or "Eq" in testo or "NotEq" in testo), (
        f"il ramo dell'avviso non è condizionato al codice d'uscita: {testo[:120]}"
    )


def test_un_avviso_che_FALLISCE_non_rompe_il_comando():
    """La proprietà che conta di più, e la sola che si può sbagliare in silenzio.

    *Un canale d'allarme che fa fallire ciò che sorveglia trasforma un problema in
    due* — e il secondo arriverebbe proprio quando il primo sta già succedendo.
    """
    f = _funzione("_esci")
    handlers = [n for n in ast.walk(f) if isinstance(n, ast.ExceptHandler)]
    assert handlers, (
        "nessun try/except attorno alla notifica: se il bot è irraggiungibile o il "
        "token manca, l'eccezione dell'AVVISO diventerebbe l'esito del COMANDO"
    )
    # L'except dev'essere LARGO: uno stretto sceglierebbe quali guasti dell'allarme
    # possono rompere il comando, e non ce n'è nessuno che debba poterlo fare.
    tipi = [getattr(h.type, "id", None) for h in handlers]
    assert "Exception" in tipi or None in tipi, (
        f"l'except attorno alla notifica è ristretto a {tipi}: un guasto non previsto "
        f"del canale d'allarme romperebbe il comando che sta sorvegliando"
    )


def test_l_uscita_avviene_COMUNQUE_dopo_il_tentativo_di_avviso():
    """`sys.exit(codice)` deve stare FUORI dal try, o un avviso riuscito potrebbe
    mangiarsi l'uscita e uno fallito cambiarne il codice."""
    f = _funzione("_esci")
    corpo_finale = f.body[-1]
    assert isinstance(corpo_finale, ast.Expr) and isinstance(corpo_finale.value, ast.Call), (
        "l'ultima istruzione di _esci non è una chiamata: l'uscita dev'essere l'ultimo "
        "gesto, dopo il tentativo di avviso e fuori dal suo try"
    )
    # ⚠️ NON si cerca la stringa "sys.exit" nel dump: lì `sys.exit(x)` compare come
    #   `Name(id='sys')` + `attr='exit'`, e la stringa intera NON ESISTE. La prima
    #   versione di questo assert la cercava e dava rosso su un codice giusto —
    #   *la sonda cercava una forma che il suo bersaglio non ha mai*.
    d = ast.dump(corpo_finale)
    assert "id='sys'" in d and "attr='exit'" in d, (
        f"l'ultima istruzione non è sys.exit: il comando potrebbe non uscire col "
        f"codice vero. Trovato: {d[:120]}"
    )


def test_il_messaggio_dice_COSA_non_e_successo_non_solo_che_e_fallito():
    """«è fallito» manda a cercare; «la macchina NON è stata aggiornata» dice il danno.

    È la stessa differenza fra il vecchio `ask.sh` — che diceva «backend
    irraggiungibile» e non dove andare — e quello curato oggi.
    """
    f = _funzione("_esci")
    testo = ast.dump(f)
    assert "NON è stata aggiornata" in testo or "NON e' stata aggiornata" in testo, (
        "il messaggio non nomina la conseguenza: chi lo legge sa che qualcosa è uscito "
        "≠0, non che la macchina è rimasta indietro"
    )
    assert "journalctl" in testo, (
        "il messaggio non dice dove guardare: un avviso che non porta al passo "
        "successivo lascia il lavoro a chi lo riceve"
    )
