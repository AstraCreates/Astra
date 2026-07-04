"""Organizations, team roles, entitlements, and admin audit events.

This is the business-facing control plane foundation. It is intentionally
local-first like the current Company Brain store, but the shape maps cleanly to
a future database: organizations own members, roles, subscription/usage state,
and audit events for admin actions.
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any

# Per-org lock covering the FULL read-modify-write-audit-save cycle. Previously
# a single global _write_lock only wrapped _save()'s final file write — the
# _load() -> mutate step happened unlocked, so concurrent calls for the same
# org (e.g. two usage-recording events, or a member upsert racing an invite
# accept) could read the same stale state and the second write would clobber
# the first's changes (lost usage counts, vanished members/invites).
_org_locks: dict[str, threading.Lock] = {}
_org_locks_guard = threading.Lock()


def _org_lock(org_id: str) -> threading.Lock:
    lock = _org_locks.get(org_id)
    if lock is None:
        with _org_locks_guard:
            lock = _org_locks.get(org_id)
            if lock is None:
                lock = threading.Lock()
                _org_locks[org_id] = lock
    return lock


PLANS: dict[str, dict[str, Any]] = {
    "beta": {
        "name": "Beta",
        "monthly_runs": 99999,
        "team_seats": 5,
        "connector_syncs_per_day": 999,
        "approval_workflows": True,
        "company_brain": True,
    },
    "starter": {
        "name": "Starter",
        "monthly_runs": 25,
        "team_seats": 3,
        "connector_syncs_per_day": 10,
        "approval_workflows": True,
        "company_brain": True,
    },
    "team": {
        "name": "Team",
        "monthly_runs": 150,
        "team_seats": 15,
        "connector_syncs_per_day": 100,
        "approval_workflows": True,
        "company_brain": True,
    },
    "scale": {
        "name": "Scale",
        "monthly_runs": 1000,
        "team_seats": 100,
        "connector_syncs_per_day": 1000,
        "approval_workflows": True,
        "company_brain": True,
    },
}


def _root() -> Path:
    root = Path(".astra/accounts")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _path(org_id: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", org_id)[:120] or "org"
    return _root() / f"{safe}.json"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _default_org(founder_id: str, org_id: str | None = None) -> dict[str, Any]:
    resolved_org = org_id or founder_id
    return {
        "org_id": resolved_org,
        "name": "Astra Workspace",
        "owner_id": founder_id,
        "created_at": _now(),
        "updated_at": _now(),
        "members": {
            founder_id: {
                "user_id": founder_id,
                "role": "owner",
                "status": "active",
                "joined_at": _now(),
            }
        },
        "subscription": {
            "plan": "beta",
            "status": "active",
            "stripe_customer_id": "",
            "stripe_subscription_id": "",
            "current_period_end": None,
        },
        "usage": {
            "period": time.strftime("%Y-%m", time.gmtime()),
            "runs": 0,
            "connector_syncs": 0,
            "approval_decisions": 0,
        },
        "admin_controls": {
            "require_approval_for_public_actions": True,
            "require_approval_for_billing_actions": True,
            "allow_agent_external_writes": False,
            "allowed_connectors": ["github", "vercel", "supabase", "clerk", "gmail", "google_drive", "slack", "notion", "obsidian"],
        },
        "audit_log": [],
        "invites": {},
    }


def _load(org_id: str, founder_id: str | None = None) -> dict[str, Any]:
    path = _path(org_id)
    if not path.exists():
        return _default_org(founder_id or org_id, org_id)
    try:
        data = json.loads(path.read_text())
    except Exception:
        data = _default_org(founder_id or org_id, org_id)
    defaults = _default_org(data.get("owner_id") or founder_id or org_id, org_id)
    for key, value in defaults.items():
        data.setdefault(key, value)
    return data


def _save(data: dict[str, Any]) -> dict[str, Any]:
    # No lock here — every caller now holds _org_lock(org_id) for its whole
    # read-modify-write cycle, this is just the write step of that cycle.
    data["updated_at"] = _now()
    _path(data["org_id"]).write_text(json.dumps(data, indent=2, sort_keys=True))
    try:
        from backend.storage_adapter import mirror_document
        mirror_document("accounts", data["org_id"], data)
    except Exception:
        pass
    return data


def _audit(data: dict[str, Any], actor_id: str, action: str, payload: dict[str, Any] | None = None) -> None:
    log = list(data.get("audit_log") or [])
    log.insert(0, {
        "at": _now(),
        "actor_id": actor_id,
        "action": action,
        "payload": payload or {},
    })
    data["audit_log"] = log[:200]


def append_audit_event(org_id: str, *, actor_id: str, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    with _org_lock(org_id):
        data = _load(org_id)
        _audit(data, actor_id, action, payload)
        _save(data)
        return with_entitlements(data)


def get_or_create_org(founder_id: str, org_id: str | None = None) -> dict[str, Any]:
    resolved_org = org_id or founder_id
    with _org_lock(resolved_org):
        data = _load(resolved_org, founder_id)
        _save(data)
        return with_entitlements(data)


def with_entitlements(data: dict[str, Any]) -> dict[str, Any]:
    plan_id = data.get("subscription", {}).get("plan") or "beta"
    plan = PLANS.get(plan_id, PLANS["beta"])
    usage = data.get("usage") or {}
    members = data.get("members") or {}
    entitlements = {
        **plan,
        "plan_id": plan_id,
        "remaining_runs": max(0, int(plan["monthly_runs"]) - int(usage.get("runs") or 0)),
        "remaining_connector_syncs": max(0, int(plan["connector_syncs_per_day"]) - int(usage.get("connector_syncs") or 0)),
        "remaining_team_seats": max(0, int(plan["team_seats"]) - len([m for m in members.values() if m.get("status") == "active"])),
    }
    return {**data, "entitlements": entitlements}


def _invite_token() -> str:
    import uuid
    return uuid.uuid4().hex


def _invite_expiry(hours: int = 72) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + hours * 3600))


def create_org_invite(
    org_id: str,
    *,
    actor_id: str,
    email: str = "",
    role: str = "viewer",
) -> dict[str, Any]:
    with _org_lock(org_id):
        data = _load(org_id)
        members = data.get("members") or {}
        actor = members.get(actor_id) or {}
        if actor_id != data.get("owner_id") and actor.get("role") not in {"owner", "admin"}:
            raise PermissionError("Only owners and admins can invite members.")
        invite = {
            "token": _invite_token(),
            "org_id": org_id,
            "kind": "org",
            "invited_by": actor_id,
            "email": email or "",
            "role": role if role in {"owner", "admin", "operator", "viewer"} else "viewer",
            "status": "pending",
            "created_at": _now(),
            "expires_at": _invite_expiry(),
        }
        invites = data.setdefault("invites", {})
        invites[invite["token"]] = invite
        _audit(data, actor_id, "invite.created", {"email": email, "role": invite["role"]})
        _save(data)
        return invite


def get_org_invite(token: str) -> dict[str, Any] | None:
    for path in _root().glob("*.json"):
        try:
            data = json.loads(path.read_text())
        except Exception:
            continue
        invite = (data.get("invites") or {}).get(token)
        if invite:
            return {**invite, "org_name": data.get("name") or data.get("org_id") or ""}
    return None


def accept_org_invite(token: str, *, user_id: str) -> dict[str, Any]:
    for path in _root().glob("*.json"):
        try:
            data = json.loads(path.read_text())
        except Exception:
            continue
        invites = data.get("invites") or {}
        invite = invites.get(token)
        if not invite:
            continue
        org_id = str(data.get("org_id") or path.stem)
        with _org_lock(org_id):
            data = _load(org_id)
            invites = data.get("invites") or {}
            invite = invites.get(token)
            if not invite:
                continue
            if invite.get("status") != "pending":
                raise ValueError(f"Invite is {invite.get('status')}")
            if invite.get("expires_at") and invite["expires_at"] < _now():
                invite["status"] = "expired"
                _save(data)
                raise ValueError("Invite has expired")
            members = data.setdefault("members", {})
            members[user_id] = {
                **members.get(user_id, {"user_id": user_id, "joined_at": _now()}),
                "role": invite.get("role") or "viewer",
                "status": "active",
                "updated_at": _now(),
            }
            invite["status"] = "accepted"
            invite["accepted_at"] = _now()
            _audit(data, user_id, "invite.accepted", {"token": token, "role": invite.get("role")})
            _save(data)
            return with_entitlements(data)
    raise ValueError("Invite not found")


def update_subscription(
    org_id: str,
    *,
    actor_id: str,
    plan: str | None = None,
    status: str | None = None,
    stripe_customer_id: str | None = None,
    stripe_subscription_id: str | None = None,
    current_period_end: str | None = None,
) -> dict[str, Any]:
    with _org_lock(org_id):
        data = _load(org_id)
        subscription = data.setdefault("subscription", {})
        if plan and plan in PLANS:
            subscription["plan"] = plan
        if status:
            subscription["status"] = status
        if stripe_customer_id is not None:
            subscription["stripe_customer_id"] = stripe_customer_id
        if stripe_subscription_id is not None:
            subscription["stripe_subscription_id"] = stripe_subscription_id
        if current_period_end is not None:
            subscription["current_period_end"] = current_period_end
        _audit(data, actor_id, "subscription.updated", {"subscription": subscription})
        _save(data)
        return with_entitlements(data)


def upsert_member(org_id: str, *, actor_id: str, user_id: str, role: str = "viewer", status: str = "active") -> dict[str, Any]:
    with _org_lock(org_id):
        data = _load(org_id)
        allowed = {"owner", "admin", "operator", "viewer"}
        if role not in allowed:
            role = "viewer"
        members = data.setdefault("members", {})
        members[user_id] = {
            **members.get(user_id, {"user_id": user_id, "joined_at": _now()}),
            "role": role,
            "status": status,
            "updated_at": _now(),
        }
        _audit(data, actor_id, "member.upserted", {"user_id": user_id, "role": role, "status": status})
        _save(data)
        return with_entitlements(data)


def update_admin_controls(org_id: str, *, actor_id: str, controls: dict[str, Any]) -> dict[str, Any]:
    with _org_lock(org_id):
        data = _load(org_id)
        current = data.setdefault("admin_controls", {})
        allowed_keys = set(_default_org(data.get("owner_id") or org_id, org_id)["admin_controls"])
        for key, value in controls.items():
            if key in allowed_keys:
                current[key] = value
        _audit(data, actor_id, "admin_controls.updated", {"controls": current})
        _save(data)
        return with_entitlements(data)


def record_usage(org_id: str, *, actor_id: str = "system", runs: int = 0, connector_syncs: int = 0, approval_decisions: int = 0) -> dict[str, Any]:
    with _org_lock(org_id):
        data = _load(org_id)
        usage = data.setdefault("usage", {})
        period = time.strftime("%Y-%m", time.gmtime())
        if usage.get("period") != period:
            data["usage"] = usage = {"period": period, "runs": 0, "connector_syncs": 0, "approval_decisions": 0}
        usage["runs"] = int(usage.get("runs") or 0) + max(0, runs)
        usage["connector_syncs"] = int(usage.get("connector_syncs") or 0) + max(0, connector_syncs)
        usage["approval_decisions"] = int(usage.get("approval_decisions") or 0) + max(0, approval_decisions)
        _audit(data, actor_id, "usage.recorded", {"runs": runs, "connector_syncs": connector_syncs, "approval_decisions": approval_decisions})
        _save(data)
        return with_entitlements(data)


def list_orgs() -> list[dict[str, Any]]:
    orgs = []
    for path in sorted(_root().glob("*.json")):
        try:
            data = json.loads(path.read_text())
            orgs.append(with_entitlements(data))
        except Exception:
            continue
    return orgs


def list_orgs_for_user(user_id: str) -> list[dict[str, Any]]:
    """Return orgs visible to a user."""
    visible = []
    for org in list_orgs():
        member = (org.get("members") or {}).get(user_id)
        if org.get("owner_id") == user_id or (member and member.get("status") == "active"):
            visible.append(org)
    return visible


def find_org_by_stripe(customer_id: str = "", subscription_id: str = "") -> dict[str, Any] | None:
    """Find an org by Stripe customer or subscription id."""
    for org in list_orgs():
        sub = org.get("subscription") or {}
        if customer_id and sub.get("stripe_customer_id") == customer_id:
            return org
        if subscription_id and sub.get("stripe_subscription_id") == subscription_id:
            return org
    return None
