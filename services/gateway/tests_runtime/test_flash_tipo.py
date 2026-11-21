"""Giro di revisione del 21/11/2026: il tipo del messaggio (`?kind=`) non entra nell'HTML com'è.

Prima `_layout` lo scriveva nell'attributo `class`: un link costruito apposta chiudeva il div e
apriva un <form> suo, che nel browser dell'admin si portava via il campo csrf della pagina.
Deps del lock (admin vero)."""
from __future__ import annotations

from app import admin

OSTILE = 'ok"></div><form method="POST" action="/admin/setup"><input name="x">'


def _html(tipo: str) -> str:
    return admin._layout("t", "<p>corpo</p>", flash="salvato", flash_kind=tipo).body.decode()


def test_un_tipo_ostile_non_esce_dalla_classe():
    h = _html(OSTILE)
    assert 'action="/admin/setup"' not in h and "<input name=" not in h
    assert '<div class="flash ok">salvato</div>' in h


def test_i_due_tipi_veri_restano():
    assert '<div class="flash err">salvato</div>' in _html("err")
    assert '<div class="flash ok">salvato</div>' in _html("ok")
    assert '<div class="flash ok">salvato</div>' in _html("qualunque")
