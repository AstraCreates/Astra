"""
Git tools for the technical agent — write files, commit, push to a GitHub repo.
run_mvp_loop is the primary entry point: iterates Claude Code until MVP is complete.

Workspaces live at ~/Documents/astra-workspaces/<session_id>/<repo_name>/
free-claude-code proxies the claude CLI through OpenRouter so no Anthropic key needed.
"""
import hashlib
import json
import logging
import os
import re
import subprocess
import threading
import uuid
from pathlib import Path

from backend.config import settings

# Cap concurrent Claude Code (openclaude) subprocesses across ALL sessions so a
# burst of technical-agent builds can't exhaust CPU/RAM on a small box. Each
# build is mostly LLM-I/O bound; this just prevents pile-ups. Tune via env.
_BUILD_SLOTS = int(os.environ.get("ASTRA_MAX_CONCURRENT_BUILDS", "4"))
_build_semaphore = threading.Semaphore(_BUILD_SLOTS)

logger = logging.getLogger(__name__)

def _find_claude_bin() -> str:
    """Find openclaude binary (supports --provider flag). Falls back to claude."""
    import shutil
    # openclaude first — it supports --provider openai for OpenRouter
    for candidate in [
        "/opt/homebrew/bin/openclaude",
        "/usr/local/bin/openclaude",
        shutil.which("openclaude") or "",
        "/opt/homebrew/bin/claude",
        "/usr/local/bin/claude",
        "/usr/bin/claude",
        shutil.which("claude") or "",
    ]:
        if candidate and os.path.isfile(candidate):
            return candidate
    return "openclaude"

OPENCLAUDE_BIN = _find_claude_bin()


def _research_error_docs(agent_output: str) -> str:
    """
    If agent_output contains library/API/framework errors, search for relevant docs
    and return a context block to inject into the next openclaude message.
    Returns empty string if no errors detected or search fails.
    """
    import re as _re
    # Error detection patterns → extract library/API name for doc search
    patterns = [
        (r"Cannot find module '(@?[^']+)'", "npm package docs: {}"),
        (r"Module not found: Can't resolve '(@?[^']+)'", "Next.js import {} docs fix"),
        (r"ImportError: cannot import name '([^']+)' from '([^']+)'", "{1} {0} python docs"),
        (r"ModuleNotFoundError: No module named '([^']+)'", "python {} docs install"),
        (r"error TS\d+:.*'([^']+)'", "TypeScript error {} fix"),
        (r"(?:TypeError|AttributeError|KeyError): .*?'([^']+)'", "{} python error fix"),
        (r"404.*?npm.*?([a-z@][a-z0-9@/_-]+)", "npm package {} version docs"),
        (r"No matching version found for ([^\s.]+)", "npm {} correct version"),
        (r"(?:Error|error): ([A-Z][a-zA-Z]+Error[^\n]{0,60})", "fix {}"),
        (r"ENOENT.*?'([^']+)'", "Node.js ENOENT {} fix"),
        (r"(?:fastapi|starlette|uvicorn|pydantic).*?(?:Error|error)[^\n]{0,80}", "FastAPI {} docs"),
        (r"(?:clerk|supabase|stripe|vercel).*?(?:Error|error|invalid|missing)[^\n]{0,80}", "{} API docs"),
    ]

    queries = []
    for pat, tmpl in patterns:
        m = _re.search(pat, agent_output, _re.IGNORECASE)
        if m:
            try:
                groups = m.groups()
                q = tmpl.format(*([groups[i] if i < len(groups) else "" for i in range(tmpl.count("{}"))]
                                   if tmpl.count("{}") > 1 else [groups[0] if groups else m.group(0)]))
                queries.append(q[:120])
            except Exception:
                queries.append(m.group(0)[:80])
            if len(queries) >= 2:
                break

    if not queries:
        # Generic: only research if clear error indicators present
        error_keywords = ["Error:", "error:", "failed", "cannot", "undefined", "missing", "not found"]
        if not any(kw in agent_output for kw in error_keywords):
            return ""
        # Extract most error-like line
        for line in agent_output.split("\n"):
            if any(kw in line for kw in ["Error:", "error:", "failed", "Cannot"]):
                queries.append(f"fix: {line.strip()[:100]}")
                break

    if not queries:
        return ""

    try:
        from backend.tools.web_search import web_search
        all_snippets = []
        for q in queries[:2]:
            logger.info("Researching error docs for: %s", q)
            result = web_search(query=q, max_results=3)
            for r in (result.get("results") or [])[:2]:
                title = r.get("title", "")
                snippet = r.get("snippet") or r.get("description") or ""
                url = r.get("url", "")
                if snippet:
                    all_snippets.append(f"• [{title}] {snippet}\n  Source: {url}")
        if not all_snippets:
            return ""
        return (
            "\n\n--- DOCUMENTATION CONTEXT (researched for the errors above) ---\n"
            + "\n".join(all_snippets)
            + "\n--- END DOCUMENTATION CONTEXT ---"
        )
    except Exception as e:
        logger.debug("Error doc research failed: %s", e)
        return ""

# Workspace root — configurable via ASTRA_WORKSPACE env var for Docker volume mounts
WORKSPACE_ROOT = Path(os.environ.get("ASTRA_WORKSPACE", str(Path.home() / "Documents" / "astra-workspaces")))
WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)

# session_id:repo_url -> workspace path
_clones: dict[str, str] = {}


def _git_trust_workspaces() -> None:
    """Mark workspaces as safe so git never refuses with 'detected dubious ownership'.

    The workspace volume is owned by a different uid than the process (and the
    scaffold subprocess may run as yet another user), which made every git add/
    push fail and produced empty repos. Register safe.directory in the SYSTEM
    config so it applies to all users, and globally as a fallback.
    """
    for scope in ("--system", "--global"):
        try:
            subprocess.run(["git", "config", scope, "--add", "safe.directory", "*"],
                           capture_output=True, timeout=10)
        except Exception:
            pass


_git_trust_workspaces()


def _clone_url(repo_url: str) -> str:
    token = settings.github_token
    if token and "github.com" in repo_url:
        return repo_url.replace("https://", f"https://{token}@")
    return repo_url


def _sh(cmd: list, cwd: str = None, timeout: int = 60) -> str:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:2])} failed: {r.stderr[:2000]}")
    return r.stdout.strip()


def _workspace_dir(workspace_key: str, repo_url: str) -> Path:
    """Deterministic persistent workspace path for a workspace scope + repo."""
    repo_name = re.sub(r"[^a-zA-Z0-9._-]+", "-", repo_url.rstrip("/").split("/")[-1])[:80] or "repo"
    safe_scope = re.sub(r"[^a-zA-Z0-9._-]+", "-", workspace_key)[:120] or "workspace"
    return (WORKSPACE_ROOT / safe_scope / repo_name).resolve()


def _ensure_within_workspace_root(path: Path) -> Path:
    root = WORKSPACE_ROOT.resolve()
    resolved = path.resolve()
    if resolved == root or root in resolved.parents:
        return resolved
    raise ValueError(f"workspace path escapes ASTRA_WORKSPACE: {resolved}")


def remove_workspace(session_id: str) -> bool:
    """Delete a session's entire workspace tree (all repos under it). Best-effort —
    runs as root in the container, so chmod first to clear astra-owned, read-only
    git objects that would otherwise block rmtree. Returns True if anything removed."""
    import shutil
    if not session_id:
        return False
    target = WORKSPACE_ROOT / session_id
    if not target.exists():
        # Drop any stale in-memory clone refs for this session anyway.
        for k in [k for k in _clones if k.startswith(f"{session_id}:")]:
            _clones.pop(k, None)
        return False
    try:
        if os.getuid() == 0:
            subprocess.run(["chmod", "-R", "u+rwX", str(target)], capture_output=True, timeout=30)
    except Exception:
        pass
    shutil.rmtree(target, ignore_errors=True)
    for k in [k for k in _clones if k.startswith(f"{session_id}:")]:
        _clones.pop(k, None)
    logger.info("Removed workspace for session %s (%s)", session_id, target)
    return not target.exists()


def _ensure_clone(repo_url: str, session_id: str = "default", workspace_key: str | None = None) -> str:
    """Clone repo into persistent workspace, return local path."""
    import time
    scope = workspace_key or session_id
    key = f"{scope}:{repo_url}"
    if key in _clones and os.path.isdir(_clones[key]):
        return _clones[key]
    workspace = _ensure_within_workspace_root(_workspace_dir(scope, repo_url))
    workspace.parent.mkdir(parents=True, exist_ok=True)
    if workspace.exists():
        # Already cloned in a prior run — just pull
        try:
            _sh(["git", "pull", "--rebase"], cwd=str(workspace), timeout=30)
        except Exception:
            pass
    else:
        # Retry clone up to 3 times with backoff — GitHub repo may not be ready yet
        last_err: Exception = RuntimeError("clone never attempted")
        for attempt in range(3):
            try:
                _sh(["git", "clone", "--depth", "1", _clone_url(repo_url), str(workspace)])
                break
            except Exception as e:
                last_err = e
                logger.warning("clone attempt %d/3 failed for %s: %s", attempt + 1, repo_url, str(e)[:400])
                if attempt < 2:
                    time.sleep(5 * (attempt + 1))
        else:
            raise last_err
        _sh(["git", "config", "user.email", "astra-agent@astra.ai"], cwd=str(workspace))
        _sh(["git", "config", "user.name", "Astra Agent"], cwd=str(workspace))
    # Ensure astra user (uid 1000) can write files in the workspace when running as root
    if os.getuid() == 0:
        subprocess.run(["chmod", "-R", "777", str(workspace)], capture_output=True)
    _clones[key] = str(workspace)
    return str(workspace)


def _root_session_id(session_id: str) -> str:
    """Walk parent_session_id up to the launch session so continuation/operating runs
    build in the SAME workspace as the launch (extend the same repo, no re-clone, no
    accidental new repo per goal)."""
    try:
        from backend.core.session_store import get_session_meta
        sid, seen = session_id, set()
        for _ in range(12):
            parent = (get_session_meta(sid) or {}).get("parent_session_id") or ""
            if not parent or parent in seen:
                break
            seen.add(parent)
            sid = parent
        return sid
    except Exception:
        return session_id


def _company_workspace_key(founder_id: str, company_id: str | None = None) -> str:
    resolved_company = company_id or founder_id or "company"
    return f"company-{resolved_company}"


def _get_workspace(
    repo_url: str,
    session_id: str,
    founder_id: str = "",
    company_id: str = "",
) -> tuple[str, bool]:
    """Return (local_path, is_github). Clones from GitHub when a repo + token are
    available, otherwise builds in a fresh local git workspace so MVPs can be
    built and previewed with NO GitHub required. Continuation runs reuse the launch
    session's workspace (resolved via the parent chain)."""
    session_id = _root_session_id(session_id)
    workspace_key = session_id
    if repo_url and founder_id and company_id:
        workspace_key = _company_workspace_key(founder_id, company_id)
    if repo_url and settings.github_token:
        try:
            return _ensure_clone(repo_url, session_id, workspace_key=workspace_key), True
        except Exception as e:
            # Repo creation blocked/failed → don't let the build die; build locally.
            logger.warning("clone failed (%s) — building in a local workspace instead", str(e)[:160])
    ws = _ensure_within_workspace_root(WORKSPACE_ROOT / re.sub(r"[^a-zA-Z0-9._-]+", "-", session_id)[:80] / "mvp")
    ws.mkdir(parents=True, exist_ok=True)
    if not (ws / ".git").exists():
        try:
            _sh(["git", "init"], cwd=str(ws))
            _sh(["git", "config", "user.email", "astra-agent@astra.ai"], cwd=str(ws))
            _sh(["git", "config", "user.name", "Astra Agent"], cwd=str(ws))
        except Exception:
            pass
    if os.getuid() == 0:
        subprocess.run(["chmod", "-R", "777", str(ws)], capture_output=True)
    return str(ws), False


def _list_built_files(local: str) -> list[str]:
    """All files in the workspace (works without git tracking), excluding noise."""
    out = []
    for root, dirs, fs in os.walk(local):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", ".next", "__pycache__")]
        for f in fs:
            rel = os.path.relpath(os.path.join(root, f), local)
            if not rel.startswith(".oc_session"):
                out.append(rel)
    return sorted(out)


def _dummy_env_value(key: str) -> str:
    ku = key.upper()
    if "URL" in ku:
        return "https://placeholder.supabase.co" if "SUPABASE" in ku else "https://placeholder.example.com"
    if any(w in ku for w in ("KEY", "SECRET", "TOKEN", "PASSWORD", "DSN")):
        return "placeholder_" + "x" * 32
    return "placeholder"


def _placeholder_env(local: str) -> dict:
    """Dummy env values (from .env.example) so the build/deploy succeeds without
    real credentials — the preview renders even before the founder adds keys."""
    env: dict[str, str] = {}
    for fname in (".env.example", ".env.local.example", ".env.sample", ".env.template"):
        p = Path(local) / fname
        if p.exists():
            try:
                for line in p.read_text().splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k = line.split("=", 1)[0].strip()
                    if k and k.isidentifier():
                        env[k] = _dummy_env_value(k)
            except Exception:
                pass
            break
    return env


def _vercel_root_dir(local: str) -> str:
    """Vercel root_directory: '' if the app is at repo root, else the subdir."""
    if (Path(local) / "package.json").exists():
        return ""
    for sub in ("frontend", "web", "app", "client"):
        if (Path(local) / sub / "package.json").exists():
            return sub
    return ""


def _node_app_dir(local: str) -> Path | None:
    """Return the most likely Node/Next app directory for deterministic checks."""
    root = Path(local)
    for sub in ("frontend", "", "web", "app", "client"):
        p = root / sub / "package.json" if sub else root / "package.json"
        if p.exists():
            return p.parent
    return None


def _npm_build_passes(local: str, timeout: int = 900) -> tuple[bool | None, str]:
    """Run the production build once (cheaper + more reliable than an LLM's opinion).
    Returns (True=passed, False=ran-and-failed/timed-out, None=no Node app found).
    Runs as the `astra` user when root so it doesn't leave root-owned node_modules/.next
    that the astra build/preview passes then can't touch."""
    app_dir = _node_app_dir(local)
    if app_dir is None:
        return None, "No package.json found — no Node app was produced."
    cache = os.environ.get("ASTRA_NPM_CACHE", "/data/npm-cache")
    env = _apply_npm_cache_env(os.environ.copy())
    install = "npm install --legacy-peer-deps --prefer-offline --no-audit --no-fund"

    def _run(shell: str, t: int):
        inner = f"cd {str(app_dir)!r} && {shell}"
        if os.getuid() == 0:
            c = ["sudo", "-u", "astra", "env", f"npm_config_cache={cache}",
                 "npm_config_prefer_offline=true", "HOME=/home/astra", "bash", "-lc", inner]
        else:
            c = ["bash", "-lc", inner]
        r = subprocess.run(c, capture_output=True, text=True, timeout=t, env=env)
        return r.returncode, "\n".join(p for p in (r.stdout, r.stderr) if p)

    # Speed: deps are installed once (by the build pass / a prior check). When
    # node_modules already exists, run ONLY `npm run build` — skip the redundant
    # re-install that was eating minutes on every recovery round. If the build then
    # fails on a missing module (a dep was added), install once and rebuild.
    try:
        if (app_dir / "node_modules").is_dir():
            rc, out = _run("npm run build", timeout)
            if rc != 0 and re.search(r"Cannot find module|Module not found|Can't resolve|ERR_MODULE_NOT_FOUND", out):
                rc, out = _run(f"{install} && npm run build", timeout)
        else:
            rc, out = _run(f"{install} && npm run build", timeout)
        return rc == 0, out[-4000:]
    except subprocess.TimeoutExpired as e:
        out = "\n".join(p for p in (e.stdout, e.stderr) if isinstance(p, str))
        return False, (out or f"npm build timed out after {timeout}s")[-4000:]
    except Exception as e:
        return False, str(e)


def _flatten_nested_repos(local: str) -> None:
    """Strip nested .git from scaffolded subprojects so they're tracked as normal
    files. Tools like create-next-app run their own `git init`, which turns the
    subdir into a gitlink with no commit — then `git add -A` fails with
    'does not have a commit checked out' and the build commits nothing."""
    import shutil
    try:
        root = Path(local).resolve()
        root_git = (root / ".git").resolve()
        for gitpath in root.rglob(".git"):
            if "/node_modules/" in str(gitpath):
                continue
            try:
                if gitpath.resolve() == root_git:
                    continue
            except Exception:
                continue
            if gitpath.is_dir():
                shutil.rmtree(gitpath, ignore_errors=True)
            else:
                try:
                    gitpath.unlink()
                except Exception:
                    pass
    except Exception:
        pass


def _stage_all(local: str) -> None:
    """Stage all files (no commit) so disk contents are tracked in local mode."""
    _flatten_nested_repos(local)
    try:
        _sh(["git", "add", "-A"], cwd=local)
    except Exception:
        pass


def _pull(local: str) -> None:
    try:
        _sh(["git", "pull", "--rebase"], cwd=local, timeout=30)
    except Exception:
        pass


def _staged_files(local: str) -> list[str]:
    out = subprocess.run(["git", "ls-files", "--cached"], cwd=local, capture_output=True, text=True).stdout
    return [l for l in out.splitlines() if l.strip()]


def _commit_and_push(local: str, message: str) -> str | None:
    """Stage all, commit if dirty, push. Returns short SHA or None."""
    _flatten_nested_repos(local)
    status = subprocess.run(["git", "status", "--porcelain"], cwd=local, capture_output=True, text=True).stdout.strip()
    if status:
        _sh(["git", "add", "-A"], cwd=local)
        _sh(["git", "commit", "-m", message], cwd=local)
    try:
        ahead = _sh(["git", "rev-list", "--count", "HEAD@{upstream}..HEAD"], cwd=local)
    except Exception:
        ahead = "1"
    if ahead == "0":
        return None
    # Web + technical agents share the repo and push concurrently, so a push can be
    # rejected (non-fast-forward / fetch first). Integrate the remote with a rebase and
    # retry instead of failing the whole build.
    branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=local, capture_output=True, text=True).stdout.strip() or "main"
    last_err = ""
    for attempt in range(3):
        push = subprocess.run(["git", "push"], cwd=local, capture_output=True, text=True, timeout=60)
        if push.returncode == 0:
            return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=local, capture_output=True, text=True).stdout.strip()
        last_err = (push.stderr or "")[:200]
        # Rejected — pull the remote in, rebasing our commits on top, then retry.
        subprocess.run(["git", "fetch", "origin"], cwd=local, capture_output=True, text=True, timeout=60)
        rb = subprocess.run(["git", "pull", "--rebase", "--autostash", "origin", branch],
                            cwd=local, capture_output=True, text=True, timeout=120)
        if rb.returncode != 0:
            # Rebase conflict — abort and prefer the remote so the build doesn't wedge.
            subprocess.run(["git", "rebase", "--abort"], cwd=local, capture_output=True, text=True)
            subprocess.run(["git", "reset", "--soft", f"origin/{branch}"], cwd=local, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", message, "--allow-empty"], cwd=local, capture_output=True, text=True)
    raise RuntimeError(f"git push failed after retries: {last_err}")


def _make_env() -> dict:
    # openclaude talks to OpenRouter (OpenAI-compatible). Use the OpenRouter key +
    # base + the configured MVP build model (a strong tool-use model on OpenRouter).
    from backend.core.key_rotator import get_openrouter_key
    or_key = (
        get_openrouter_key()
        or getattr(settings, "openrouter_api_key", "")
        or getattr(settings, "planner_model_api_key", "")
    )
    env = os.environ.copy()
    env["OPENAI_BASE_URL"] = getattr(settings, "openrouter_base_url", "") or "https://openrouter.ai/api/v1"
    env["OPENAI_API_KEY"] = or_key
    env["OPENAI_MODEL"] = getattr(settings, "mvp_build_model", "") or "xiaomi/mimo-v2.5-pro"
    # Persistent, shared npm cache so `npm install` (run by every build pass and every
    # session) pulls packages from local disk instead of re-downloading — the biggest
    # chunk of build time. prefer-offline = use the cache whenever possible.
    _apply_npm_cache_env(env)
    return env


_NPM_CACHE_DIR = os.environ.get("ASTRA_NPM_CACHE", "/data/npm-cache")


def _apply_npm_cache_env(env: dict) -> dict:
    """Point npm at a persistent shared cache + offline-first. Best-effort mkdir."""
    try:
        Path(_NPM_CACHE_DIR).mkdir(parents=True, exist_ok=True)
        if os.getuid() == 0:
            subprocess.run(["chmod", "-R", "777", _NPM_CACHE_DIR], capture_output=True, timeout=15)
    except Exception:
        pass
    env["npm_config_cache"] = _NPM_CACHE_DIR
    env["npm_config_prefer_offline"] = "true"
    env["npm_config_audit"] = "false"
    env["npm_config_fund"] = "false"
    return env


def _record_build_usage(result_obj: dict, founder_id: str = "", session_id: str = "") -> None:
    """Bill an openclaude build as separate, higher-rate 'MVP credits'.

    MVP tool-use work costs more than normal agent tokens (mvp_credit_multiplier),
    and is logged under an 'MVP build' reason so it shows up distinctly.
    """
    try:
        if not founder_id:
            return
        usage = result_obj.get("usage") or {}
        cache_read = int(usage.get("cache_read_input_tokens", 0) or 0)
        inp = sum(int(usage.get(k, 0) or 0) for k in ("input_tokens", "cache_creation_input_tokens")) + cache_read
        out = int(usage.get("output_tokens", 0) or 0)
        total_t = inp + out
        turns = int(result_obj.get("num_turns", 0) or 0)
        if total_t <= 0:
            return
        from backend.core.usage import cost_to_credits, BASE_MARKUP
        from backend.credits.store import deduct_credits
        # Builds bill at a higher markup: BASE (10×) × mvp_credit_multiplier.
        mult = float(getattr(settings, "mvp_credit_multiplier", 3.0) or 3.0)
        build_model = getattr(settings, "mvp_build_model", "") or "xiaomi/mimo-v2.5-pro"
        markup = BASE_MARKUP * mult
        credits = cost_to_credits(build_model, inp, out, cache_read, markup=markup)
        deduct_credits(
            founder_id, credits,
            f"MVP build — {turns} tool rounds, {total_t:,} tokens ({markup:.0f}x markup)",
            session_id or None,
        )
        logger.info("MVP build billed founder=%s credits=%s tokens=%s turns=%s", founder_id, credits, total_t, turns)
    except Exception as e:
        logger.warning("MVP build billing failed: %s", e)


def _stream_build_events(cmd: list, cwd: str, timeout: int, env: dict,
                         founder_id: str, app_session_id: str, oc_session_id: str, agent: str = "technical") -> str:
    """Run openclaude with stream-json output, publishing each step (assistant
    text, tool calls, and every file as it's written) live to the session so the
    technical-agent preview shows the build happening — no GitHub needed."""
    import time as _t
    import threading as _th
    from backend.core.events import publish_sync

    files: dict[str, str] = {}
    tool_names: dict[str, str] = {}   # tool_use_id -> tool name (to label results)
    tool_targets: dict[str, str] = {}  # tool_use_id -> short target (cmd/path)
    result_obj = None
    stderr_lines: list[str] = []

    def pub(ev: dict) -> None:
        try:
            publish_sync(app_session_id, {"type": "agent_build", "agent": agent, **ev})
        except Exception:
            pass

    def _block_text(content) -> str:
        """Flatten a tool_result content (str or list of blocks) to plain text."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for b in content:
                if isinstance(b, dict):
                    parts.append(b.get("text") or b.get("content") or "")
                else:
                    parts.append(str(b))
            return "\n".join(p for p in parts if p)
        return str(content or "")

    with _build_semaphore:
        proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, env=env, bufsize=1)
        watchdog = _th.Timer(timeout, proc.kill)
        watchdog.daemon = True
        watchdog.start()
        def _pump_stderr() -> None:
            try:
                assert proc.stderr is not None
                for raw in proc.stderr:
                    line = raw.strip()
                    if not line:
                        continue
                    stderr_lines.append(line)
                    pub({"kind": "error", "text": line[-2000:]})
            except Exception:
                pass

        stderr_thread = _th.Thread(target=_pump_stderr, daemon=True)
        stderr_thread.start()
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                etype = ev.get("type")
                if etype == "system":
                    pub({"kind": "start", "tools": ev.get("tools", [])})
                elif etype == "assistant":
                    for block in (ev.get("message", {}).get("content") or []):
                        bt = block.get("type")
                        if bt == "text" and (block.get("text") or "").strip():
                            pub({"kind": "log", "text": block["text"][:2000]})
                        elif bt == "tool_use":
                            name = block.get("name") or ""
                            inp = block.get("input") or {}
                            bid = block.get("id") or ""
                            if bid:
                                tool_names[bid] = name
                            if name in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
                                path = inp.get("file_path") or inp.get("path") or inp.get("notebook_path") or ""
                                content = inp.get("content") or inp.get("new_string") or ""
                                if bid:
                                    tool_targets[bid] = path
                                if path:
                                    files[path] = content
                                    verb = "edited" if name in ("Edit", "MultiEdit") else "wrote"
                                    pub({"kind": "file", "path": path, "content": content[:20000], "size": len(content), "verb": verb})
                            elif name == "Bash":
                                cmd = (inp.get("command") or "")[:500]
                                desc = (inp.get("description") or "")[:120]
                                if bid:
                                    tool_targets[bid] = cmd
                                pub({"kind": "command", "command": cmd, "desc": desc})
                            elif name == "TodoWrite":
                                todos = inp.get("todos") or []
                                items = [str(t.get("content") or t.get("task") or t)[:80] for t in todos if isinstance(t, (dict, str))]
                                active = next((str(t.get("content") or "")[:80] for t in todos
                                               if isinstance(t, dict) and t.get("status") == "in_progress"), "")
                                pub({"kind": "plan", "text": f"Plan ({len(items)} steps)" + (f" — now: {active}" if active else ""),
                                     "todos": items[:12]})
                            elif name in ("Read", "Glob", "Grep"):
                                tgt = str(inp.get("file_path") or inp.get("pattern") or "")[:120]
                                if bid:
                                    tool_targets[bid] = tgt
                                pub({"kind": "tool", "tool": name, "target": tgt})
                            else:
                                pub({"kind": "tool", "tool": name, "target": str(inp.get("file_path") or inp.get("url") or "")[:120]})
                elif etype == "user":
                    # Tool results — bash stdout/stderr, test output, build errors. The
                    # detail that makes the build watchable. Only surface Bash results
                    # (file reads are noise; we already stream files separately).
                    for block in (ev.get("message", {}).get("content") or []):
                        if not isinstance(block, dict) or block.get("type") != "tool_result":
                            continue
                        rid = block.get("tool_use_id") or ""
                        rname = tool_names.get(rid, "")
                        if rname and rname not in ("Bash",):
                            continue
                        out = _block_text(block.get("content")).strip()
                        if not out:
                            continue
                        is_err = bool(block.get("is_error"))
                        tail = out[-700:] if len(out) > 700 else out
                        pub({"kind": "error" if is_err else "output",
                             "text": tail, "command": tool_targets.get(rid, "")[:120]})
                elif etype == "result":
                    result_obj = ev
        finally:
            watchdog.cancel()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
            stderr_thread.join(timeout=1)

    if isinstance(result_obj, dict):
        _record_build_usage(result_obj, founder_id, oc_session_id)
        pub({"kind": "done", "files": list(files.keys()), "exit_code": proc.returncode or 0})
        return (result_obj.get("result") or "").strip()
    stderr_text = "\n".join(stderr_lines).strip()
    if stderr_text:
        pub({"kind": "error", "text": stderr_text[-2000:]})
    pub({"kind": "done", "files": list(files.keys()), "exit_code": proc.returncode or 0,
         "error": stderr_text[-2000:] if stderr_text else ""})
    return stderr_text


def _run_claude(local: str, prompt: str, session_id: str = None, timeout: int = 480, model: str = None,
                founder_id: str = "", app_session_id: str = "", agent: str = "technical") -> str:
    """
    Send one message to openclaude. When app_session_id is set, the build streams
    live to that session (transcript + files). Otherwise returns the final result.
    """
    if not os.path.exists(OPENCLAUDE_BIN):
        raise RuntimeError(f"openclaude not found at {OPENCLAUDE_BIN}")

    env = _make_env()
    model = model or env.get("OPENAI_MODEL", "xiaomi/mimo-v2.5-pro")
    # Build args list (excluding cwd — handled by shell cd).
    # --output-format json gives a clean, parseable result object (and reliably
    # runs the agentic tool loop). Keep the prompt as the LAST arg with no
    # variadic flag before it, or openclaude swallows it as a flag value.
    # Force autonomous execution: weaker open models otherwise reply "what would
    # you like me to build?" instead of using their tools. This system prompt
    # makes them act non-interactively regardless of how the per-call prompt is worded.
    autonomy = (
        "You are an autonomous coding agent running non-interactively in a sandbox. "
        "There is NO human to answer questions. NEVER ask what to build or for "
        "clarification — make reasonable assumptions and proceed immediately. Use your "
        "Write/Edit/Bash tools to create real, complete, runnable code (not stubs or "
        "scaffolding). Finish the task fully before stopping."
    )
    stream = bool(app_session_id)
    oc_args = [
        OPENCLAUDE_BIN, "--print",
        "--output-format", ("stream-json" if stream else "json"),
        "--allow-dangerously-skip-permissions", "--dangerously-skip-permissions",
        "--provider", "openai", "--model", model,
    ]
    if stream:
        oc_args += ["--verbose"]  # stream-json needs verbose to emit step events
    if session_id:
        oc_args += ["--session-id", session_id]
    # Autonomy preamble + the task as the final prompt argument.
    full_prompt = autonomy + "\n\n---\n\n" + prompt

    # Pass args as a LIST (no shell) so prompts with parentheses, quotes, etc.
    # can never break shell parsing. openclaude blocks --dangerously-skip-permissions
    # as root, so drop to the astra user via sudo + env for the credentials.
    openai_key = env.get("OPENAI_API_KEY", "")
    openai_base = env.get("OPENAI_BASE_URL", settings.openrouter_base_url)
    openai_model = env.get("OPENAI_MODEL", model)
    if os.getuid() == 0:
        # openclaude runs as `astra`, but the root backend process created the
        # workspace + .git (and rewrites it between passes via _commit_and_push), so
        # those files are root-owned and astra's `git commit` fails with exit 128
        # ('.git' not writable). Hand the whole workspace to astra before each run.
        try:
            subprocess.run(["chown", "-R", "astra:astra", local], capture_output=True, timeout=120)
            subprocess.run(["chmod", "-R", "u+rwX", local], capture_output=True, timeout=120)
        except Exception:
            pass
        cmd = [
            "sudo", "-u", "astra", "env",
            f"OPENAI_API_KEY={openai_key}",
            f"OPENAI_BASE_URL={openai_base}",
            f"OPENAI_MODEL={openai_model}",
            "HOME=/home/astra",
            # Persistent shared npm cache (sudo's env reset drops these unless listed).
            f"npm_config_cache={env.get('npm_config_cache', _NPM_CACHE_DIR)}",
            "npm_config_prefer_offline=true",
            "npm_config_audit=false",
            "npm_config_fund=false",
        ] + oc_args + [full_prompt]
    else:
        cmd = oc_args + [full_prompt]

    if stream:
        return _stream_build_events(cmd, local, timeout, env, founder_id, app_session_id, session_id, agent)

    with _build_semaphore:
        r = subprocess.run(cmd, cwd=local, capture_output=True, text=True, timeout=timeout, env=env)
    if r.returncode not in (0, 1):
        logger.warning("openclaude exited %d: %s", r.returncode, r.stderr[:200])
    out = (r.stdout or "").strip()
    # --output-format json returns a single result object; extract the final
    # text + record build usage for MVP credit billing. Fall back to raw text.
    try:
        obj = json.loads(out)
        if isinstance(obj, dict):
            _record_build_usage(obj, founder_id, session_id)
            return (obj.get("result") or "").strip() or out
    except Exception:
        pass
    return out


_PM_SYSTEM = """You are a product manager driving an MVP build with an AI coding agent.
Your job: read what the agent last said, then write the next message to keep it moving.

Rules:
- If the agent asked a question, answer it clearly and briefly.
- If the agent finished a chunk of work, tell it what to do next based on what's still missing.
- If the agent seems stuck or confused, give clear direction.
- If the MVP is fully complete (all files written and committed), respond with exactly: DONE
- Be direct. No fluff. The agent responds best to clear, specific instructions."""


def _pm_respond(agent_output: str, goal: str, context: str, missing: list[str]) -> str | None:
    """Use planner LLM to generate the orchestrator's next message to openclaude."""
    env = _make_env()
    api_key = env.get("OPENAI_API_KEY", "")
    base_url = env.get("OPENAI_BASE_URL", settings.openrouter_base_url)
    # These review calls run against the OpenRouter endpoint, so use a model valid
    # there (planner_model_name may be an OpenRouter-only slug -> 404).
    model = getattr(settings, "mvp_build_model", "") or "xiaomi/mimo-v2.5-pro"

    from backend.core.llm_client import get_or_client
    client = get_or_client(base_url, api_key)
    missing_str = ", ".join(missing) if missing else "none — MVP may be complete"
    user_msg = (
        f"Goal: {goal}\n"
        f"Context: {context[:800] if context else 'none'}\n"
        f"Still missing files: {missing_str}\n\n"
        f"Agent's last message:\n{agent_output[-2000:]}\n\n"
        f"What do you say next? If MVP is done, respond: DONE"
    )
    from backend.core.llm_cache import cacheable_messages, openrouter_extra_body
    resp = client.chat.completions.create(
        model=model,
        messages=cacheable_messages([
            {"role": "system", "content": _PM_SYSTEM},
            {"role": "user", "content": user_msg},
        ], breakpoints=(0,)),  # cache stable system prompt only
        temperature=0.2,
        timeout=30.0,
        extra_body=openrouter_extra_body(model),
    )
    reply = (resp.choices[0].message.content if getattr(resp, "choices", None) else "") or ""
    reply = re.sub(r"<think>.*?</think>", "", reply, flags=re.DOTALL).strip()
    if reply.strip().upper() == "DONE":
        return None
    return reply


_PLANNER_REVIEW_SYSTEM = """You are a senior engineer doing a cold code review of an AI-generated MVP.
You have the full file list and sampled code from key files (up to 2500 chars each).

IMPORTANT: If a file appears in the file list, assume it exists and is complete UNLESS the sample you were given contains obvious placeholder text (e.g. "TODO", "pass", "raise NotImplementedError") or is clearly empty. Do NOT flag files as missing or incomplete just because they weren't sampled.

Your job: find REAL problems only:
- Files that exist in the file list but whose sample shows they are clearly stubs or empty
- Critical missing files that are NOT in the file list at all
- Broken imports referencing files that don't exist in the file list
- Obvious logic errors visible in the samples

Respond with a JSON object:
{
  "pass": true/false,
  "issues": ["issue1", "issue2"],   // concrete, specific — empty list if pass=true
  "fix_instructions": "tell the coding agent exactly what to fix, or empty string if pass=true"
}"""


def _planner_review(local: str, goal: str, files: list[str]) -> dict:
    """Independent planner LLM review of the built codebase. Returns {pass, issues, fix_instructions}."""
    env = _make_env()
    from backend.core.llm_client import get_or_client
    client = get_or_client(env["OPENAI_BASE_URL"], env["OPENAI_API_KEY"])
    # These review calls run against the OpenRouter endpoint, so use a model valid
    # there (planner_model_name may be an OpenRouter-only slug -> 404).
    model = getattr(settings, "mvp_build_model", "") or "xiaomi/mimo-v2.5-pro"

    # Sample key files — read enough that truncation false-positives don't trigger
    samples = []
    priority = [
        "backend/main.py", "backend/routers/api.py", "backend/routers/auth.py",
        "backend/models.py", "frontend/app/page.tsx", "frontend/app/dashboard/page.tsx",
        "frontend/package.json", "backend/requirements.txt",
    ]
    for rel in priority:
        full = Path(local) / rel
        if full.exists():
            content = full.read_text(errors="replace")
            samples.append(f"=== {rel} ({len(content)} chars) ===\n{content[:2500]}")

    sample_block = "\n\n".join(samples) if samples else "No key files found."
    file_list = "\n".join(files)

    user_msg = (
        f"Goal: {goal}\n\n"
        f"Files in repo ({len(files)} total):\n{file_list}\n\n"
        f"Key file samples:\n{sample_block}"
    )
    try:
        from backend.core.llm_cache import cacheable_messages, openrouter_extra_body
        resp = client.chat.completions.create(
            model=model,
            messages=cacheable_messages([
                {"role": "system", "content": _PLANNER_REVIEW_SYSTEM},
                {"role": "user", "content": user_msg + "\n\nRespond with ONLY a single valid JSON object — no prose, no markdown."},
            ], breakpoints=(0,)),  # cache stable system prompt
            temperature=0.1,
            timeout=60.0,
            extra_body=openrouter_extra_body(model),
        )
        raw = (resp.choices[0].message.content if getattr(resp, "choices", None) else "") or "{}"
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        result = json.loads(raw)
        return {
            "pass": bool(result.get("pass", False)),
            "issues": result.get("issues", []),
            "fix_instructions": result.get("fix_instructions", ""),
        }
    except Exception as e:
        logger.warning("planner_review failed: %s", e)
        return {"pass": True, "issues": [], "fix_instructions": ""}  # don't block on error


_FAKE_PACKAGES = {
    "@radix-ui/react-badge",
    "@radix-ui/react-layout",
    "@radix-ui/react-grid",
    "@radix-ui/react-flex",
    "@radix-ui/react-container",
    "@next/font",  # merged into next/font in Next.js 13+; use next/font/google etc.
}

MVP_REQUIRED = [
    "frontend/package.json",
    "frontend/app/page.tsx",
    "backend/main.py",
    "README.md",
]

# For the technical agent: the product must have auth + a dashboard, not just a
# landing page. MVP_REQUIRED is kept as the web-agent default (landing page only).
# PRODUCT_REQUIRED is used when no explicit required_files is given to the
# technical agent — the completion loop keeps iterating until ALL of these exist,
# which forces the LLM to actually build auth, a dashboard, and the API layer.
PRODUCT_REQUIRED = [
    "frontend/package.json",
    "frontend/app/page.tsx",
    "frontend/app/(auth)/login/page.tsx",
    "frontend/app/dashboard/page.tsx",
    "frontend/app/api/auth/route.ts",
    "frontend/lib/auth.ts",
    "README.md",
]


def _build_doctor(local: str) -> None:
    """Deterministic fixes for the most common LLM build-breakers, applied per-file so
    a bad batch command can't leave them half-fixed (the openclaude heal pass kept
    failing on these). Currently: Supabase's server createClient() is ASYNC — every
    `const x = createClient()` in a file that imports it from a `.../server` module
    must be `await createClient()` (and its enclosing fn made async)."""
    import re as _re
    root = Path(local)
    changed = 0
    for p in list(root.rglob("*.ts")) + list(root.rglob("*.tsx")):
        try:
            if any(part in ("node_modules", ".next", ".git") for part in p.parts):
                continue
            text = p.read_text(errors="replace")
        except Exception:
            continue
        if "createClient" not in text:
            continue
        # Only the SERVER supabase client is async (import from a path containing "server").
        if not _re.search(r"import\s*\{[^}]*\bcreateClient\b[^}]*\}\s*from\s*['\"][^'\"]*server[^'\"]*['\"]", text):
            continue
        new = _re.sub(r"(=\s*)createClient\(\)", r"\1await createClient()", text)
        if new == text:
            continue
        # Make the enclosing default export async if it isn't (server components/pages).
        new = _re.sub(r"export default function (\w+)", r"export default async function \1", new)
        new = _re.sub(r"export async function (GET|POST|PUT|PATCH|DELETE)\b", r"export async function \1", new)
        new = _re.sub(r"export function (GET|POST|PUT|PATCH|DELETE)\b", r"export async function \1", new)
        try:
            p.write_text(new)
            changed += 1
        except Exception:
            pass
    if changed:
        logger.info("build_doctor: awaited async supabase createClient in %d file(s)", changed)


def _ensure_tailwind_setup(repo_dir: str) -> None:
    """Deterministically fix Tailwind so styles actually compile, no matter what the
    LLM scaffolded. The common failure (blank/unstyled site) is Tailwind v4 installed
    against v3-style @tailwind/@apply CSS, a missing postcss config, or content globs
    that purge every utility — all yield raw @tailwind directives and zero styling."""
    import json as _json, re as _re
    root = Path(repo_dir)
    POSTCSS = "module.exports = { plugins: { tailwindcss: {}, autoprefixer: {} } };\n"
    TW_CFG = (
        "/** @type {import('tailwindcss').Config} */\n"
        "module.exports = { content: ["
        "'./app/**/*.{js,ts,jsx,tsx,mdx}','./components/**/*.{js,ts,jsx,tsx,mdx}',"
        "'./pages/**/*.{js,ts,jsx,tsx,mdx}','./src/**/*.{js,ts,jsx,tsx,mdx}'"
        "], theme: { extend: {} }, plugins: [] };\n"
    )
    for pkg in root.rglob("package.json"):
        if "node_modules" in str(pkg):
            continue
        try:
            data = _json.loads(pkg.read_text())
        except Exception:
            continue
        deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        if "next" not in deps and "tailwindcss" not in deps:
            continue
        app_dir = pkg.parent
        try:
            # 1. Pin Tailwind v3 toolchain in devDependencies; purge v4 bits.
            data.get("dependencies", {}).pop("tailwindcss", None)
            data.get("dependencies", {}).pop("@tailwindcss/postcss", None)
            dev = data.setdefault("devDependencies", {})
            dev.pop("@tailwindcss/postcss", None)
            dev["tailwindcss"] = "^3.4.17"
            dev["postcss"] = "^8.4.49"
            dev["autoprefixer"] = "^10.4.20"
            pkg.write_text(_json.dumps(data, indent=2) + "\n")
            # 2. Correct postcss config (drop v4/ESM variants).
            for f in ("postcss.config.mjs", "postcss.config.ts"):
                (app_dir / f).unlink(missing_ok=True)
            (app_dir / "postcss.config.js").write_text(POSTCSS)
            # 3. Ensure a tailwind config with real content globs exists.
            if not (app_dir / "tailwind.config.js").exists() and not (app_dir / "tailwind.config.ts").exists():
                (app_dir / "tailwind.config.js").write_text(TW_CFG)
            # 4. globals.css must use v3 @tailwind directives (not v4 @import).
            for css in app_dir.rglob("globals.css"):
                if "node_modules" in str(css):
                    continue
                try:
                    txt = css.read_text()
                except Exception:
                    continue
                if "@tailwind base" not in txt:
                    txt = _re.sub(r'@import\s+["\']tailwindcss["\'];?\s*', "", txt)
                    css.write_text("@tailwind base;\n@tailwind components;\n@tailwind utilities;\n\n" + txt)
        except Exception as e:
            logger.warning("tailwind setup fixup failed for %s: %s", app_dir, e)


def _sanitize_package_json(repo_dir: str) -> None:
    frontend = Path(repo_dir) / "frontend"

    # Rename next.config.ts → next.config.mjs (not supported in Next.js 14)
    ts_cfg = frontend / "next.config.ts"
    if ts_cfg.exists():
        import re as _re
        mjs_cfg = frontend / "next.config.mjs"
        if not mjs_cfg.exists():
            content = ts_cfg.read_text()
            content = _re.sub(r"^import type.*\n", "", content, flags=_re.MULTILINE)
            content = _re.sub(r":\s*NextConfig\b", "", content)
            content = content.replace("export default config satisfies NextConfig", "export default config")
            mjs_cfg.write_text(content)
        ts_cfg.unlink()
        logger.warning("Sanitize: renamed next.config.ts → next.config.mjs")

    pkg_path = frontend / "package.json"
    if not pkg_path.exists():
        return
    try:
        data = json.loads(pkg_path.read_text())
        changed = False
        # Correct next version — pin to 15.3.3 (latest stable 15.x; 14.x is outdated)
        _NEXT_VERSION = "15.3.3"
        for section in ("dependencies", "devDependencies", "peerDependencies"):
            if section not in data:
                continue
            before = set(data[section])
            # Remove fake packages AND Clerk (causes runtime errors in App Router)
            _BANNED = _FAKE_PACKAGES | {"@clerk/nextjs", "@clerk/clerk-sdk-node", "@clerk/backend"}
            data[section] = {k: v for k, v in data[section].items() if k not in _BANNED}
            removed = before - set(data[section])
            if removed:
                logger.warning("Removed fake/banned npm packages: %s", removed)
                changed = True
            # Fix @next/* packages to match the actual next version
            if "next" in data[section]:
                actual_next = data[section]["next"].lstrip("^~")
                for pkg in list(data[section]):
                    if pkg.startswith("@next/"):
                        data[section][pkg] = actual_next
                        changed = True
                # Upgrade any 14.x → 15.x
                import re as _re
                ver = actual_next
                if _re.match(r"1[0-4]\.", ver):
                    data[section]["next"] = _NEXT_VERSION
                    for pkg in list(data[section]):
                        if pkg.startswith("@next/"):
                            data[section][pkg] = _NEXT_VERSION
                    changed = True
                    logger.warning("Upgraded next + @next/* to %s (was %s)", _NEXT_VERSION, ver)
        if changed:
            pkg_path.write_text(json.dumps(data, indent=2))
    except Exception as e:
        logger.warning("package.json sanitize failed: %s", e)


def _missing_mvp_files(local: str, required: list[str]) -> list[str]:
    # Check disk (works whether or not files are git-staged / pushed).
    base = Path(local)
    return [f for f in required if not (base / f).exists()]


def _file_prompt(rel_path: str, goal: str, context: str, local: str) -> str:
    """Build a targeted single-file prompt with full context so model has no excuse to plan."""
    # Read existing files for cross-file consistency (imports, types)
    siblings = []
    for p in ["frontend/package.json", "frontend/tsconfig.json", "backend/main.py", "backend/models.py"]:
        fp = Path(local) / p
        if fp.exists() and p != rel_path:
            try:
                siblings.append(f"--- {p} ---\n{fp.read_text()[:600]}")
            except Exception:
                pass
    sibling_block = ("\n\nEXISTING FILES (for consistency):\n" + "\n".join(siblings)) if siblings else ""
    ctx_block = f"\n\nCONTEXT:\n{context[:800]}" if context else ""

    # File-specific guidance
    hints = {
        "frontend/package.json": (
            "Use ONLY these real packages with these EXACT versions for Tailwind so the "
            "CSS actually compiles (Tailwind v4 has a different setup and breaks @tailwind/@apply): "
            "\"tailwindcss\": \"^3.4.17\", \"postcss\": \"^8.4.49\", \"autoprefixer\": \"^10.4.20\" "
            "(all in devDependencies). Plus: next@15.3.3, react@19, react-dom@19, typescript, "
            "@tailwindcss/forms, clsx, lucide-react, next-auth@beta, @supabase/supabase-js, @supabase/ssr, "
            "framer-motion, zod, react-hook-form. "
            "NEVER use tailwindcss v4 / @tailwindcss/postcss. NEVER @clerk/*. NEVER @next/font (use next/font/google). NEVER @radix-ui/react-badge."
        ),
        # These three MUST be correct or Tailwind emits raw @tailwind/@apply (no styles).
        "frontend/postcss.config.js": (
            "REQUIRED for Tailwind to compile. Exactly:\n"
            "module.exports = { plugins: { tailwindcss: {}, autoprefixer: {} } };"
        ),
        "frontend/postcss.config.mjs": (
            "REQUIRED for Tailwind to compile. Exactly:\n"
            "export default { plugins: { tailwindcss: {}, autoprefixer: {} } };"
        ),
        "frontend/tailwind.config.ts": (
            "Tailwind v3 config. The `content` globs MUST cover every dir with classes or all utilities get purged "
            "(blank styling). Use: content: ['./app/**/*.{js,ts,jsx,tsx,mdx}','./components/**/*.{js,ts,jsx,tsx,mdx}',"
            "'./src/**/*.{js,ts,jsx,tsx,mdx}']. Define any custom colors as nested objects with real shades "
            "(e.g. sky: {500:'#0ea5e9'}) — NEVER use a bare 'DEFAULT'-only color and reference it as `sky-DEFAULT`."
        ),
        "frontend/tailwind.config.js": (
            "Same as tailwind.config.ts: content globs must cover ./app, ./components, ./src; custom colors need real shades."
        ),
        "frontend/app/globals.css": (
            "Tailwind v3 entry. MUST start with exactly these three lines:\n"
            "@tailwind base;\n@tailwind components;\n@tailwind utilities;\n"
            "Then any @layer/@apply rules. Do NOT use Tailwind v4 syntax (@import 'tailwindcss')."
        ),
        "frontend/next.config.js": "Use .js extension ONLY. Never next.config.ts or .mjs.",
        "frontend/middleware.ts": "Use next-auth (NOT Clerk). Protect /dashboard/* routes with NextAuth middleware.",
        "backend/requirements.txt": "Include: fastapi, uvicorn[standard], pydantic, python-dotenv, sqlalchemy, psycopg2-binary, python-jose[cryptography], passlib[bcrypt], httpx",
    }
    hint = hints.get(rel_path, "")
    hint_block = f"\n\nFILE HINTS: {hint}" if hint else ""

    return (
        f"You are a senior full-stack engineer building an MVP for: {goal}{ctx_block}{sibling_block}{hint_block}\n\n"
        f"Task: write the file `{rel_path}` with COMPLETE, production-ready code.\n"
        f"Rules:\n"
        f"- NO TODOs, NO placeholders, NO '// implement later', NO empty functions\n"
        f"- Every class, function, and route must have a real, working implementation\n"
        f"- The file must be immediately runnable/importable with no changes\n\n"
        f"IMPORTANT: Use your Write tool RIGHT NOW to create `{rel_path}`. "
        f"Do not explain. Do not plan. Write the complete file and say DONE."
    )


_BUILD_PLAN_SYSTEM = (
    "You are a senior product designer + engineer. From the product goal AND the RESEARCH "
    "provided (market, ICP, pain points, competitors), produce a COMPLETE, concrete plan for "
    "how the product/site will LOOK, how it WILL WORK, and WHAT IT DOES — exhaustive enough "
    "that a coding agent implements it end-to-end with no further decisions. Ground every "
    "choice in the research: the design, features, and copy must fit the target user and the "
    "pain you're solving. Be specific; real features, not placeholders.\n\n"
    "Cover, in order:\n"
    "1. PRODUCT: one paragraph — what it does, the core value, the primary user, and the "
    "specific pain it solves (cite the research).\n"
    "2. WHO IT'S FOR: the ICP from research and how that shapes the product and tone.\n"
    "3. LOOK & FEEL: the visual system — overall vibe/positioning, color palette, typography, "
    "spacing/layout style, key components, iconography, imagery, and interaction/motion. Then, "
    "for each main screen, describe its look and layout (what the user sees, top to bottom).\n"
    "4. USER FLOWS: the key end-to-end flows (sign up → onboard → core action → result), with states.\n"
    "5. PAGES/ROUTES: every route with its purpose, layout, and main UI elements.\n"
    "6. CORE FEATURES: each real feature — what it does and exactly how it works.\n"
    "7. DATA MODEL: entities, fields, relationships.\n"
    "8. AUTH: must WORK out of the box. Default to email+password (or magic-link) via "
    "Supabase Auth or NextAuth Credentials — these function with no external OAuth setup. "
    "Do NOT plan a Google/GitHub/social sign-in button unless real OAuth credentials are "
    "provisioned: a dead social button is worse than none. NEVER Clerk.\n"
    "9. FILES: the concrete file tree to create/extend, each with a one-line purpose.\n"
    "10. ACCEPTANCE: a checklist of what 'done and working' means.\n\n"
    "CRITICAL — DO NOT RESTATE THE RESEARCH. The research is INPUT for your decisions, not "
    "content to repeat. Never summarize or copy the market brief / ICP doc. Every line you write "
    "must be a concrete BUILD decision: a screen, a component, a layout, a feature, an interaction, "
    "a data field, a file. If a sentence could appear in a market report, delete it. Translate "
    "research INTO product: e.g. 'ICP is time-poor ops managers' → 'dashboard opens on a single "
    "Today view with one primary CTA; no nested menus'.\n\n"
    "HONESTY: never plan fake testimonials, customer quotes/logos, user counts, ratings, revenue, "
    "or press mentions. A new product has no customers yet — plan honest copy and real features, "
    "with neutral placeholders (no invented specifics) where real data doesn't exist yet.\n\n"
    "Plan the actual APP (auth, dashboard, the core feature set) plus how it looks, not just a "
    "landing page. Output clear markdown — a buildable spec, not a report."
)


def _build_plan_research(founder_id: str) -> str:
    """Pull the founder's research + design vault notes so the plan is grounded in the
    actual market/ICP findings (not just the one-line goal). Best-effort, capped."""
    if not founder_id:
        return ""
    try:
        from backend.tools.obsidian_logger import format_vault_context
    except Exception:
        return ""
    parts: list[str] = []
    for agent in ("research", "research_market", "design"):
        try:
            txt = format_vault_context(agent, max_notes=2, founder_id=founder_id)
            if txt and txt.strip():
                parts.append(txt.strip())
        except Exception:
            continue
    return ("\n\n".join(parts))[:7000]


def _generate_build_plan(goal: str, context: str = "", kind: str = "app", founder_id: str = "") -> dict:
    """Produce a complete build spec with MiniMax-M3 before the build runs, so
    openclaude implements a real product instead of improvising from a one-liner.
    Grounds the plan (look/function/purpose) in the founder's research notes.
    Best-effort — returns {"plan": "", "files": []} on any failure (build still runs)."""
    env = _make_env()
    model = getattr(settings, "build_plan_model", "") or "minimax/minimax-m3"
    research = _build_plan_research(founder_id)
    try:
        from backend.core.llm_client import get_or_client
        client = get_or_client(env["OPENAI_BASE_URL"], env["OPENAI_API_KEY"])
        user_msg = (
            f"PRODUCT GOAL:\n{goal}\n\n"
            + (f"RESEARCH (market / ICP / pain / competitors — base the plan on this):\n{research}\n\n" if research else "")
            + (f"DESIGN & PRODUCT CONTEXT:\n{context[:6000]}\n\n" if context else "")
            + f"Produce the complete build plan for the {kind} — how it looks, how it works, and "
              "what it does, grounded in the research above. End with a line "
              "'FILES:' followed by a JSON array of the key files to create/extend, "
              'e.g. FILES: ["app/dashboard/page.tsx", "app/api/auth/[...nextauth]/route.ts"].'
        )
        def _ask(max_toks: int) -> str:
            from backend.core.llm_cache import cacheable_messages, openrouter_extra_body
            resp = client.chat.completions.create(
                model=model,
                messages=cacheable_messages([
                    {"role": "system", "content": _BUILD_PLAN_SYSTEM},
                    {"role": "user", "content": user_msg},
                ], breakpoints=(0,)),
                temperature=0.3,
                timeout=180.0,
                max_tokens=max_toks,
                # minimax-m3 is a reasoning model — disable reasoning so the token
                # budget goes to the actual plan, not <think> that gets stripped to "".
                extra_body=openrouter_extra_body(model, {"reasoning": {"effort": "none"}}),
            )
            raw = (resp.choices[0].message.content if getattr(resp, "choices", None) else "") or ""
            # Drop complete think blocks; if that empties it, drop only the trailing
            # unclosed think prefix so a truncated reasoning dump still yields the plan.
            stripped = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
            if not stripped and raw:
                stripped = re.sub(r"^.*?</think>", "", raw, flags=re.DOTALL).strip() or raw.strip()
            return stripped

        plan = _ask(8000)
        # One quick retry only if it came back essentially empty (avoid doubling
        # latency on the technical agent, which has a hard 3600s budget).
        if len(plan) < 200:
            plan = _ask(8000) or plan
        files: list[str] = []
        m = re.search(r"FILES:\s*(\[.*?\])", plan, re.DOTALL)
        if m:
            try:
                parsed = json.loads(m.group(1))
                files = [str(f).strip() for f in parsed if isinstance(f, str) and f.strip()][:40]
            except Exception:
                files = []
        if not files:
            # Model wrote the file plan as markdown (not the FILES: JSON line) — scan
            # for real source paths so the completion loop still targets them.
            seen: set[str] = set()
            for raw in re.findall(r"[\w@./\[\]-]+\.(?:tsx?|jsx?|css|json|prisma|sql|mjs)", plan):
                p = raw.strip().lstrip("./")
                if p and "/" in p and p not in seen and not p.startswith("node_modules"):
                    seen.add(p)
            files = list(seen)[:40]
        logger.info("build plan generated (%d chars, %d files) via %s", len(plan), len(files), model)
        return {"plan": plan, "files": files, "model": model}
    except Exception as e:
        logger.warning("build plan generation failed (%s) — building from goal only: %s", model, e)
        return {"plan": "", "files": [], "model": model}


def run_mvp_loop(
    repo_url: str = "",
    goal: str = "",
    session_id: str = "default",
    context: str = "",
    required_files: list[str] = None,
    max_rounds: int = None,  # kept for API compat, ignored
    founder_id: str = "",
    agent: str = "technical",
) -> dict:
    """
    Build MVP by calling openclaude once per missing file (no session-id — fresh context each call).
    Avoids session state pollution that caused the PM loop to spin forever.
    """
    if required_files is None:
        # Technical agent builds the product (auth + dashboard + core features).
        # Web agent builds only the landing page. Different default file sets.
        required_files = PRODUCT_REQUIRED if agent == "technical" else MVP_REQUIRED
    elif isinstance(required_files, str):
        # LLM sometimes passes the list serialized as a JSON/Python string — parse it.
        try:
            import ast as _ast
            parsed = _ast.literal_eval(required_files)
            required_files = list(parsed) if isinstance(parsed, (list, tuple)) else MVP_REQUIRED
        except Exception:
            try:
                import json as _json
                parsed = _json.loads(required_files)
                required_files = list(parsed) if isinstance(parsed, list) else MVP_REQUIRED
            except Exception:
                required_files = MVP_REQUIRED

    if not goal:
        return {"error": "goal is required — describe what to build, e.g. \"Next.js SaaS app with auth and dashboard\""}

    try:
        # Pin the company's product repo: reuse the SAME repo across every run so
        # operating goals EXTEND the product in place (→ incremental build) instead
        # of cloning a brand-new repo under a freshly-invented company name each
        # time. The agent may still pass a new repo_url; if the company already has
        # a pinned repo we override to it.
        _company_id = founder_id or ""
        try:
            from backend.core.session_store import get_session_meta as _gsm
            if founder_id:
                _company_id = str((_gsm(session_id) or {}).get("company_id") or founder_id)
        except Exception:
            pass
        if founder_id and _company_id:
            try:
                from backend.missions.company_goal import get_company_repo
                _pinned = get_company_repo(founder_id, _company_id)
                if _pinned and _pinned != repo_url:
                    logger.info("run_mvp_loop: reusing pinned company repo %s (agent passed %r)", _pinned, repo_url)
                    repo_url = _pinned
            except Exception:
                pass

        # GitHub-optional: clone if a repo+token exist, else build in a local
        # workspace and stream files to the preview (no GitHub required).
        local, is_github = _get_workspace(repo_url, session_id, founder_id=founder_id, company_id=_company_id)

        # First build that produced a real GitHub repo → pin it for all future runs.
        if founder_id and _company_id and is_github and repo_url:
            try:
                from backend.missions.company_goal import set_company_repo
                set_company_repo(founder_id, _company_id, repo_url)
            except Exception:
                pass

        oc_session_id = str(uuid.uuid4())
        Path(local, ".oc_session_id").write_text(oc_session_id)
        commits = []

        def _phase(text: str, **extra) -> None:
            """Publish a build-progress line so the technical preview shows what's
            happening between openclaude steps (passes, rounds, commits)."""
            try:
                from backend.core.events import publish_sync
                publish_sync(session_id, {"type": "agent_build", "agent": agent,
                                          "kind": "phase", "text": text, **extra})
            except Exception:
                pass

        try:
            from backend.core.events import publish_sync
            publish_sync(session_id, {"type": "agent_build", "agent": agent,
                                      "kind": "build_start", "goal": goal[:160], "github": is_github})
        except Exception:
            pass
        _phase(f"Workspace ready ({'GitHub' if is_github else 'local'}) — {len(required_files)} target files")

        logger.info("MVP build start (github=%s) for %s", is_github, repo_url or "(local)")
        if is_github:
            _pull(local)

        # Incremental mode: this agent already built the product in this workspace
        # once (a .built_<agent> marker exists). Operating/follow-up goals must NOT
        # rebuild the whole site — apply ONLY this goal's change and preserve the
        # existing pages, design system, and prior work. First build = full build.
        built_marker = Path(local) / f".built_{agent}"
        incremental = built_marker.exists()
        if incremental:
            _phase("Incremental update — changing only what this goal needs (existing product preserved)")

        # Plan the product with MiniMax-M3 BEFORE building (the MVP planner), so
        # openclaude implements a real app from a concrete spec instead of improvising.
        # Only for the product build (technical) — the web/landing agent skips it (no
        # separate website planner). Skipped on incremental (no full re-plan).
        plan_info = {"plan": "", "files": [], "model": ""}
        if agent != "web" and not incremental:
            _phase("Planning the product (MiniMax-M3)…")
            plan_info = _generate_build_plan(goal, context, kind="app", founder_id=founder_id)
        build_plan = plan_info.get("plan") or ""
        if build_plan:
            plan_title = "Product build plan"
            try:
                from backend.core.events import publish_sync
                publish_sync(session_id, {"type": "agent_build", "agent": agent, "kind": "plan",
                                          "text": f"{plan_title} ready ({len(build_plan)} chars) — {plan_info.get('model','')}"})
                # Surface the full plan as a viewable deliverable in the session UI.
                publish_sync(session_id, {"type": "stack_artifact", "artifact": {
                    "key": f"build_plan_{agent}",
                    "title": plan_title,
                    "owner_agent": agent,
                    "status": "ready",
                    "description": f"Complete build spec generated by {plan_info.get('model','')} before the build.",
                    "preview": build_plan[:400],
                    "content": build_plan,
                }})
            except Exception:
                pass
            # Merge the plan's concrete file list into the build targets so the
            # completion loop actually drives the product files into existence.
            planned = [f for f in (plan_info.get("files") or []) if isinstance(f, str)]
            if planned:
                required_files = list(dict.fromkeys([*required_files, *planned]))
            try:
                (Path(local) / "BUILD_PLAN.md").write_text(build_plan)
            except Exception:
                pass

        # Pass 1: ONE autonomous build of the whole MVP in a persistent openclaude
        # session (it loops internally — writes every file, runs/tests, fixes),
        # then iterate until all required files exist. Not one-shot-per-file.
        build_sid = str(uuid.uuid4())
        manifest = "\n".join(f"- {f}" for f in required_files)
        build_prompt = (
            f"Build a COMPLETE, working product for this goal:\n{goal}\n\n"
            + (f"FOLLOW THIS BUILD PLAN EXACTLY — implement every page, feature, route, and data "
               f"model in it. This is the spec, not a suggestion:\n\n{build_plan}\n\n" if build_plan else "")
            + (f"Context:\n{context}\n\n" if context else "")
            + "You MUST create ALL of these files — they are REQUIRED and the build is considered "
              "incomplete until every one of them exists with real, working code:\n"
            + manifest + "\n\n"
            + "CRITICAL: do NOT stop after creating a landing page. The required files above include "
              "auth pages, a dashboard, and API routes — you must build ALL of them. A landing-page-only "
              "build that skips auth and dashboard is a FAILED build.\n"
            + "Rules: no stubs, no TODOs, no placeholders — every function, route, and component fully "
              "implemented and runnable. Build the ENTIRE product (auth + dashboard + the core features "
              "from the plan), file by file, using your Write/Edit/Bash tools. Keep working until the whole "
              "product is complete and matches the plan; do not stop after one file or build only a landing page.\n"
            + "WORKING AUTH (non-negotiable): auth must actually work. Use email+password (or magic-link) "
              "via Supabase Auth or NextAuth Credentials — these function with only the Supabase anon key / a "
              "NEXTAUTH_SECRET, no external OAuth setup. Do NOT add a Google/GitHub/social sign-in button: it "
              "needs OAuth credentials that don't exist, so it's a DEAD button. A working email/password form "
              "beats a broken social button.\n"
            + "DEMO-ACCESSIBLE PREVIEW (non-negotiable): the preview deploys with PLACEHOLDER credentials and NO "
              "real database, so a normal login will dead-end and the whole product looks like 'just a landing "
              "page'. The app MUST be reachable without real backend creds. Do ALL of: (1) seed a demo account "
              "(email 'demo@demo.app', password 'demo123') that signs in against an in-memory/JSON/SQLite-file "
              "fallback when env DB vars are placeholders; (2) put a prominent 'View live demo' / 'Try it' button "
              "on the landing that logs into that demo session and lands on the dashboard in ONE click; (3) make "
              "the authed pages render with realistic seeded/mock data (no blank states) so the product is fully "
              "explorable in the preview. The dashboard must be reachable from the landing in one click — if a "
              "visitor cannot see the actual product, the build has failed.\n"
            + "NO DEAD UI: every button, link, and form must do something real — wired to a route, action, or "
              "handler. No links to pages that don't exist, no onClick-less buttons, no forms that don't submit. "
              "If a feature isn't built, don't put a control for it in the UI.\n"
            + ("DESIGN PRESERVATION (non-negotiable): a landing page already exists in this repo with an "
               "established visual design. Do NOT change the existing styling. Specifically: do NOT rewrite or "
               "restyle globals.css theme/color CSS variables, the tailwind.config theme (colors, fonts, spacing), "
               "the fonts wired in layout.tsx, or any existing landing-page component. REUSE those exact design "
               "tokens (the same colors, fonts, spacing, component classes) for every NEW page (auth, dashboard, "
               "features) so the whole product looks like one cohesive site. Only ADD files/sections; never "
               "overwrite the landing's look.\n" if agent != "web" else "")
            + ("HONESTY: do NOT fabricate testimonials, customer quotes/names/photos, company logos, user "
              "counts, ratings, revenue, or press mentions — a new product has no customers yet. Use honest "
              "copy and neutral placeholders (no invented specifics) instead of fake social proof.\n"
              "VERIFY with `npm run build` / `npx tsc --noEmit` ONLY — do NOT run `next dev`/`next start` and "
              "curl-test routes: the sandbox blocks `sleep`, has no `lsof`, and rate limiters trip your own "
              "requests. A clean build is the bar; the live preview is started separately.")
        )
        # Incremental: replace the holistic build prompt with a targeted change
        # that preserves the existing site. Keeps the shared verify/deploy tail.
        if incremental:
            build_prompt = (
                "The product ALREADY EXISTS in this repo with an established design and working "
                f"features. Make ONLY the change this goal requires — nothing else:\n{goal}\n\n"
                + (f"Context:\n{context}\n\n" if context else "")
                + "STRICT: do NOT rebuild, restyle, or rewrite existing pages/components. Do NOT touch "
                  "globals.css theme, the tailwind config, fonts, or the landing/dashboard unless this "
                  "goal is specifically about them. Add or edit only the minimum files needed for this "
                  "one change, reusing the existing design system. No dead UI — wire every control to a "
                  "real route/action. Verify with `npm run build` / `npx tsc --noEmit` only."
            )
        logger.info("Pass 1: %s build (%d target files, plan=%s)",
                    "incremental" if incremental else "holistic MVP", len(required_files), bool(build_plan))
        _phase(("Applying incremental change" if incremental else "Pass 1/4 — building the full product")
               + ("" if incremental else (" from plan" if build_plan else "")))
        _run_claude(local, build_prompt, session_id=build_sid, timeout=1800,
                    founder_id=founder_id, app_session_id=session_id, agent=agent)

        # Completion loop: keep going until required files exist. Technical agent gets
        # 2 rounds by default (landing page pass rarely creates auth+dashboard on the
        # first try); web/other stay at 1. Skipped on incremental (change is intentionally
        # small, not the full MVP manifest).
        _default_rounds = 2 if agent == "technical" else 1
        completion_rounds = 0 if incremental else max(0, int(getattr(settings, "mvp_max_completion_rounds", _default_rounds) or _default_rounds))
        for _round in range(completion_rounds):
            _stage_all(local)
            missing = _missing_mvp_files(local, required_files)
            if not missing:
                break
            logger.info("Completion round %d: %d still missing", _round + 1, len(missing))
            _phase(f"Completion round {_round + 1} — {len(missing)} file(s) still missing: {', '.join(missing[:5])}")
            fix_prompt = (
                "These required files are still missing or incomplete: " + ", ".join(missing)
                + ". Create and fully implement them NOW with your Write tool — real, complete code. "
                + f"Project: {goal}."
            )
            _run_claude(local, fix_prompt, session_id=build_sid, timeout=900,
                        founder_id=founder_id, app_session_id=session_id, agent=agent)

        # Placeholder env so the verification build + deploy work without real keys.
        try:
            ph = _placeholder_env(local)
            if ph:
                (Path(local) / ".env.local").write_text("\n".join(f"{k}={v}" for k, v in ph.items()) + "\n")
        except Exception:
            pass

        _sanitize_package_json(local)
        if is_github:
            sha = _commit_and_push(local, f"feat: mvp build — {goal[:50]}")
            if sha:
                commits.append(sha)
        else:
            _stage_all(local)

        # Deterministic fixes/checks come before any recovery LLM. If the app
        # already builds, skip the costly self-test/build-heal/review passes by default.
        _ensure_tailwind_setup(local)
        _build_doctor(local)
        _sanitize_package_json(local)
        # A web/technical build is expected to produce a Node app — if it didn't, that's
        # a real failure (no package.json), not a pass.
        _expects_node = any(str(f).endswith(("package.json", ".tsx", ".ts", ".jsx")) for f in (required_files or []))
        _phase("Pass 2/4 — deterministic build check")
        build_res, build_output = _npm_build_passes(local)
        if build_res is None:  # no Node app found
            build_ok = not _expects_node
            if _expects_node:
                build_output = "No package.json / Node app was produced — the build wrote no app."
        else:
            build_ok = bool(build_res)
        _phase("Build check: passed" if build_ok else "Build check: failed — starting recovery",
               build_output=(build_output or "")[-1200:])

        max_rounds = max(1, int(getattr(settings, "mvp_max_build_rounds", 3) or 3))

        # Compiler-as-critic recovery loop: feed the REAL `npm run build` errors to
        # openclaude, re-apply deterministic fixes, then RE-VERIFY with the compiler.
        # Repeat until the build genuinely passes or we hit the round cap — so we never
        # ship a build that only "passed" because the model said so. One persistent
        # recovery session so each round remembers what the last one already tried.
        recovery_sid = str(uuid.uuid4())
        round_i = 0
        while (not build_ok) and round_i < max_rounds:
            round_i += 1
            _phase(f"Build recovery {round_i}/{max_rounds} — fixing real build errors")
            fix_prompt = (
                "The production build FAILS. Fix EVERY error below so `npm run build` passes "
                "clean. Fix the actual cause (TypeScript types, bad imports, async Supabase "
                "`createClient` → `await createClient()`, missing files, invented npm packages, "
                "Next.js 15 App Router APIs). Do NOT start a dev server or curl-test. If you "
                "tried a fix last round and the same error persists, try a different approach.\n\n"
                f"=== npm run build output ===\n{(build_output or '')[-4500:]}"
            )
            _run_claude(local, fix_prompt, session_id=recovery_sid, timeout=900,
                        founder_id=founder_id, app_session_id=session_id, agent=agent)
            # Re-assert deterministic fixes so the LLM can't undo the known-good toolchain.
            _sanitize_package_json(local)
            _ensure_tailwind_setup(local)
            _build_doctor(local)
            _res, build_output = _npm_build_passes(local)
            build_ok = (not _expects_node) if _res is None else bool(_res)
            _phase("Build now PASSES ✓" if build_ok else f"Build still failing after round {round_i}",
                   build_output=(build_output or "")[-1200:])
            if is_github:
                sha_r = _commit_and_push(local, f"fix: build recovery {round_i} — {goal[:40]}")
                if sha_r:
                    commits.append(sha_r)
            else:
                _stage_all(local)

        # Final guard — re-assert the Tailwind toolchain in case a later pass touched it.
        _ensure_tailwind_setup(local)
        _stage_all(local)
        all_files = _list_built_files(local)
        _build_status = "passed" if build_ok else ("failed" if _expects_node else "skipped")
        _phase(f"Build {_build_status} — {len(all_files)} files written", files_total=len(all_files))
        # Write the incremental marker only on a real success — prevents future goals
        # from running in incremental mode on a never-built (empty) repo.
        if build_ok and not incremental:
            try:
                built_marker.write_text(build_sid)
            except Exception:
                pass

        # Auto-deploy to Vercel so there's a live preview URL (uses placeholder env
        # vars so it builds without real keys). Only when pushed to GitHub.
        deploy_url = None
        from backend.tools.vercel_deploy import _founder_has_vercel
        if is_github and repo_url and _founder_has_vercel(founder_id):
            try:
                from backend.core.events import publish_sync
                publish_sync(session_id, {"type": "agent_build", "agent": agent, "kind": "deploy_start"})
            except Exception:
                pass
            try:
                from backend.tools.vercel_deploy import vercel_deploy_from_github
                dep = vercel_deploy_from_github(
                    repo_url,
                    project_name=Path(local).name[:60],
                    env_vars=_placeholder_env(local),
                    root_directory=_vercel_root_dir(local),
                    founder_id=founder_id,
                )
                deploy_url = dep.get("deploy_url") or dep.get("url") or dep.get("deployment_url")
                if deploy_url:
                    try:
                        from backend.core.events import publish_sync
                        publish_sync(session_id, {"type": "agent_build", "agent": agent, "kind": "deploy", "url": deploy_url})
                    except Exception:
                        pass
            except Exception as e:
                logger.warning("auto vercel deploy failed: %s", e)

        # Fallback: if Vercel didn't produce a URL (error, no token, or local-only
        # build), run the MVP on the server itself on a free port for a live preview.
        local_preview = False
        if not deploy_url:
            try:
                from backend.tools.local_preview import start_local_preview
                # Key preview by root session so child builds replace the same slot
                root_sid = _root_session_id(session_id)
                url = start_local_preview(local, root_sid, company_name=Path(local).name)
                if url:
                    deploy_url = url
                    local_preview = True
                    try:
                        from backend.core.events import publish_sync
                        publish_sync(session_id, {"type": "agent_build", "agent": agent,
                                                  "kind": "deploy", "url": url, "local": True})
                    except Exception:
                        pass
            except Exception as e:
                logger.warning("local preview failed: %s", e)

        return {
            # success reflects the compiler when a Node app was expected, so callers
            # don't ship a broken build as a success.
            "success": bool(build_ok) if _expects_node else True,
            "build_passes": bool(build_ok),
            "repo_url": repo_url,
            "github_url": f"{repo_url}/tree/main" if is_github else "",
            "deploy_url": deploy_url,
            "local_preview": local_preview,
            "local_only": not is_github,
            "commits": commits,
            "files_in_repo": len(all_files),
            "files_preview": all_files[:30],
            "missing": _missing_mvp_files(local, required_files),
        }

    except Exception as e:
        logger.error("run_mvp_loop failed: %s", e)
        return {"error": str(e)}


def run_claude_in_repo(
    repo_url: str = "",
    task: str = "",
    session_id: str = "default",
    context: str = "",
    founder_id: str = "",
) -> dict:
    """
    Single Claude Code pass inside a repo. Commits + pushes whatever it writes.
    For full MVP building, prefer run_mvp_loop instead.
    """
    if not settings.github_token:
        return {"error": "GITHUB_TOKEN not set"}
    if not repo_url or not repo_url.startswith("https://github.com/"):
        return {"error": f"run_claude_in_repo requires a valid GitHub repo URL; got: {repo_url!r}. "
                         "If no repo exists yet, call github_create_repo first, then run_mvp_loop."}

    ctx_section = f"\n\nCONTEXT:\n{context}\n" if context else ""
    prompt = (
        f"Write REAL working code files immediately using the Write tool. No planning.\n\n"
        f"TASK: {task}{ctx_section}\n\n"
        f"After writing files, run: bash -c \"git add -A && git commit -m 'feat: {task[:60]}'\""
    )

    try:
        local = _ensure_clone(repo_url, session_id)
        _pull(local)
        # Resume the session from the MVP build (stored in .oc_session_id)
        sid_file = Path(local) / ".oc_session_id"
        oc_session_id = sid_file.read_text().strip() if sid_file.exists() else str(uuid.uuid4())
        _run_claude(local, prompt, session_id=oc_session_id, timeout=3600, founder_id=founder_id)
        sha = _commit_and_push(local, f"feat: {task[:72]}")
        files = _staged_files(local)
        return {
            "success": True,
            "repo_url": repo_url,
            "commit": sha,
            "files_in_repo": len(files),
            "github_url": f"{repo_url}/tree/main",
        }
    except subprocess.TimeoutExpired:
        return {"error": "Timed out (360s)"}
    except Exception as e:
        logger.error("run_claude_in_repo failed: %s", e)
        return {"error": str(e)}


def write_files_to_repo(
    repo_url: str = "",
    files: dict | None = None,
    commit_message: str = "feat: add files",
    session_id: str = "default",
) -> dict:
    """
    Write specific files directly to a GitHub repo and push.
    files: {"relative/path.ext": "file content string"}
    """
    if not repo_url:
        return {"error": "repo_url is required — pass the GitHub repo URL, e.g. https://github.com/org/repo"}
    if not files:
        return {"error": "files is required — pass a dict of {\"path\": \"content\"} to write"}
    if not settings.github_token:
        return {"error": "GITHUB_TOKEN not set"}
    try:
        local = _ensure_clone(repo_url, session_id)
        _pull(local)

        written = []
        for rel_path, content in files.items():
            full = Path(local) / rel_path
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content if isinstance(content, str) else str(content), encoding="utf-8")
            written.append(rel_path)

        sha = _commit_and_push(local, commit_message)
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
