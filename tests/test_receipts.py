"""Receipt builder, durable receipt store, and public share tokens."""
import importlib

import pytest

from backend.core.orchestrator import Orchestrator


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    # Re-import stores so their module-level paths pick up the temp vault lazily.
    import backend.verification.receipt_store as rs
    import backend.verification.share_store as ss
    importlib.reload(rs)
    importlib.reload(ss)
    return rs, ss


def _verdict():
    return {
        "status": "passed",
        "attempts": 2,
        "artifacts": [{"artifact_key": "market_brief", "status": "passed"}],
        "levels": {"shape": [], "executable": [], "semantic": []},
        "evidence": {
            "shape": {"passed": True},
            "executable": {"url": "https://x.test", "ok": True, "status": 200, "bytes": 9000},
            "semantic": {"sources_count": 14},
        },
    }


def test_artifact_receipt_builds_three_checks():
    r = Orchestrator._artifact_receipt("market_brief", _verdict())
    levels = [c["level"] for c in r["checks"]]
    assert levels == ["shape", "executable", "semantic"]
    assert r["attempts"] == 2
    assert "HTTP 200" in r["checks"][1]["detail"]


def test_artifact_receipt_empty_when_no_verdict():
    assert Orchestrator._artifact_receipt("x", None) == {}


def test_receipt_store_roundtrip_and_collapse(vault):
    rs, _ = vault
    receipt = Orchestrator._artifact_receipt("market_brief", _verdict())
    rs.add_receipt("f", "c", session_id="s1", artifact_key="market_brief",
                   artifact_title="Market brief", agent="research", receipt=receipt)
    # Second write for same (session, artifact) should collapse on latest_only read.
    rs.add_receipt("f", "c", session_id="s1", artifact_key="market_brief",
                   artifact_title="Market brief", agent="research", receipt=receipt)
    rows = rs.list_receipts("f", "c", latest_only=True)
    assert len(rows) == 1
    assert rows[0]["status"] == "passed"
    assert len(rs.list_receipts("f", "c", latest_only=False)) == 2


def test_share_store_create_resolve_and_rotate(vault):
    _, ss = vault
    t1 = ss.create_share("f", "c")
    assert ss.resolve_share(t1) == {"founder_id": "f", "company_id": "c", **ss.resolve_share(t1)}
    assert ss.resolve_share(t1)["company_id"] == "c"
    # Rotating issues a new token and invalidates the old one (one active per company).
    t2 = ss.create_share("f", "c")
    assert t2 != t1
    assert ss.resolve_share(t1) is None
    assert ss.resolve_share(t2)["company_id"] == "c"
    assert ss.resolve_share("bogus") is None
