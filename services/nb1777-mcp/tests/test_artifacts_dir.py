"""artifacts_dir — la directory nasce, e se non è scrivibile LO DICE (caso del 05/09).

Il caso vivo: il volume di produzione era root:root e ogni `studio_download`
moriva nel generico «Download failed» di nlm, senza diagnosi. La cura non è solo
il chown nel Dockerfile: è il fallimento PARLANTE prima di invocare nlm — questo
file prova entrambi i versi (il sano deve riuscire, il rotto deve spiegare).
"""
from __future__ import annotations

import os

import pytest

from app import core


def test_nasce_se_manca_ed_e_scrivibile(tmp_path, monkeypatch):
    dest = tmp_path / "artefatti"
    monkeypatch.setenv("NLM_ARTIFACTS", str(dest))
    p = core.artifacts_dir()
    assert p == dest and p.is_dir()


def test_non_scrivibile_fallisce_parlando(tmp_path, monkeypatch):
    if os.getuid() == 0:
        pytest.skip("da root ogni directory è scrivibile: il caso non è costruibile")
    dest = tmp_path / "sola-lettura"
    dest.mkdir()
    dest.chmod(0o555)
    monkeypatch.setenv("NLM_ARTIFACTS", str(dest))
    try:
        with pytest.raises(core.NLMError) as ex:
            core.artifacts_dir()
        # la diagnosi deve dire COSA non va e COME si cura, non solo che fallisce
        assert "scrivibile" in str(ex.value) and "chown" in str(ex.value)
    finally:
        dest.chmod(0o755)
