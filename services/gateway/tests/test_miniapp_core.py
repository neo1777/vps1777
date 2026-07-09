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
    # 25h dopo → oltre il max_age di 24h
    assert miniapp_core.verify_init_data(init, BOT, now=old + 25 * 3600) is None


def test_empty_inputs():
    assert miniapp_core.verify_init_data("", BOT) is None
    assert miniapp_core.verify_init_data("a=b&hash=x", "") is None


def test_is_owner():
    assert miniapp_core.is_owner("774881727", 774881727) is True
    assert miniapp_core.is_owner(774881727, 774881727) is True
    assert miniapp_core.is_owner("999", 774881727) is False
    assert miniapp_core.is_owner("abc", 774881727) is False
    # owner_id non configurato (0) → nessun filtro
    assert miniapp_core.is_owner("qualunque", 0) is True


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
