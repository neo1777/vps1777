"""Le cure nate dalla sesta fetta della revisione col catalogo: gli strumenti attorno alla CLI
(indice, controlli dei documenti, hook, script di backup e rotazione)."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
TOOLS = _ROOT / "tools"


def _carica(nome_file: str):
    spec = importlib.util.spec_from_file_location("_fetta06_" + nome_file.replace("-", "_").removesuffix(".py"),
                                                  TOOLS / nome_file)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


ix = _carica("indice_semantico.py")


def _esito(codice=0, out="", err=""):
    return subprocess.CompletedProcess([], codice, out, err)


# ── indice_semantico ────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("risposta, atteso", [(_esito(0, "c-e\n"), True), (_esito(0, "non-c-e\n"), False)])
def test_l_indice_remoto_c_e_o_non_c_e(risposta, atteso):
    assert ix.esiste_remoto("host", "cont", "/x/y.vec.db", lambda *a, **k: risposta) is atteso


@pytest.mark.parametrize("risposta", [_esito(255, "", "ssh: connessione rifiutata"), _esito(0, ""),
                                      _esito(1, "", "container non in esecuzione")])
def test_se_non_si_riesce_a_saperlo_ci_si_ferma(risposta):
    """Prima un errore di ssh valeva «non esiste», e con --tutto si ricostruiva da zero."""
    with pytest.raises(ix.Fallito, match="non ho potuto sapere"):
        ix.esiste_remoto("host", "cont", "/x/y.vec.db", lambda *a, **k: risposta)


def test_dopo_il_caricamento_si_rilegge_l_impronta(tmp_path):
    vec = tmp_path / "a.vec.db"
    vec.write_bytes(b"indice")
    giusta = ix._sha256(vec)

    def esegui_con(sha):
        def esegui(cmd, **k):
            testo = " ".join(cmd)
            return _esito(0, f"{sha}  /x\n") if "sha256sum" in testo else _esito(0)
        return esegui

    ix.carica("host", "cont", vec, esegui_con(giusta))                    # combacia: nessun errore
    with pytest.raises(ix.Fallito, match="impronta diversa"):
        ix.carica("host", "cont", vec, esegui_con("0" * 64))


# ── i controlli dei documenti: zero esaminati non è un verde ────────────────────────────────

def test_nomi_nei_doc_senza_documenti_e_non_misurato(monkeypatch, capsys):
    nomi = _carica("nomi-nei-doc.py")
    monkeypatch.setattr(nomi, "contesto", lambda: {})
    monkeypatch.setattr(nomi, "_git_ls", lambda *a: [])
    monkeypatch.setattr(nomi, "RADICE", Path("/percorso/che/non/esiste"))
    assert nomi.main() == 2
    assert "NON MISURATO" in capsys.readouterr().out


def test_doc_riferimenti_senza_riferimenti_e_non_misurato(monkeypatch, capsys):
    rif = _carica("doc-riferimenti.py")
    monkeypatch.setattr(rif, "analizza", lambda *a: ({"esatti": 0, "assoluti": 0, "runtime": 0,
                                                     "imprecisi": 0}, {}, {}, 0))
    monkeypatch.setattr(sys, "argv", ["doc-riferimenti.py"])
    assert rif.main() == 2
    assert "NON MISURATO" in capsys.readouterr().out


def test_coordinate_nei_doc_zero_su_zero_e_non_misurato():
    src = (TOOLS / "coordinate-nei-doc.py").read_text(encoding="utf-8")
    i = src.index("if tot == 0:")
    assert "return 2" in src[i:i + 300] and i < src.index('print(f"✅ {tot} su {tot}')


# ── verify-features ─────────────────────────────────────────────────────────────────────────

def test_un_verify_cmd_che_non_finisce_e_un_fallimento_parlante(monkeypatch):
    vf = _carica("verify-features.py")
    monkeypatch.setattr(vf, "CMD_TIMEOUT_S", 1)
    ok, perche = vf.run_check({"cmd": "sleep 5"}, _ROOT)
    assert ok is False and "non ha finito" in perche
    src = (TOOLS / "verify-features.py").read_text(encoding="utf-8")
    assert "timeout=CMD_TIMEOUT_S" in src and "BOZZA per tools/verify-features.py" not in src
    assert "datetime.timezone.utc).date()" in src


# ── script: le proprietà si leggono nel sorgente (girano contro docker e ssh veri) ──────────

def test_il_restore_guarda_che_lo_stack_sia_fermo_prima_di_svuotare():
    src = (TOOLS / "restore.sh").read_text(encoding="utf-8")
    i_down = src.index("docker compose down --remove-orphans")
    i_guarda = src.index("docker compose ps -q")
    i_svuota = src.index("rm -rf /dst/*")
    assert i_down < i_guarda < i_svuota and "non tocco i volumi" in src[i_guarda:i_guarda + 400]


def test_la_rotazione_scrive_i_segreti_tutto_o_niente_e_non_mostra_il_token():
    src = (TOOLS / "rotate-secret.sh").read_text(encoding="utf-8")
    codice = "\n".join(r for r in src.splitlines() if not r.lstrip().startswith("#"))
    assert 'echo -n "$NEW" > "$FILE"' not in codice and 'echo -n "$TOK" > "$FILE"' not in codice
    assert codice.count('scrivi_segreto "$FILE"') == 3 and "mv -f \"$tmp\" \"$1\"" in codice
    assert "read -rs TOK" in codice and "read -r TOK" not in codice


def test_il_pull_dei_backup_ha_un_tempo_massimo_e_non_lascia_pezzi_col_nome_buono():
    src = (TOOLS / "backup-pull.sh").read_text(encoding="utf-8")
    assert "--partial-dir=.rsync-parziale" in src and "--timeout=300" in src
    assert "ConnectTimeout=20" in src


def test_l_hook_non_porta_percorsi_personali_e_ferma_i_conflitti():
    src = (TOOLS / "hooks" / "pre-commit").read_text(encoding="utf-8")
    codice = "\n".join(r for r in src.splitlines() if not r.lstrip().startswith("#"))
    assert "Scrivania" not in codice and "mcp_dash" not in codice
    assert "git config --get vps1777.gate-locale" in codice
    assert "marcatori di conflitto" in codice and "exit 1" in codice[codice.index("_CONFLITTI"):]


# ── i README non promettono garanzie senza una prova accanto ────────────────────────────────

def test_i_readme_non_usano_il_lessico_delle_garanzie_assolute():
    """«Sicuro», «secure», «safe», «certificato», «military-grade», «quantum-safe» in una pagina
    pubblica sono una promessa: o hanno accanto il rimando alla prova, o non ci stanno. Qui la
    regola è la più semplice: nei due README quelle parole non compaiono (i sostantivi
    «sicurezza» e «security» sì: nominano l'argomento, non lo garantiscono)."""
    import re
    lessico = re.compile(r"\b(sicur[oaie]|secure|safe|certificat[oaie]|certified|military[- ]grade|"
                         r"quantum[- ]safe|resistente al quantum)\b", re.I)
    for nome in ("README.md", "README.it.md"):
        testo = (_ROOT / nome).read_text(encoding="utf-8")
        trovate = [f"{nome}:{n}: {r.strip()[:90]}" for n, r in enumerate(testo.splitlines(), 1)
                   if lessico.search(r)]
        assert not trovate, "frasi-garanzia senza prova nei README:\n" + "\n".join(trovate)
