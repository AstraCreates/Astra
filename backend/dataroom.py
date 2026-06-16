"""Auto-maintained data room.

Unlike a one-time export, this is recomputed fresh on every call from data
that already exists elsewhere (session results, genome, Stripe) — so it's
always current instead of going stale the moment something changes.
"""
from __future__ import annotations

from typing import Any

from backend.core import session_store
from backend.deliverables import collect_result_attachment_paths
from backend.genome.store import get_genome
from backend.provisioning.credentials_store import load_credentials


def _session_deliverables(session_id: str) -> list[dict[str, Any]]:
    from backend.workflow_state import build_session_state

    events = session_store.load_events(session_id)
    if not events:
        return []
    state = build_session_state(session_id, events)
    out: list[dict[str, Any]] = []
    for agent_name, agent_state in (state.get("agents") or {}).items():
        result = agent_state.get("result") if isinstance(agent_state, dict) else None
        if not isinstance(result, dict):
            continue
        for path in collect_result_attachment_paths(result):
            out.append({
                "path": str(path),
                "name": path.name,
                "agent": agent_name,
                "session_id": session_id,
            })
    return out


def _stripe_metrics(founder_id: str) -> dict[str, Any]:
    creds = load_credentials(founder_id, "stripe") or {}
    token = creds.get("access_token")
    if not token:
        return {"connected": False}
    try:
        from backend.tools.stripe_tools import get_stripe_data
        data = get_stripe_data(token)
        if data.get("error"):
            return {"connected": True, "error": data["error"]}
        return {
            "connected": True,
            "mrr": data.get("mrr"),
            "total_revenue": data.get("total_revenue"),
            "currency": data.get("currency"),
            "balance": data.get("balance"),
        }
    except Exception as e:
        return {"connected": False, "error": str(e)}


def build_data_room(founder_id: str, company_id: str) -> dict[str, Any]:
    """Everything currently true about a company: every deliverable ever
    generated across every session, live Stripe revenue if connected, and
    the operating profile (genome)."""
    sessions = session_store.list_sessions(founder_id=founder_id, company_id=company_id, limit=200)

    deliverables: list[dict[str, Any]] = []
    for s in sessions:
        sid = s.get("session_id")
        if sid:
            deliverables.extend(_session_deliverables(sid))

    seen: set[str] = set()
    unique_deliverables = []
    for d in deliverables:
        if d["path"] in seen:
            continue
        seen.add(d["path"])
        unique_deliverables.append(d)

    return {
        "founder_id": founder_id,
        "company_id": company_id,
        "genome": get_genome(founder_id, company_id),
        "metrics": _stripe_metrics(founder_id),
        "deliverables": unique_deliverables,
        "session_count": len(sessions),
    }
