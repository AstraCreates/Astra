"""
claude_code_scaffold — clones a GitHub repo, runs Claude Code to build real code, commits + pushes.
The technical agent calls this after github_create_repo to get actual working code into the repo.
"""
import logging
import os
import subprocess
import tempfile

from backend.config import settings

logger = logging.getLogger(__name__)

CLAUDE_BIN = "/Users/ishaangubbala/.local/bin/claude"


def claude_code_scaffold(
    repo_url: str,
    task: str,
    commit_message: str = "feat: scaffold via claude code",
    context: str = "",
    api_key: str = "",
    **_kwargs,
) -> dict:
    """
    Clone a GitHub repo, run Claude Code to implement the task, commit and push.
    Args:
        repo_url: full GitHub HTTPS URL (e.g. https://github.com/org/repo)
        task: detailed instruction for Claude Code (what to build / scaffold)
        commit_message: git commit message for the changes
        context: optional extra context (research findings, session notes, etc.)
    Returns: {success, repo_url, commit, output_preview, error?}
    """
    token = settings.github_token
    if not token:
        return {"error": "GITHUB_TOKEN not set — cannot clone/push"}

    # Inject token into clone URL
    if "github.com" in repo_url:
        clone_url = repo_url.replace("https://", f"https://{token}@")
    else:
        clone_url = repo_url

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            # Clone
            _run(["git", "clone", "--depth", "1", clone_url, tmpdir])

            # Configure git identity for the commit
            _run(["git", "config", "user.email", "astra-agent@astra.ai"], cwd=tmpdir)
            _run(["git", "config", "user.name", "Astra Technical Agent"], cwd=tmpdir)

            # Augment the task with a comprehensive scaffold directive
            context_section = f"\n\nSESSION CONTEXT (from other agents):\n{context}\n" if context else ""
            full_task = f"""Write actual files NOW using the Write tool. Do not plan, explain, or ask questions — start writing code immediately.

Scaffold a production-ready SaaS codebase for: {task}{context_section}

Required files (write all with real working code, no TODOs):
1. backend/main.py — FastAPI app with routers mounted
2. backend/models.py — SQLAlchemy models
3. backend/routers/auth.py — JWT /register /login /me
4. backend/routers/api.py — core business endpoints
5. backend/services/core.py — business logic
6. backend/requirements.txt
7. frontend/package.json
8. frontend/src/app/page.tsx — landing page
9. frontend/src/app/dashboard/page.tsx
10. docker-compose.yml
11. .env.example
12. README.md

Start with file 1 immediately. Write each file completely before moving to the next."""

            # Run Claude Code non-interactively
            env = os.environ.copy()
            env["HOME"] = os.environ.get("HOME", "/Users/ishaangubbala")
            # Use DeepInfra API key if provided (for user-facing runs)
            effective_key = api_key or getattr(settings, "deepinfra_api_key", "") or getattr(settings, "planner_model_api_key", "")
            if effective_key:
                env["ANTHROPIC_API_KEY"] = effective_key
            result = subprocess.run(
                [CLAUDE_BIN, "--print", full_task, "--output-format", "text", "--dangerously-skip-permissions"],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=600,
                env=env,
            )
            claude_output = result.stdout.strip()
            if result.returncode != 0:
                logger.warning("claude exited %d: %s", result.returncode, result.stderr[:300])

            # Stage any uncommitted changes Claude Code left behind
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=tmpdir, capture_output=True, text=True
            ).stdout.strip()

            if status:
                _run(["git", "add", "-A"], cwd=tmpdir)
                _run(["git", "commit", "-m", commit_message], cwd=tmpdir)

            # Check if there are local commits ahead of origin (Claude Code may have committed itself)
            ahead = subprocess.run(
                ["git", "rev-list", "--count", "HEAD@{upstream}..HEAD"],
                cwd=tmpdir, capture_output=True, text=True
            ).stdout.strip()

            if ahead == "0" and not status:
                return {
                    "success": True,
                    "repo_url": repo_url,
                    "commit": None,
                    "note": "No changes — Claude Code may have only described rather than written files",
                    "output_preview": claude_output[:400],
                }

            # Push all commits (ours + any Claude Code made)
            push_result = subprocess.run(
                ["git", "push"],
                cwd=tmpdir, capture_output=True, text=True, timeout=60
            )
            if push_result.returncode != 0:
                return {
                    "success": False,
                    "error": f"git push failed: {push_result.stderr[:300]}",
                    "output_preview": claude_output[:400],
                }

            # Get the commit SHA
            sha = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=tmpdir, capture_output=True, text=True
            ).stdout.strip()

            # Count total files in repo
            file_count = subprocess.run(
                ["git", "ls-files", "--cached"],
                cwd=tmpdir, capture_output=True, text=True
            ).stdout.strip().count("\n") + 1

            return {
                "success": True,
                "repo_url": repo_url,
                "commit": sha,
                "files_in_repo": file_count,
                "output_preview": claude_output[:400],
            }

        except subprocess.TimeoutExpired:
            return {"error": "claude_code_scaffold timed out (600s)"}
        except Exception as e:
            logger.error("claude_code_scaffold failed: %s", e)
            return {"error": str(e)}


def _run(cmd: list, cwd: str = None) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {r.stderr[:200]}")
    return r
