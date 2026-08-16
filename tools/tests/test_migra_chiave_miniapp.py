"""Collaudo di tools/migra-chiave-miniapp.sh — H54, la migrazione alla chiave derivata.

PERCHÉ QUESTI TEST E NON ALTRI. Lo strumento fa due cose che, se sbagliate, falliscono
in modo SILENZIOSO — cioè nel modo che questo progetto insegue da settimane:

  ① deriva una chiave che deve essere IDENTICA a quella che il gateway calcola.
     Se diverge di un byte, il gateway parte, i log tacciono, e la Mini App smette
     di autenticare. Nessun errore dice «la chiave è sbagliata»: dice 401 a un utente.
  ② scrive un overlay che deve togliere UN secret e non toccare gli altri quattro.
     `docker compose` FONDE le liste di secrets invece di sostituirle: senza `!reset`
     il token resterebbe montato e l'overlay — scritto per toglierlo — non toglierebbe
     niente, senza un solo messaggio di avviso.

⭐ E il caso ③ esiste per un difetto MIO, non ipotetico: la prima versione dello script
   scriveva `secrets: !reset []` — lista VUOTA — con accanto un avviso «completala a
   mano». Chi non avesse letto l'avviso avrebbe avviato il gateway senza NESSUN
   segreto. Il test ③ è quella versione, resa impossibile.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "tools" / "migra-chiave-miniapp.sh"
# ⚠️ ACCORCIATO IL 16/08, e la ragione va letta prima di allungarlo di nuovo:
#   con la regex curata (`\d{5,}:[A-Za-z0-9_-]{30,}`, allineata a `deploy.sh:243`)
#   il valore precedente — 49 caratteri dopo i due punti — faceva scattare il gate
#   anti-leak su QUESTO file. Non era un falso positivo: aveva davvero la forma di
#   un token. ⇒ scelto di accorciare il VALORE invece di esentare il FILE, perché
#   un'esenzione è una porta che resta aperta anche quando il file cambia.
# 🔑 Il test non ne risente: il token qui è un valore OPACO — si scrive, se ne deriva
#   una chiave e si verifica che non trapeli. Nessuna asserzione guarda la sua
#   lunghezza o il suo formato.
TOKEN_FINTO = "1234567890:FINTO-NON-UN-TOKEN"


def _prepara(tmp: Path) -> Path:
    """Una copia minima del repo: mai i secret veri, mai il compose vero modificato."""
    (tmp / "tools").mkdir(parents=True, exist_ok=True)
    (tmp / "secrets").mkdir(parents=True, exist_ok=True)
    shutil.copy(SCRIPT, tmp / "tools" / SCRIPT.name)
    shutil.copy(REPO / "compose.yaml", tmp / "compose.yaml")
    (tmp / "secrets" / "telegram_bot_token.txt").write_text(TOKEN_FINTO + "\n")
    return tmp


def _lancia(tmp: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "tools/migra-chiave-miniapp.sh", *args],
        cwd=tmp, capture_output=True, text=True,
    )


def _secrets_del_gateway(path: Path) -> list[str]:
    serv, dentro, out = None, False, []
    for riga in path.read_text(encoding="utf-8").split("\n"):
        m = re.match(r"^  ([a-z0-9_-]+):\s*$", riga)
        if m:
            serv, dentro = m.group(1), False
        if re.match(r"^    secrets:", riga):
            dentro = serv == "gateway"
            continue
        if dentro:
            m2 = re.match(r"^      - ([a-z0-9_]+)\s*$", riga)
            if m2:
                out.append(m2.group(1))
            elif riga.strip() and not riga.startswith("      "):
                dentro = False
    return out


def test_1_la_chiave_e_identica_a_quella_del_gateway(tmp_path):
    """① Se questa diverge, la Mini App si rompe e nessun log lo dice."""
    tmp = _prepara(tmp_path)
    assert _lancia(tmp).returncode == 0

    scritta = (tmp / "secrets" / "telegram_webapp_secret.txt").read_text().strip()

    sys.path.insert(0, str(REPO / "services" / "gateway"))
    from app.miniapp_core import webapp_secret_key  # la funzione VERA del prodotto

    assert scritta == webapp_secret_key(TOKEN_FINTO).hex(), (
        "la chiave derivata dallo script NON coincide con quella che il gateway "
        "calcola: la Mini App riceverebbe 401 e nessun log direbbe perché"
    )
    assert len(scritta) == 64 and all(c in "0123456789abcdef" for c in scritta)


def test_2_il_token_non_finisce_da_nessuna_parte(tmp_path):
    """Lo strumento legge il token una volta e non lo copia né lo stampa."""
    tmp = _prepara(tmp_path)
    r = _lancia(tmp)

    assert TOKEN_FINTO not in r.stdout, "il token è finito nell'output"
    assert TOKEN_FINTO not in r.stderr, "il token è finito su stderr"
    for f in tmp.rglob("*"):
        if f.is_file() and f.name != "telegram_bot_token.txt":
            testo = f.read_text(encoding="utf-8", errors="replace")
            assert TOKEN_FINTO not in testo, f"il token è stato copiato in {f.name}"


def test_3_overlay_toglie_il_token_e_non_perde_gli_altri(tmp_path):
    """③ Il caso nato da un difetto mio: una lista VUOTA passava per «riscritta»."""
    tmp = _prepara(tmp_path)
    assert _lancia(tmp).returncode == 0

    base = _secrets_del_gateway(tmp / "compose.yaml")

    # 🔄 16/08 (#61): il compose BASE monta già la chiave derivata, quindi il presupposto
    #   di questo test — «il gateway parte col token» — non regge più. La cosa giusta non
    #   è cancellarlo: è fargli misurare ANCHE il nuovo stato, così continua a proteggere
    #   il caso vecchio se qualcuno torna indietro, e dichiara quello nuovo se resta.
    # ⭐ E il controllo che aggiungo vale più di quello che sostituisce: «né il token né
    #   la chiave» non è lo stato migrato, è uno stato ROTTO in cui la Mini App non può
    #   autenticare nessuno — e prima nessun test lo distingueva dal successo.
    if "telegram_bot_token" not in base:
        assert "telegram_webapp_secret" in base, (
            "il gateway non ha NÉ il token NÉ la chiave derivata: non è lo stato "
            "migrato della #61, è uno stato in cui la Mini App rifiuta tutto")
        return

    nuovo = _secrets_del_gateway(tmp / "compose.miniapp-secret.yaml")
    assert "telegram_bot_token" not in nuovo, "l'overlay NON toglie il token"
    assert "telegram_webapp_secret" in nuovo, "l'overlay non dà la chiave derivata"
    persi = set(base) - set(nuovo) - {"telegram_bot_token"}
    assert not persi, f"l'overlay perde secrets che il gateway usa: {sorted(persi)}"
    assert nuovo, "lista VUOTA: è il difetto che questo test esiste per impedire"


def test_4_reset_c_e_o_compose_fonde_le_liste(tmp_path):
    """Senza `!reset` compose FONDE, e l'overlay non toglierebbe niente in silenzio."""
    tmp = _prepara(tmp_path)
    assert _lancia(tmp).returncode == 0
    testo = (tmp / "compose.miniapp-secret.yaml").read_text(encoding="utf-8")
    assert "!reset" in testo, (
        "senza `!reset` docker compose unisce le due liste: il token resterebbe "
        "montato e l'overlay sembrerebbe applicato"
    )


def test_5_rilanciarlo_non_sovrascrive_la_chiave(tmp_path):
    """Idempotenza: due lanci non devono cambiare un segreto già provisionato."""
    tmp = _prepara(tmp_path)
    _lancia(tmp)
    prima = (tmp / "secrets" / "telegram_webapp_secret.txt").read_text()
    r2 = _lancia(tmp)
    dopo = (tmp / "secrets" / "telegram_webapp_secret.txt").read_text()

    assert prima == dopo, "un secondo lancio ha sovrascritto la chiave"
    assert r2.returncode == 0, "il secondo lancio deve restare verde, non fallire"


def test_6_verifica_non_scrive_niente(tmp_path):
    """`--verifica` è una sonda: se scrivesse, non si potrebbe usare per guardare."""
    tmp = _prepara(tmp_path)
    prima = sorted(p.name for p in tmp.rglob("*") if p.is_file())
    assert _lancia(tmp, "--verifica").returncode == 0
    assert sorted(p.name for p in tmp.rglob("*") if p.is_file()) == prima


def test_7_senza_token_si_ferma_e_dice_perche(tmp_path):
    """Un fallimento deve nominare il file mancante, non morire generico."""
    tmp = _prepara(tmp_path)
    (tmp / "secrets" / "telegram_bot_token.txt").unlink()
    r = _lancia(tmp)
    assert r.returncode != 0, "senza token deve fermarsi"
    assert "telegram_bot_token" in (r.stdout + r.stderr)
