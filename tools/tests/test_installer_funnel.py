"""Test della conferma del Funnel nell'installer — `installer/engine.py`.

Perché esiste: `_ts_funnel_ok()` legge `tailscale funnel status` SULLA VPS, cioè la
configurazione che la macchina dichiara su sé stessa. Da quel booleano si concludeva
«✓ Funnel HTTPS attivo» **e si chiudeva la porta 8080** (`step_finalize` guarda
`self.production`): con la configurazione a posto e il tunnel non funzionante,
l'utente restava senza HTTPS *e* senza fallback.

⭐ Il metro è quello del repo: non basta che la sonda sappia dire sì. Deve dare la
risposta giusta sui casi costruiti — compreso quello che deve LASCIAR PASSARE (un 401
del gateway è una conferma: prova che il tunnel porta i byte) e quello strutturale, che
è il vero oggetto del rilievo: **la porta non si chiude su una dichiarazione locale.**

📌 `paramiko` è stubbato: è la sola dipendenza esterna dell'installer, non è dichiarata
in pyproject e in CI non c'è. Senza lo stub questo file non sarebbe importabile — e un
test che non gira è esattamente il presidio che non presidia.
"""
from __future__ import annotations

import ast
import importlib.util
import sys
import types
import urllib.error
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_ENGINE = _ROOT / "installer" / "engine.py"

sys.modules.setdefault("paramiko", types.ModuleType("paramiko"))
_spec = importlib.util.spec_from_file_location("installer_engine", _ENGINE)
eng = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eng)


class _Finto:
    """Il minimo per esercitare il metodo senza una VPS: è una funzione pura di rete."""
    _funnel_confermato_da_qui = eng.Deployer._funnel_confermato_da_qui


def _con_urlopen(monkey):
    import urllib.request
    vecchio = urllib.request.urlopen
    urllib.request.urlopen = monkey
    return vecchio


# ───────────────────────── quello che DEVE confermare ────────────────────────

def test_una_risposta_200_conferma():
    class R:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False
    v = _con_urlopen(lambda *a, **k: R())
    try:
        ok, perche = _Finto()._funnel_confermato_da_qui("https://esempio.ts.net")
        assert ok and "200" in perche, perche
    finally:
        _con_urlopen(v)


def test_un_401_del_gateway_CONFERMA_perche_il_tunnel_porta_i_byte():
    # IL caso che evita il falso rosso garantito: il gateway ha l'autenticazione e su
    # `/` risponde legittimamente 401. Contare solo i 200 avrebbe dichiarato rotto un
    # Funnel perfettamente funzionante — e un gate che grida al lupo viene spento.
    def alza(*a, **k):
        raise urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)
    v = _con_urlopen(alza)
    try:
        ok, perche = _Finto()._funnel_confermato_da_qui("https://esempio.ts.net")
        assert ok, "un 401 deve contare come conferma: il tunnel ha portato i byte"
        assert "401" in perche
    finally:
        _con_urlopen(v)


# ─────────────────────── quello che NON deve confermare ──────────────────────

def test_un_errore_di_rete_non_conferma_e_riprova():
    tentativi = []
    def alza(*a, **k):
        tentativi.append(1)
        raise urllib.error.URLError("Name or service not known")
    v = _con_urlopen(alza)
    try:
        ok, perche = _Finto()._funnel_confermato_da_qui("https://esempio.ts.net", tentativi=2)
        assert not ok
        assert len(tentativi) == 2, f"deve riprovare: un singolo errore di rete è comune ({len(tentativi)})"
        assert perche, "il perché non può essere vuoto: finisce sotto gli occhi dell'utente"
    finally:
        _con_urlopen(v)


def test_senza_url_non_conferma_e_non_interroga_nessuno():
    chiamate = []
    v = _con_urlopen(lambda *a, **k: chiamate.append(1))
    try:
        ok, _ = _Finto()._funnel_confermato_da_qui("")
        assert not ok
        assert not chiamate, "senza URL non si interroga nulla"
    finally:
        _con_urlopen(v)


# ────────── il caso STRUTTURALE, ed è il vero oggetto del rilievo ────────────

def test_la_porta_non_si_chiude_su_una_dichiarazione_locale():
    """`production = True` non può essere raggiunto senza la conferma dall'esterno.

    Provato sull'AST e non sul flusso: esercitare `step_tailscale_host` richiederebbe
    una VPS vera. Qui la domanda è di STRUTTURA — «esiste un cammino che chiude la
    porta 8080 fidandosi solo di `tailscale funnel status`?» — e sulla struttura si
    risponde leggendo l'albero, senza simulare mezza rete.
    """
    albero = ast.parse(_ENGINE.read_text(encoding="utf-8"))
    for fn in ast.walk(albero):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        assegna = [n for n in ast.walk(fn)
                   if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Attribute) and t.attr == "production"
                           for t in n.targets)
                   and isinstance(n.value, ast.Constant) and n.value.value is True]
        if not assegna:
            continue
        conferme = [n.lineno for n in ast.walk(fn)
                    if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "_funnel_confermato_da_qui"]
        for a in assegna:
            assert conferme, (
                f"{fn.name}: mette production=True senza chiamare mai "
                f"_funnel_confermato_da_qui — la porta 8080 si chiuderebbe su una "
                f"dichiarazione locale"
            )
            assert min(conferme) < a.lineno, (
                f"{fn.name}: production=True alla riga {a.lineno} precede la conferma "
                f"esterna (riga {min(conferme)})"
            )


def test_la_sonda_locale_non_e_piu_usata_da_sola():
    # Il verso opposto del precedente: se qualcuno rimettesse `_ts_funnel_ok()` come
    # unico guardiano, il test sopra cadrebbe — ma solo se production=True resta. Qui
    # si fissa l'altra metà: la sonda locale esiste ancora ed è documentata come
    # insufficiente, così chi la legge non la riusa credendola completa.
    assert "_ts_funnel_ok" in _ENGINE.read_text(encoding="utf-8")
    doc = eng.Deployer._ts_funnel_ok.__doc__ or ""
    assert "non basta" in doc.lower(), (
        "la sonda locale deve dichiarare nel suo docstring che da sola non basta"
    )


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {name}")
            except Exception as exc:  # noqa: BLE001
                fails += 1
                print(f"FAIL {name}: {exc}")
    raise SystemExit(1 if fails else 0)
