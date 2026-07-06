"""Teams, orgs, and invitation system for Astra.

Flat-file store at /data/astra_docs/teams.json (mirrors accounts.py pattern).

Endpoints:
  POST   /teams                              — create team
  GET    /teams/me?founder_id=X             — list teams for user
  GET    /teams/{team_id}                    — team info + members
  POST   /teams/{team_id}/invites            — create invite token, send email
  GET    /invites/{token}                    — public invite info
  POST   /invites/{token}/accept             — accept invite
  DELETE /teams/{team_id}/members/{user_id} — remove member (owner only)
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.tenant_auth import require_authenticated_user, require_founder_access, request_user_id

logger = logging.getLogger(__name__)

teams_router = APIRouter()

# ---------------------------------------------------------------------------
# Data layer
# ---------------------------------------------------------------------------

def _teams_path() -> Path:
    vault = os.environ.get("OBSIDIAN_VAULT", "/tmp/astra_docs")
    p = Path(vault)
    p.mkdir(parents=True, exist_ok=True)
    return p / "teams.json"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _load_store() -> dict[str, Any]:
    path = _teams_path()
    if not path.exists():
        return {"teams": {}, "invites": {}}
    try:
        data = json.loads(path.read_text())
        data.setdefault("teams", {})
        data.setdefault("invites", {})
        return data
    except Exception:
        return {"teams": {}, "invites": {}}


def _save_store(data: dict[str, Any]) -> None:
    _teams_path().write_text(json.dumps(data, indent=2, sort_keys=True))


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CreateTeamRequest(BaseModel):
    name: str
    founder_id: str


class CreateInviteRequest(BaseModel):
    founder_id: str
    email: str = ""


class AcceptInviteRequest(BaseModel):
    founder_id: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_owner(team: dict, user_id: str) -> bool:
    for m in team.get("members", []):
        if m["user_id"] == user_id and m["role"] == "owner":
            return True
    return False


def _is_member(team: dict, user_id: str) -> bool:
    for m in team.get("members", []):
        if m["user_id"] == user_id:
            return True
    return False


def _caller_id(request: Request) -> str:
    user_id = request_user_id(request)
    if user_id:
        return user_id
    return require_authenticated_user(request)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@teams_router.post("/teams")
async def create_team(body: CreateTeamRequest, request: Request):
    """Create a new team with the creator as owner."""
    if not body.name or not body.founder_id:
        raise HTTPException(status_code=400, detail="name and founder_id are required")
    require_founder_access(request, body.founder_id, min_role="admin")

    store = _load_store()
    team_id = uuid.uuid4().hex[:16]
    team: dict[str, Any] = {
        "id": team_id,
        "name": body.name,
        "owner_id": body.founder_id,
        "created_at": _now(),
        "members": [
            {
                "user_id": body.founder_id,
                "role": "owner",
                "joined_at": _now(),
            }
        ],
    }
    store["teams"][team_id] = team
    _save_store(store)
    logger.info("Team created: %s (owner=%s)", team_id, body.founder_id)
    return {"ok": True, "team": team}


@teams_router.get("/teams/me")
async def my_teams(request: Request, founder_id: str = ""):
    """List all teams the user belongs to."""
    if not founder_id:
        raise HTTPException(status_code=400, detail="founder_id query param required")
    require_founder_access(request, founder_id, min_role="viewer")

    store = _load_store()
    my = [t for t in store["teams"].values() if _is_member(t, founder_id)]
    return {"founder_id": founder_id, "teams": my}


@teams_router.get("/teams/{team_id}")
async def get_team(team_id: str, request: Request):
    """Return team info + members."""
    actor_id = _caller_id(request)
    store = _load_store()
    team = store["teams"].get(team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    if not _is_member(team, actor_id):
        raise HTTPException(status_code=403, detail="Team membership required")
    return {"team": team}


@teams_router.post("/teams/{team_id}/invites")
async def create_invite(team_id: str, body: CreateInviteRequest, request: Request):
    """Create an invite token (72h), optionally email it, return token + invite_url."""
    if not body.founder_id:
        raise HTTPException(status_code=400, detail="founder_id required")
    actor_id = require_founder_access(request, body.founder_id, min_role="owner")
    store = _load_store()
    team = store["teams"].get(team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    if not _is_owner(team, actor_id):
        raise HTTPException(status_code=403, detail="Only team owners can invite members")

    token = uuid.uuid4().hex
    expires_at = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ",
        time.gmtime(time.time() + 72 * 3600),
    )
    invite: dict[str, Any] = {
        "token": token,
        "team_id": team_id,
        "invited_by": actor_id,
        "email": body.email or "",
        "expires_at": expires_at,
        "status": "pending",
    }
    store["invites"][token] = invite
    _save_store(store)

    invite_url = f"https://astracreates.com/invite/{token}"

    # Send email if address provided
    email_result: dict[str, Any] = {}
    if body.email:
        try:
            from backend.tools.resend_tools import resend_send_email
            inviter = actor_id
            team_name = team["name"]
            html = (
                f"<div style='font-family:sans-serif;max-width:580px;margin:auto;padding:40px 24px'>"
                f"<h2>You've been invited to join <b>{team_name}</b> on Astra</h2>"
                f"<p style='color:#555'>{inviter} has invited you to collaborate on their Astra workspace.</p>"
                f"<a href='{invite_url}' style='background:#000;color:#fff;padding:12px 28px;"
                f"border-radius:6px;text-decoration:none;font-weight:600'>Accept Invitation</a>"
                f"<p style='color:#999;font-size:12px;margin-top:32px'>"
                f"This link expires in 72 hours. If you didn't expect this, ignore this email.</p>"
                f"</div>"
            )
            email_result = resend_send_email(
                to=body.email,
                from_email="noreply@astracreates.com",
                subject=f"You've been invited to join {team_name} on Astra",
                html=html,
            )
        except Exception as e:
            logger.warning("Invite email failed: %s", e)
            email_result = {"error": str(e), "sent": False}

    return {
        "ok": True,
        "token": token,
        "invite_url": invite_url,
        "expires_at": expires_at,
        "email_result": email_result,
    }


@teams_router.get("/invites/{token}")
async def get_invite(token: str):
    """Public endpoint — returns team name + inviter for the invite page."""
    store = _load_store()
    invite = store["invites"].get(token)
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")

    if invite["status"] != "pending":
        raise HTTPException(status_code=410, detail=f"Invite is {invite['status']}")

    if time.strptime(invite["expires_at"], "%Y-%m-%dT%H:%M:%SZ") < time.gmtime():
        raise HTTPException(status_code=410, detail="Invite has expired")

    team = store["teams"].get(invite["team_id"], {})
    return {
        "token": token,
        "team_id": invite["team_id"],
        "team_name": team.get("name", ""),
        "invited_by": invite["invited_by"],
        "email": invite["email"],
        "expires_at": invite["expires_at"],
    }


@teams_router.post("/invites/{token}/accept")
async def accept_invite(token: str, body: AcceptInviteRequest, request: Request):
    """Accept a team invite — add user to team as member."""
    if not body.founder_id:
        raise HTTPException(status_code=400, detail="founder_id required")
    require_founder_access(request, body.founder_id, min_role="viewer")

    store = _load_store()
    invite = store["invites"].get(token)
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found")

    if invite["status"] != "pending":
        raise HTTPException(status_code=410, detail=f"Invite is already {invite['status']}")

    if time.strptime(invite["expires_at"], "%Y-%m-%dT%H:%M:%SZ") < time.gmtime():
        invite["status"] = "expired"
        _save_store(store)
        raise HTTPException(status_code=410, detail="Invite has expired")

    team_id = invite["team_id"]
    team = store["teams"].get(team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    if _is_member(team, body.founder_id):
        # Already a member — idempotent accept
        invite["status"] = "accepted"
        _save_store(store)
        return {"ok": True, "team": team, "already_member": True}

    team["members"].append(
        {
            "user_id": body.founder_id,
            "role": "member",
            "joined_at": _now(),
        }
    )
    invite["status"] = "accepted"
    _save_store(store)
    logger.info("Invite %s accepted by %s, joined team %s", token, body.founder_id, team_id)
    return {"ok": True, "team": team}


@teams_router.delete("/teams/{team_id}/members/{user_id}")
async def remove_member(team_id: str, user_id: str, request: Request, founder_id: str = ""):
    """Remove a member from a team. Only owners can remove members."""
    if not founder_id:
        raise HTTPException(status_code=400, detail="founder_id query param required")
    actor_id = require_founder_access(request, founder_id, min_role="owner")

    store = _load_store()
    team = store["teams"].get(team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    if not _is_owner(team, actor_id):
        raise HTTPException(status_code=403, detail="Only team owners can remove members")

    if user_id == team["owner_id"]:
        raise HTTPException(status_code=400, detail="Cannot remove the team owner")

    before = len(team["members"])
    team["members"] = [m for m in team["members"] if m["user_id"] != user_id]
    if len(team["members"]) == before:
        raise HTTPException(status_code=404, detail="User is not a member of this team")

    _save_store(store)
    logger.info("Member %s removed from team %s by %s", user_id, team_id, actor_id)
    return {"ok": True, "team_id": team_id, "removed_user_id": user_id}
