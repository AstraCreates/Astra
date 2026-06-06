import base64

from backend.core.events import _strip_base64


def test_sse_payload_strips_large_base64_results():
    raw = base64.b64encode(b"x" * 20_000).decode()
    event = {
        "type": "agent_done",
        "agent": "marketing",
        "result": {"base64": raw, "prompt": "ad"},
    }

    stripped = _strip_base64(event)

    assert stripped["_base64_stripped"] is True
    assert stripped["result"]["base64"] == f"[base64:{len(raw)}chars]"
    assert stripped["result"]["prompt"] == "ad"
