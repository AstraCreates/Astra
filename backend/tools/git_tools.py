"""
Git tools for the technical agent — write files, commit, push to a GitHub repo.
Maintains a persistent clone per session so incremental commits are cheap.
"""
import logging
import os
import subprocess
import tempfile
from pathlib import Path

from backend.config import settings

logger = logging.getLogger(__name__)

# session_id -> cloned tmpdir path (kept alive for iterative commits)
_clones: dict[str, str] = {}


def _clone_url(repo_url: str) -> str:
    token = settings.github_token
    if token and "github.com" in repo_url:
        return repo_url.replace("https://", f"https://{token}@")
    return repo_url


def _run(cmd: list, cwd: str = None, timeout: int = 60) -> str:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:2])} failed: {r.stderr[:300]}")
    return r.stdout.strip()


def _ensure_clone(repo_url: str, session_id: str = "default") -> str:
    """Clone repo once per session, return local path."""
    key = f"{session_id}:{repo_url}"
    if key in _clones and os.path.isdir(_clones[key]):
        return _clones[key]
    tmpdir = tempfile.mkdtemp(prefix="astra_repo_")
    _run(["git", "clone", "--depth", "1", _clone_url(repo_url), tmpdir])
    _run(["git", "config", "user.email", "astra-agent@astra.ai"], cwd=tmpdir)
    _run(["git", "config", "user.name", "Astra Technical Agent"], cwd=tmpdir)
    _clones[key] = tmpdir
    return tmpdir


def write_files_to_repo(
    repo_url: str,
    files: dict,
    commit_message: str = "feat: add files",
    session_id: str = "default",
) -> dict:
    """
    Write multiple files to a GitHub repo and push.
    Args:
        repo_url: full GitHub HTTPS URL
        files: dict of {relative_path: content_string}, e.g. {"src/app.py": "# code"}
        commit_message: git commit message
        session_id: used to reuse the clone across calls
    Returns: {success, commit, files_written, repo_url}
    """
    if not settings.github_token:
        return {"error": "GITHUB_TOKEN not set"}
    if not files:
        return {"error": "No files provided"}
    try:
        local = _ensure_clone(repo_url, session_id)

        # Pull latest
        try:
            _run(["git", "pull", "--rebase"], cwd=local, timeout=30)
        except Exception:
            pass

        # Write all files
        written = []
        for rel_path, content in files.items():
            full = Path(local) / rel_path
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content if isinstance(content, str) else str(content), encoding="utf-8")
            written.append(rel_path)

        # Stage and commit
        _run(["git", "add", "-A"], cwd=local)
        status = subprocess.run(["git", "status", "--porcelain"], cwd=local, capture_output=True, text=True).stdout.strip()
        if not status:
            return {"success": True, "note": "No changes to commit", "repo_url": repo_url}

        _run(["git", "commit", "-m", commit_message], cwd=local)

        # Push
        push = subprocess.run(["git", "push"], cwd=local, capture_output=True, text=True, timeout=60)
        if push.returncode != 0:
            return {"error": f"git push failed: {push.stderr[:300]}"}

        sha = _run(["git", "rev-parse", "--short", "HEAD"], cwd=local)
        return {
            "success": True,
            "repo_url": repo_url,
            "commit": sha,
            "files_written": written,
            "github_url": f"{repo_url}/tree/main",
        }
    except Exception as e:
        logger.error("write_files_to_repo failed: %s", e)
        return {"error": str(e)}


def run_claude_in_repo(
    repo_url: str,
    task: str,
    session_id: str = "default",
    context: str = "",
) -> dict:
    """
    Run Claude Code non-interactively inside the repo to implement a feature.
    Claude writes files, then we commit and push whatever it created.
    Args:
        repo_url: GitHub repo URL
        task: what Claude Code should build/implement
        session_id: reuses existing clone
        context: extra context (research notes, prior outputs, etc.)
    Returns: {success, commit, files_changed, output_preview}
    """
    if not settings.github_token:
        return {"error": "GITHUB_TOKEN not set"}

    claude_bin = "/Users/ishaangubbala/.local/bin/claude"
    if not os.path.exists(claude_bin):
        return {"error": f"Claude Code not found at {claude_bin}"}

    try:
        local = _ensure_clone(repo_url, session_id)

        # Pull latest
        try:
            _run(["git", "pull", "--rebase"], cwd=local, timeout=30)
        except Exception:
            pass

        ctx_section = f"\n\nCONTEXT FROM OTHER AGENTS:\n{context}\n" if context else ""
        full_task = (
            f"You are building a production MVP. Write REAL working code files using the Write tool.\n"
            f"Do NOT plan or explain — write files immediately.\n\n"
            f"TASK: {task}{ctx_section}\n\n"
            f"After writing all files, run `git add -A && git commit -m 'feat: {task[:60]}'` via Bash tool."
        )

        env = os.environ.copy()
        result = subprocess.run(
            [claude_bin, "--print", full_task, "--output-format", "text", "--dangerously-skip-permissions"],
            cwd=local,
            capture_output=True,
            text=True,
            timeout=600,
            env=env,
        )
        if result.returncode not in (0, 1):
            logger.warning("claude exited %d: %s", result.returncode, result.stderr[:200])

        # Stage any uncommitted changes
        status = subprocess.run(["git", "status", "--porcelain"], cwd=local, capture_output=True, text=True).stdout.strip()
        files_changed = [l[3:] for l in status.splitlines()] if status else []

        if status:
            _run(["git", "add", "-A"], cwd=local)
            _run(["git", "commit", "-m", f"feat: {task[:72]}"], cwd=local)

        # Check commits ahead of remote
        try:
            ahead = _run(["git", "rev-list", "--count", "HEAD@{upstream}..HEAD"], cwd=local)
        except Exception:
            ahead = "1"

        if ahead == "0" and not status:
            return {
                "success": True,
                "note": "No file changes detected — Claude may have only described",
                "output_preview": result.stdout[:600],
                "repo_url": repo_url,
            }

        push = subprocess.run(["git", "push"], cwd=local, capture_output=True, text=True, timeout=60)
        if push.returncode != 0:
            return {"error": f"push failed: {push.stderr[:300]}", "output_preview": result.stdout[:400]}

        sha = _run(["git", "rev-parse", "--short", "HEAD"], cwd=local)
        return {
            "success": True,
            "repo_url": repo_url,
            "commit": sha,
            "files_changed": files_changed,
            "github_url": f"{repo_url}/tree/main",
            "output_preview": result.stdout[:600],
        }
    except subprocess.TimeoutExpired:
        return {"error": "Timed out (600s)"}
    except Exception as e:
        logger.error("run_claude_in_repo failed: %s", e)
        return {"error": str(e)}
