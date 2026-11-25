"""`classify_voice`, regola ⑤: la quota di righe citate (25/11/2026, QUA-04).

Le prove non percorrevano i due rami della quota: la bandiera `quote_fence` da metà in su, e il
verdetto `mixed` quando la prosa propria scende sotto il 30%.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import archive_indexer as ai  # noqa: E402


def test_meta_citato_alza_la_bandiera_ma_resta_voce_propria():
    testo = "guarda cosa mi ha risposto\n> prima riga citata\ne io non sono d'accordo\n> seconda riga citata"
    voce, quota, conf, bandiere = ai.classify_voice(testo, "human", "")
    assert (voce, quota, bandiere) == ("own", 0.5, ["quote_fence"])
    assert conf == 0.5, "con una bandiera alzata la confidenza scende"


def test_quasi_tutto_citato_e_mixed():
    testo = "ecco\n" + "\n".join(f"> riga citata numero {i}" for i in range(4))
    voce, quota, conf, bandiere = ai.classify_voice(testo, "human", "")
    assert (voce, quota, conf, bandiere) == ("mixed", 0.8, 0.5, ["quote_fence"])


def test_senza_citazioni_un_mittente_sconosciuto_resta_unknown():
    assert ai.classify_voice("una frase qualunque", "boh", "") == ("unknown", 0.0, 0.0, [])
