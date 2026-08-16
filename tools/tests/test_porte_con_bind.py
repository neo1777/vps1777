"""Ogni porta pubblicata dai compose dichiara SU QUALE INTERFACCIA — mai nuda.

🔴 PERCHÉ ESISTE (10/08, voce `31513bb8` di b82df434, misura di 71d540e6):
  `compose.dev.yaml` pubblicava `"8080:8080"`, `"8002:8002"`, `"8003:8003"` — senza
  `host_ip`, Docker pubblica su TUTTE le interfacce. Su una macchina in LAN o su un
  wifi pubblico i tre backend erano raggiungibili da chiunque, senza il gateway
  davanti e senza l'autenticazione dell'ingress. Era l'unico overlay del repo a farlo:
  gli altri due usano già `${GATEWAY_BIND:-127.0.0.1}` / `${ONBOARDING_BIND:-127.0.0.1}`.

⭐ E LA CURA DA SOLA NON BASTAVA — rilievo di b82df434 mentre la PR era aperta:
  **nessun presidio guardava i compose.** `prova-7-porta-pubblicata-davvero.sh` non ne
  nomina nessuno. Curare le tre righe senza questo test lascia il difetto libero di
  tornare al prossimo overlay, e nessuno se ne accorgerebbe: *una cura senza presidio
  è una cura con una data di scadenza che nessuno ha scritto.*

⚠️ IL PERIMETRO È UN GLOB, NON UNA LISTA — ereditato da `test_nlm_auth_montaggi.py`
  (#140): se domani nasce `compose.qualcosa.yaml` con una porta nuda, qui è ROSSO senza
  che nessuno debba ricordarsi di aggiungerlo. Una lista scritta a mano tace su chi non
  è in lista; un glob no.

🔴 SOLO STDLIB, e non è una preferenza: in `tools/tests` PyYAML non c'è. La CI di
  stanotte è andata rossa esattamente così — il repo *usa* PyYAML, ma dentro un
  `uv run --with pyyaml` che è un altro job. Una dipendenza disponibile in un job non
  è disponibile in tutti.
"""

from __future__ import annotations

import glob
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]

# Una voce di `ports:` è NUDA quando è `"8080:8080"` o `8080:8080` — cioè quando prima
# della prima coppia non c'è né un IP né una variabile. Le forme coperte:
#   "127.0.0.1:9443:9443"          bind fisso          (compose.ops.portainer.yaml)
#   "${GATEWAY_BIND:-127.0.0.1}:8080:8080"   default sicuro + override esplicito
_PORTA_NUDA = re.compile(r'^\s*-\s*"?(\d+):(\d+)(?:/\w+)?"?\s*(?:#.*)?$')


def _compose_files() -> list[Path]:
    files = [Path(p) for p in glob.glob(str(_ROOT / "compose*.yaml"))]
    files += [Path(p) for p in glob.glob(str(_ROOT / "plugins" / "*" / "compose*.yaml"))]
    return sorted(files)


def porte_nude(righe: list[str]) -> list[tuple[int, str]]:
    """(numero_riga, testo) di ogni porta pubblicata senza interfaccia.

    Si entra in `ports:` e si esce alla prima chiave allo stesso livello o più esterna:
    senza questo, un `- "8080:8080"` dentro `command:` o `environment:` verrebbe contato.
    """
    fuori: list[tuple[int, str]] = []
    dentro = False
    indent_ports = 0
    for n, r in enumerate(righe, 1):
        spoglio = r.rstrip()
        if not spoglio or spoglio.lstrip().startswith("#"):
            continue
        indent = len(spoglio) - len(spoglio.lstrip())
        if re.match(r"^\s*ports:\s*$", spoglio):
            dentro, indent_ports = True, indent
            continue
        if dentro:
            # una riga che non è un elemento di lista, o rientra al livello di `ports:`,
            # chiude il blocco
            if not spoglio.lstrip().startswith("-") or indent <= indent_ports:
                dentro = False
                continue
            if _PORTA_NUDA.match(spoglio):
                fuori.append((n, spoglio.strip()))
    return fuori


# 🖐️ L'ECCEZIONE, e si dichiara invece di allargare la regola.
# Il primo giro di questo test è andato ROSSO su `compose.ingress.caddy.yaml` (80, 443) —
# e aveva torto: Caddy È l'ingress, deve rispondere da Internet, è il suo mestiere.
# ⭐ Una guardia che blocca il legittimo si finisce per disattivarla, e allora non
# protegge più nemmeno dove serviva. Ma l'eccezione va NOMINATA: qui sotto si vede chi
# è pubblico per disegno, e chiunque altro resta rosso — *il default severo non si
# tocca, si elenca chi ne esce e perché.*
# ⚠️ Enumerata a mano di proposito: chi non è in questa lista NON tace, GRIDA. È la
# differenza fra una lista che nasconde e una che espone.
_PUBBLICHE_PER_DISEGNO = {
    ("compose.ingress.caddy.yaml", "80"),    # HTTP  → redirect a HTTPS, ACME http-01
    ("compose.ingress.caddy.yaml", "443"),   # HTTPS → è l'ingress: sta davanti al gateway
}


@pytest.mark.parametrize("f", _compose_files(), ids=lambda p: p.name)
def test_nessuna_porta_senza_interfaccia(f: Path) -> None:
    nude = [(n, t) for n, t in porte_nude(f.read_text(encoding="utf-8").splitlines())
            if (f.name, _PORTA_NUDA.match(" " + t).group(1)) not in _PUBBLICHE_PER_DISEGNO]
    assert not nude, (
        f"{f.name}: {len(nude)} porta/e pubblicate su TUTTE le interfacce — "
        + " · ".join(f"riga {n}: {t}" for n, t in nude)
        + ". Usa `${VAR:-127.0.0.1}:host:container` (come compose.ingress.tailscale.yaml:58) "
        "o un bind fisso (come compose.ops.portainer.yaml:32)."
    )


def test_il_perimetro_non_e_vuoto() -> None:
    """Se il glob non trova niente, il test sopra è verde per la ragione sbagliata."""
    assert len(_compose_files()) >= 5, f"solo {len(_compose_files())} compose trovati"


# ── POLARITÀ: il presidio deve MORDERE, non solo passare ──────────────────────
# ⭐ Un test che non ha mai visto un rosso non è collaudato: prova che il codice gira,
#   non che il presidio distingua. Qui i due versi si provano su testo sintetico.
def test_polarita_riconosce_la_porta_nuda() -> None:
    nude = porte_nude(['services:', '  x:', '    ports:', '      - "8080:8080"'])
    assert len(nude) == 1 and nude[0][0] == 4


@pytest.mark.parametrize("riga", [
    '      - "127.0.0.1:9443:9443"',
    '      - "${GATEWAY_BIND:-127.0.0.1}:8080:8080"',
    '      - "${DEV_BIND:-127.0.0.1}:8002:8002"',
])
def test_polarita_le_forme_corrette_passano(riga: str) -> None:
    assert not porte_nude(['services:', '  x:', '    ports:', riga])


def test_polarita_non_guarda_fuori_da_ports() -> None:
    """Un `- "8080:8080"` sotto un'altra chiave non è una porta pubblicata."""
    assert not porte_nude(['services:', '  x:', '    command:', '      - "8080:8080"'])
