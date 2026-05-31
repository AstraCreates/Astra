"""
claude_code_scaffold — clones a GitHub repo, runs Claude Code to build real code, commits + pushes.
The technical agent calls this after github_create_repo to get actual working code into the repo.
"""
import hashlib
import json
import logging
import os
import subprocess
import tempfile
import uuid

from backend.config import settings

logger = logging.getLogger(__name__)



def claude_code_scaffold(
    repo_url: str,
    task: str = "",
    goal: str = "",
    commit_message: str = "feat: scaffold via claude code",
    context: str = "",
    api_key: str = "",
    **_kwargs,
) -> dict:
    """
    Clone a GitHub repo, run Claude Code to implement the task, commit and push.
    Args:
        repo_url: full GitHub HTTPS URL (e.g. https://github.com/org/repo)
        task: detailed instruction for Claude Code (what to build / scaffold). Also accepts 'goal' as alias.
        goal: alias for task (accepted for agent compatibility)
        commit_message: git commit message for the changes
        context: optional extra context (research findings, session notes, etc.)
    Returns: {success, repo_url, commit, output_preview, error?}
    """
    # Accept 'goal' as alias for 'task'
    task = task or goal
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

            # Run openclaude with DeepInfra backend
            from backend.tools.git_tools import OPENCLAUDE_BIN, _make_env
            env = _make_env()
            env["HOME"] = os.environ.get("HOME", "/root")
            if api_key:
                env["OPENAI_API_KEY"] = api_key

            # Stable session UUID per repo — persistent conversation like TUI
            repo_hash = hashlib.md5(repo_url.encode()).hexdigest()
            oc_session_id = str(uuid.UUID(repo_hash))

            # openclaude ignores subprocess cwd — must cd in shell so it writes files in the repo dir.
            # Also: openclaude refuses --dangerously-skip-permissions when running as root, so we
            # must drop to the 'astra' non-root user. sudo env_reset strips API keys, so we pass
            # them explicitly via `sudo -u astra env KEY=VAL ...` rather than sudo -E.
            escaped_task = full_task.replace("'", "'\\''")
            oc_args = (
                f"{OPENCLAUDE_BIN} --print --allow-dangerously-skip-permissions --dangerously-skip-permissions"
                f" --provider openai --model deepseek-ai/DeepSeek-V4-Flash"
                f" --session-id {oc_session_id}"
            )
            import shutil as _shutil
            if os.getuid() == 0 and _shutil.which("sudo"):
                # Pass API keys explicitly since sudo env_reset strips them
                openai_key = env.get("OPENAI_API_KEY", "")
                openai_base = env.get("OPENAI_BASE_URL", "https://api.deepinfra.com/v1/openai")
                openai_model = env.get("OPENAI_MODEL", "deepseek-ai/DeepSeek-V4-Flash")
                # Make tmpdir writable by astra user
                subprocess.run(["chmod", "-R", "777", tmpdir], capture_output=True)
                shell_cmd = (
                    f"cd {tmpdir!r} && "
                    f"sudo -u astra env HOME=/home/astra "
                    f"OPENAI_API_KEY={openai_key!r} "
                    f"OPENAI_BASE_URL={openai_base!r} "
                    f"OPENAI_MODEL={openai_model!r} "
                    f"{oc_args} '{escaped_task}'"
                )
            else:
                shell_cmd = f"cd {tmpdir!r} && {oc_args} '{escaped_task}'"

            result = subprocess.run(
                shell_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=600,
                env=env,
            )
            claude_output = result.stdout.strip()
            if result.returncode not in (0, 1):
                logger.warning("openclaude exited %d: %s", result.returncode, result.stderr[:300])

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
