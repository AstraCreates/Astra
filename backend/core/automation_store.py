"""Durable store for the automations canvas: flow definitions (nodes/edges) and
run history, per founder. Same lock/atomic-write idiom as session_store.py.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

_founder_locks: dict[str, threading.Lock] = {}
_founder_locks_guard = threading.Lock()


def _founder_lock(founder_id: str) -> threading.Lock:
    lock = _founder_locks.get(founder_id)
    if lock is None:
        with _founder_locks_guard:
            lock = _founder_locks.get(founder_id)
            if lock is None:
                lock = threading.Lock()
                _founder_locks[founder_id] = lock
    return lock


def _vault() -> Path:
    path = Path(os.environ.get("OBSIDIAN_VAULT", "/tmp/astra_docs"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_id(value: str) -> str:
    return "".join(c for c in value if c.isalnum() or c in ("_", "-"))[:128] or "unknown"


def _founder_dir(founder_id: str) -> Path:
    d = _vault() / "automations" / _safe_id(founder_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "runs").mkdir(parents=True, exist_ok=True)
    return d


def _flows_path(founder_id: str) -> Path:
    return _founder_dir(founder_id) / "flows.json"


def _run_path(founder_id: str, run_id: str) -> Path:
    return _founder_dir(founder_id) / "runs" / f"{_safe_id(run_id)}.json"


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
    tmp.replace(path)


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


_now = now  # internal alias, kept for brevity within this module


# ── Flows ────────────────────────────────────────────────────────────────────

def _load_flows(founder_id: str) -> dict[str, dict]:
    p = _flows_path(founder_id)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def list_flows(founder_id: str) -> list[dict]:
    flows = _load_flows(founder_id)
    return sorted(flows.values(), key=lambda f: f.get("updated_at", ""), reverse=True)


def get_flow(founder_id: str, flow_id: str) -> dict | None:
    return _load_flows(founder_id).get(flow_id)


def save_flow(
    founder_id: str,
    name: str,
    nodes: list[dict],
    edges: list[dict],
    flow_id: str = "",
) -> dict:
    with _founder_lock(founder_id):
        flows = _load_flows(founder_id)
        flow_id = flow_id or f"flow_{uuid.uuid4().hex[:12]}"
        existing = flows.get(flow_id)
        flow = {
            "id": flow_id,
            "founder_id": founder_id,
            "name": name,
            "nodes": nodes,
            "edges": edges,
            "created_at": (existing or {}).get("created_at") or _now(),
            "updated_at": _now(),
            # Opaque per-flow secret for the public webhook trigger endpoint —
            # generated once and kept stable across re-saves.
            "webhook_token": (existing or {}).get("webhook_token") or uuid.uuid4().hex,
        }
        flows[flow_id] = flow
        _atomic_write(_flows_path(founder_id), flows)
        _index_webhook_token(flow["webhook_token"], founder_id, flow_id)
        return flow


def delete_flow(founder_id: str, flow_id: str) -> bool:
    with _founder_lock(founder_id):
        flows = _load_flows(founder_id)
        if flow_id not in flows:
            return False
        token = flows[flow_id].get("webhook_token")
        del flows[flow_id]
        _atomic_write(_flows_path(founder_id), flows)
        if token:
            _unindex_webhook_token(token)
        return True


# ── Webhook token index ──────────────────────────────────────────────────────
# The webhook trigger URL only exposes this opaque token (no founder_id/flow_id
# path segments — founder_id is derived from a founder's email and has no
# business appearing in a URL a founder pastes into a third-party service).

_webhook_index_lock = threading.Lock()


def _webhook_index_path() -> Path:
    return _vault() / "automations" / "_webhook_index.json"


def _load_webhook_index() -> dict[str, dict]:
    p = _webhook_index_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _index_webhook_token(token: str, founder_id: str, flow_id: str) -> None:
    with _webhook_index_lock:
        index = _load_webhook_index()
        index[token] = {"founder_id": founder_id, "flow_id": flow_id}
        _atomic_write(_webhook_index_path(), index)


def _unindex_webhook_token(token: str) -> None:
    with _webhook_index_lock:
        index = _load_webhook_index()
        if token in index:
            del index[token]
            _atomic_write(_webhook_index_path(), index)


def resolve_webhook_token(token: str) -> tuple[str, str] | None:
    """Returns (founder_id, flow_id) for a webhook token, or None if unknown."""
    entry = _load_webhook_index().get(token)
    if not entry:
        return None
    return entry["founder_id"], entry["flow_id"]


# ── Runs ─────────────────────────────────────────────────────────────────────

def create_run(founder_id: str, flow_id: str) -> dict:
    run_id = f"run_{uuid.uuid4().hex[:16]}"
    run = {
        "run_id": run_id,
        "flow_id": flow_id,
        "founder_id": founder_id,
        "status": "running",
        "node_results": {},
        "started_at": _now(),
        "finished_at": None,
        "error": None,
    }
    _atomic_write(_run_path(founder_id, run_id), run)
    return run


def update_run(founder_id: str, run_id: str, **fields: Any) -> None:
    with _founder_lock(founder_id):
        p = _run_path(founder_id, run_id)
        try:
            run = json.loads(p.read_text())
        except Exception:
            run = {"run_id": run_id, "founder_id": founder_id, "node_results": {}}
        run.update(fields)
        _atomic_write(p, run)


def set_node_result(founder_id: str, run_id: str, node_id: str, result: dict) -> None:
    with _founder_lock(founder_id):
        p = _run_path(founder_id, run_id)
        try:
            run = json.loads(p.read_text())
        except Exception:
            run = {"run_id": run_id, "founder_id": founder_id, "node_results": {}}
        run.setdefault("node_results", {})[node_id] = result
        _atomic_write(p, run)


def get_run(founder_id: str, run_id: str) -> dict | None:
    p = _run_path(founder_id, run_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def list_runs(founder_id: str, flow_id: str = "", limit: int = 20) -> list[dict]:
    runs_dir = _founder_dir(founder_id) / "runs"
    runs = []
    for f in runs_dir.glob("*.json"):
        try:
            run = json.loads(f.read_text())
        except Exception:
            continue
        if flow_id and run.get("flow_id") != flow_id:
            continue
        runs.append(run)
    runs.sort(key=lambda r: r.get("started_at", ""), reverse=True)
    return runs[:limit]
