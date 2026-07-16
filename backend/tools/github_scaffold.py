import asyncio
import base64
import hashlib
import logging
import threading
import uuid
from typing import Any, Callable

import requests

from backend.config import settings

logger = logging.getLogger(__name__)

_GH_API = "https://api.github.com"


# ── Durable idempotency for repo creation ────────────────────────────────────
# PLAN.md invariant: "Every external side effect has an idempotency key and
# durable receipt before Temporal retries are enabled." github_create_repo
# always appends a random uuid suffix to guarantee a unique name, which means
# a Temporal retry of this step previously created a genuinely new, orphaned,
# duplicate repo every time (the exact opposite of idempotent) -- there is no
# native GitHub idempotency-key mechanism to fall back on, so Astra's own
# durable action/receipt layer is the only protection available, and only
# when session_id (this codebase's run_id) is provided.
def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    box: dict = {}

    def _runner() -> None:
        try:
            box["result"] = asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001 - re-raised on the caller's thread below
            box["error"] = exc

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join()
    if "error" in box:
        raise box["error"]
    return box["result"]


def _create_repo_with_idempotency(
    *, run_id: str, step_id: str, args: dict[str, Any], create_call: Callable[[], dict],
) -> dict:
    if not run_id:
        return create_call()

    from backend.control_plane.action_executor import (
        ExternalActionRequest,
        canonicalize_tool_args,
        execute_external_action,
        get_default_repo_bundle,
    )

    canonical_args = canonicalize_tool_args(args)
    action_id = hashlib.sha256(f"{run_id}::{step_id}::github_create_repo::{canonical_args}".encode("utf-8")).hexdigest()
    bundle = get_default_repo_bundle()

    async def _effect(_effect_args: dict, _idempotency_key: str) -> dict:
        return create_call()

    result = _run_async(execute_external_action(
        ExternalActionRequest(
            run_id=run_id,
            step_id=step_id or "github_create_repo",
            action_id=action_id,
            tool="github_create_repo",
            args=args,
        ),
        action_repo=bundle.action_repo,
        receipt_repo=bundle.receipt_repo,
        approval_repo=bundle.approval_repo,
        execute_effect=_effect,
    ))
    out = dict(result.provider_result or {})
    out["_replayed"] = bool(result.replayed)
    return out


def github_create_repo(
    repo_name: str = "",
    description: str = "",
    stack: dict = None,
    mvp_features: list[dict] = None,
    private: bool = True,
    name: str = "",
    founder_id: str = "",
    session_id: str = "",
    **kwargs,
) -> dict:
    repo_name = repo_name or name
    if not isinstance(stack, dict):
        # Real production bug: a model passed stack as a list (or other
        # non-dict), which _generate_scaffold's stack.get(...) calls can't
        # handle — AttributeError: 'list' object has no attribute 'get'.
        stack = {}
    if mvp_features is None:
        mvp_features = []
    if isinstance(mvp_features, str):
        mvp_features = [{"name": f.strip()} for f in mvp_features.split(",") if f.strip()]
    """Create GitHub repo. Args: repo_name (str, kebab-case), description (str), stack (dict e.g. {"language":"Python","framework":"FastAPI"}), mvp_features (list of dicts e.g. [{"name":"Auth","description":"..."}]), private (bool). Returns: {repo_url, scaffolded}.
    Requires GITHUB_TOKEN. Falls back to returning scaffold content only.
    """
    token = getattr(settings, "github_token", None)
    if not token:
        scaffold = _generate_scaffold(repo_name, description, stack, mvp_features)
        return {
            "created": False,
            "scaffold": scaffold,
            "note": "GITHUB_TOKEN not set — scaffold generated but not pushed.",
        }

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        # Get authenticated user
        user_resp = requests.get(f"{_GH_API}/user", headers=headers, timeout=10)
        user_resp.raise_for_status()
        username = user_resp.json()["login"]

        # Create repo — append short suffix to avoid name collisions. Wrapped so a
        # Temporal retry of this step replays the durable receipt (same repo_url)
        # instead of creating a genuinely new, orphaned, duplicate repo.
        def _do_create() -> dict:
            unique_name = f"{repo_name}-{uuid.uuid4().hex[:6]}"
            resp = requests.post(
                f"{_GH_API}/user/repos",
                headers=headers,
                json={"name": unique_name, "description": description, "private": private, "auto_init": True},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            return {"repo_name": unique_name, "repo_url": data["html_url"]}

        create_result = _create_repo_with_idempotency(
            run_id=session_id,
            step_id="github_create_repo",
            args={"repo_name": repo_name, "description": description, "private": private},
            create_call=_do_create,
        )
        repo_name = create_result["repo_name"]
        repo_url = create_result["repo_url"]
        was_replayed = bool(create_result.get("_replayed", False))

        # A replayed receipt means an earlier attempt already created this repo AND
        # pushed its scaffold -- re-pushing would hit GitHub's "sha required to
        # update an existing file" error on every file.
        if was_replayed:
            return {
                "created": True,
                "repo_url": repo_url,
                "repo_name": repo_name,
                "owner": username,
                "files_pushed": [],
                "replayed": True,
            }

        # Push scaffold files
        scaffold = _generate_scaffold(repo_name, description, stack, mvp_features)
        for filename, content in scaffold.items():
            encoded = base64.b64encode(content.encode()).decode()
            requests.put(
                f"{_GH_API}/repos/{username}/{repo_name}/contents/{filename}",
                headers=headers,
                json={"message": f"chore: initial scaffold for {filename}", "content": encoded},
                timeout=15,
            )

        return {
            "created": True,
            "repo_url": repo_url,
            "repo_name": repo_name,
            "owner": username,
            "files_pushed": list(scaffold.keys()),
        }
    except Exception as e:
        logger.error("github_create_repo failed: %s", e)
        scaffold = _generate_scaffold(repo_name, description, stack, mvp_features)
        return {"created": False, "scaffold": scaffold, "error": str(e)}


def _generate_scaffold(repo_name: str, description: str, stack: dict, mvp_features: list[dict]) -> dict:
    features_md = "\n".join(
        f"- [ ] **{f.get('name', f)}** ({f.get('priority', 'p1')})" if isinstance(f, dict) else f"- [ ] {f}"
        for f in mvp_features
    )
    backend = stack.get("backend", "FastAPI")
    frontend = stack.get("frontend", "Next.js")
    db = stack.get("db", "PostgreSQL")

    readme = f"""# {repo_name}

{description}

## Stack
- **Backend**: {backend}
- **Frontend**: {frontend}
- **Database**: {db}
- **Hosting**: {stack.get("hosting", "Vercel + Railway")}

## MVP Features
{features_md}

## Getting Started

```bash
# Install dependencies
npm install        # frontend
pip install -r requirements.txt  # backend

# Run dev servers
npm run dev        # frontend (localhost:3000)
uvicorn main:app --reload  # backend (localhost:8000)
```

## Built with [Astra](https://astra.ai) — AI founding team for first-time founders.
"""

    gitignore = """# Python
__pycache__/
*.pyc
.env
venv/
.venv/

# Node
node_modules/
.next/
dist/

# Misc
.DS_Store
*.log
"""

    env_example = """# Backend
DATABASE_URL=postgresql://user:pass@localhost:5432/db
SECRET_KEY=change-me

# Frontend
NEXT_PUBLIC_API_URL=http://localhost:8000
"""

    return {
        "README.md": readme,
        ".gitignore": gitignore,
        ".env.example": env_example,
    }
