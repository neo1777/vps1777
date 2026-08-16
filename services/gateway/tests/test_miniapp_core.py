"""Test validazione initData Telegram (stdlib-only, offline)."""
from __future__ import annotations

import hashlib
import hmac
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import miniapp_core  # noqa: E402

BOT = "123456:TEST-bot-token"


def _sign(fields: dict, token: str = BOT) -> str:
    """Costruisce un initData firmato come farebbe Telegram."""
    pairs = sorted(fields.items())
    data_check = "\n".join(f"{k}={v}" for k, v in pairs)
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    h = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urlencode(list(fields.items()) + [("hash", h)])


def test_valid_init_data():
    now = 1_700_000_000
    init = _sign({"auth_date": str(now), "user": '{"id":774881727}', "query_id": "x"})
    out = miniapp_core.verify_init_data(init, BOT, now=now)
    assert out is not None
    assert out["user"] == '{"id":774881727}'


def test_tampered_hash_rejected():
    now = 1_700_000_000
    init = _sign({"auth_date": str(now), "user": '{"id":1}'})
    tampered = init[:-4] + ("0000" if not init.endswith("0000") else "1111")
    assert miniapp_core.verify_init_data(tampered, BOT, now=now) is None


def test_wrong_token_rejected():
    now = 1_700_000_000
    init = _sign({"auth_date": str(now), "user": '{"id":1}'})
    assert miniapp_core.verify_init_data(init, "999:OTHER", now=now) is None


def test_missing_hash_rejected():
    init = urlencode({"auth_date": str(int(time.time())), "user": '{"id":1}'})
    assert miniapp_core.verify_init_data(init, BOT) is None


def test_expired_rejected():
    old = 1_700_000_000
    init = _sign({"auth_date": str(old), "user": '{"id":1}'})
    # 25h dopo → oltre il max_age (era 24h, ora 12h: scaduta a maggior ragione)
    assert miniapp_core.verify_init_data(init, BOT, now=old + 25 * 3600) is None


def test_init_data_window_is_12h():
    """H27: la finestra è 12h, non più 24h. Una initData di 13h fa NON deve più
    passare — è il punto del rilievo, quindi il test guarda proprio il confine."""
    assert miniapp_core.INIT_DATA_MAX_AGE_S == 12 * 3600
    t = 1_700_000_000
    init = _sign({"auth_date": str(t), "user": '{"id":1}'})
    assert miniapp_core.verify_init_data(init, BOT, now=t + 11 * 3600) is not None  # dentro
    assert miniapp_core.verify_init_data(init, BOT, now=t + 13 * 3600) is None      # fuori
    # e il vecchio limite di 24h non vale più
    assert miniapp_core.verify_init_data(init, BOT, now=t + 23 * 3600) is None


def test_init_data_auth_date_nel_futuro_passa_ma_non_e_replay():
    """auth_date nel futuro (clock skew del client): (now - auth_date) è negativo,
    quindi passa. È voluto — un initData FIRMATO col token del bot non lo può
    forgiare il client; qui documentiamo la semantica, non la cambiamo."""
    t = 1_700_000_000
    init = _sign({"auth_date": str(t + 300), "user": '{"id":1}'})
    assert miniapp_core.verify_init_data(init, BOT, now=t) is not None


def test_empty_inputs():
    assert miniapp_core.verify_init_data("", BOT) is None
    assert miniapp_core.verify_init_data("a=b&hash=x", "") is None


def test_is_owner():
    assert miniapp_core.is_owner("774881727", 774881727) is True
    assert miniapp_core.is_owner(774881727, 774881727) is True
    assert miniapp_core.is_owner("999", 774881727) is False
    assert miniapp_core.is_owner("abc", 774881727) is False
    # owner_id non configurato (0) → FAIL-CLOSED: nessuno è owner (prima era True!)
    assert miniapp_core.is_owner("qualunque", 0) is False
    assert miniapp_core.is_owner(774881727, 0) is False


# ───── URL dei connettori: il segreto non deve uscire per sbaglio (H26) ─────

def test_masked_connector_url_non_contiene_il_segreto():
    masked = miniapp_core.masked_connector_url("https://vps.example.com", "nb1777")
    assert "s3cret-gateway-value" not in masked   # ovvio, ma è IL punto
    assert masked == "https://vps.example.com/••••••••/nb1777/mcp"
    # il mask è a lunghezza FISSA: non rivela quanto è lungo il segreto
    assert masked == miniapp_core.masked_connector_url("https://vps.example.com", "nb1777")


def test_masked_url_lunghezza_fissa_a_prescindere_dal_segreto():
    # la forma mascherata non dipende dal segreto: non può nemmeno riceverlo
    a = miniapp_core.masked_connector_url("https://h", "x")
    b = miniapp_core.masked_connector_url("https://h", "x")
    assert a == b and a.count("•") == 8


def test_connector_url_completo():
    assert miniapp_core.connector_url("https://vps.example.com/", "S3CRET", "archive") == \
        "https://vps.example.com/S3CRET/archive/mcp"  # base con slash finale → un solo /


def test_connector_url_senza_segreto_configurato():
    # segreto assente: placeholder parlante, sia in chiaro sia mascherato
    assert miniapp_core.connector_url("https://h", "", "nb1777") == "https://h/<SECRET>/nb1777/mcp"
    assert miniapp_core.masked_connector_url("https://h", "nb1777", has_secret=False) == \
        "https://h/<SECRET>/nb1777/mcp"


# ───── parsing MCP ─────

def test_parse_mcp_payload_sse():
    body = 'event: message\ndata: {"jsonrpc":"2.0","result":{"content":[]}}\n\n'
    out = miniapp_core.parse_mcp_payload("text/event-stream", body)
    assert out["jsonrpc"] == "2.0"


def test_parse_mcp_payload_json():
    out = miniapp_core.parse_mcp_payload("application/json", '{"result":{}}')
    assert out == {"result": {}}


def test_parse_mcp_payload_sse_empty_raises():
    import pytest
    with pytest.raises(ValueError):
        miniapp_core.parse_mcp_payload("text/event-stream", "event: message\n\n")


def test_extract_tool_texts_ok():
    rpc = {"result": {"content": [
        {"type": "text", "text": "uno"}, {"type": "text", "text": "due"},
        {"type": "image", "data": "..."},  # non-text → ignorato
    ]}}
    assert miniapp_core.extract_tool_texts(rpc) == ["uno", "due"]


def test_extract_tool_texts_rpc_error():
    import pytest
    with pytest.raises(ValueError, match="boom"):
        miniapp_core.extract_tool_texts({"error": {"code": -1, "message": "boom"}})


def test_extract_tool_texts_is_error():
    import pytest
    with pytest.raises(ValueError, match="tool fallito"):
        miniapp_core.extract_tool_texts(
            {"result": {"isError": True, "content": [{"type": "text", "text": "tool fallito"}]}})


def test_parse_json_blocks_mixed():
    texts = ['{"id":"a","title":"A"}',       # dict per block
             '[{"id":"b"},{"id":"c"}]',      # block con array
             'non-json',                      # ignorato
             '42']                            # scalare → ignorato
    out = miniapp_core.parse_json_blocks(texts)
    assert [d["id"] for d in out] == ["a", "b", "c"]


def test_parse_string_blocks_mixed():
    texts = ['["db1","db2"]', '"db3"', 'db4-plain', '']
    assert miniapp_core.parse_string_blocks(texts) == ["db1", "db2", "db3", "db4-plain"]


def test_summarize_secrets():
    st = {"checked_at": "2026-07-09", "secrets": [
        {"name": "a", "overdue": False}, {"name": "b", "overdue": True}]}
    out = miniapp_core.summarize_secrets(st)
    assert out == {"total": 2, "overdue": 1, "overdue_names": ["b"],
                   "checked_at": "2026-07-09"}


def test_extract_answer():
    # involucro JSON del tool → solo il testo
    assert miniapp_core.extract_answer('{"answer": "ciao mondo"}') == "ciao mondo"
    # testo semplice → invariato
    assert miniapp_core.extract_answer("risposta libera") == "risposta libera"
    # JSON ma senza answer stringa → invariato (non si inventa)
    assert miniapp_core.extract_answer('{"other": 1}') == '{"other": 1}'
    assert miniapp_core.extract_answer('{"answer": 42}') == '{"answer": 42}'
    assert miniapp_core.extract_answer("") == ""


def test_version_gt():
    assert miniapp_core.version_gt("0.16.0", "0.15.2") is True
    assert miniapp_core.version_gt("0.15.2", "0.15.2") is False
    # il caso reale trovato in E2E: check giornaliero stantio → niente downgrade
    assert miniapp_core.version_gt("0.15.0", "0.15.2") is False
    assert miniapp_core.version_gt("1.0.0", "0.99.99") is True
    assert miniapp_core.version_gt("v0.16.0", "0.15.2") is True   # prefisso v
    assert miniapp_core.version_gt("0.16.0", "dev") is False      # non-numerico → confronto stringa
    assert miniapp_core.version_gt("", "0.15.2") is False
    assert miniapp_core.version_gt("0.15.2", "") is False


def test_summarize_secrets_empty():
    assert miniapp_core.summarize_secrets({}) == {
        "total": 0, "overdue": 0, "overdue_names": [], "checked_at": ""}


# ─────────────────────────────────────────────────────────────────────────────
# H54 — la chiave DERIVATA al posto del token intero.
#
# Il rilievo dice: il gateway monta il token del bot, e col token si parla come
# il bot fuori dal suo perimetro. Misurato il 27/07: il gateway non chiama MAI
# l'API di Telegram (zero occorrenze di api.telegram.org/sendMessage/getUpdates),
# quindi del token gli serve solo la chiave che se ne deriva — e la derivazione
# è a senso unico.
#
# Questi casi provano le due metà: che la chiave derivata BASTA, e che tutto
# ciò che funzionava prima funziona ancora identico.
# ─────────────────────────────────────────────────────────────────────────────

WEBAPP_HEX = hmac.new(b"WebAppData", BOT.encode(), hashlib.sha256).hexdigest()


def test_chiave_derivata_verifica_senza_il_token():
    """La metà che chiude il rilievo: si valida SENZA passare il token."""
    now = 1_700_000_000
    init = _sign({"auth_date": str(now), "user": '{"id":774881727}'})
    out = miniapp_core.verify_init_data(init, "", webapp_secret_hex=WEBAPP_HEX, now=now)
    assert out is not None
    assert out["user"] == '{"id":774881727}'


def test_derivata_e_token_danno_lo_stesso_verdetto():
    """Retrocompatibilità: le due strade non possono divergere, o la migrazione
    diventerebbe un cambio di comportamento travestito da cambio di segreto."""
    now = 1_700_000_000
    init = _sign({"auth_date": str(now), "user": '{"id":1}'})
    assert (miniapp_core.verify_init_data(init, BOT, now=now)
            == miniapp_core.verify_init_data(init, "", webapp_secret_hex=WEBAPP_HEX, now=now))


def test_la_derivata_vince_sul_token():
    """Se ci sono entrambi si usa la derivata: altrimenti un token dimenticato
    nel compose terrebbe in vita la strada che si voleva chiudere, e nessuno se
    ne accorgerebbe perché tutto continuerebbe a funzionare."""
    now = 1_700_000_000
    init = _sign({"auth_date": str(now), "user": '{"id":1}'}, token="UN-ALTRO-token")
    altra = hmac.new(b"WebAppData", b"UN-ALTRO-token", hashlib.sha256).hexdigest()
    # firmata con l'altro token: passa con la SUA derivata anche se BOT è presente
    assert miniapp_core.verify_init_data(init, BOT, webapp_secret_hex=altra, now=now) is not None
    # e la derivata di BOT la rifiuta, pur essendo BOT il token passato
    assert miniapp_core.verify_init_data(init, BOT, webapp_secret_hex=WEBAPP_HEX, now=now) is None


def test_derivata_sbagliata_rifiuta():
    now = 1_700_000_000
    init = _sign({"auth_date": str(now), "user": '{"id":1}'})
    sbagliata = hmac.new(b"WebAppData", b"altro", hashlib.sha256).hexdigest()
    assert miniapp_core.verify_init_data(init, "", webapp_secret_hex=sbagliata, now=now) is None


def test_derivata_malformata_non_esplode_e_rifiuta():
    """Un segreto non-esadecimale o troncato in provisioning deve dare un rifiuto
    pulito, non un'eccezione e non un falso positivo. La lunghezza si controlla:
    una chiave troncata darebbe un 401 di firma, che si legge come «initData
    scaduta» e manda a cercare dalla parte opposta."""
    now = 1_700_000_000
    init = _sign({"auth_date": str(now), "user": '{"id":1}'})
    for cattiva in ("non-esadecimale", "ab", WEBAPP_HEX[:-2], WEBAPP_HEX + "ff", ""):
        if cattiva == "":
            continue  # vuota = «non configurata», copre il ramo del token
        assert miniapp_core.verify_init_data(init, "", webapp_secret_hex=cattiva, now=now) is None


def test_senza_niente_rifiuta():
    """Né token né derivata: non si valida per difetto. Fail-closed."""
    now = 1_700_000_000
    init = _sign({"auth_date": str(now), "user": '{"id":1}'})
    assert miniapp_core.verify_init_data(init, "", webapp_secret_hex="", now=now) is None


def test_la_derivata_non_e_il_token():
    """Il punto del rilievo, in una riga: chi ha la chiave non ha il token.
    Se un giorno qualcuno «semplificasse» montando il token al posto suo, questo
    test non se ne accorgerebbe — ma chi lo legge sì."""
    assert WEBAPP_HEX != BOT
    assert BOT not in WEBAPP_HEX
    assert miniapp_core.webapp_secret_key(BOT).hex() == WEBAPP_HEX


def test_la_scadenza_vale_anche_con_la_derivata():
    """Il presidio di freschezza (H27, 12h) non deve saltare sulla strada nuova:
    è il modo classico in cui un ramo aggiunto perde un controllo che l'altro ha."""
    now = 1_700_000_000
    vecchio = _sign({"auth_date": str(now - 13 * 3600), "user": '{"id":1}'})
    assert miniapp_core.verify_init_data(vecchio, "", webapp_secret_hex=WEBAPP_HEX, now=now) is None
