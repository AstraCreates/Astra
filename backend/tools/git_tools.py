"""
Git tools for the technical agent — write files, commit, push to a GitHub repo.
run_mvp_loop is the primary entry point: iterates Claude Code until MVP is complete.

Workspaces live at ~/Documents/astra-workspaces/<session_id>/<repo_name>/
free-claude-code proxies the claude CLI to DeepInfra so no Anthropic key needed.
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

import openai

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
    # openclaude first — it supports --provider openai for DeepInfra
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




def _clone_url(repo_url: str) -> str:
    token = settings.github_token
    if token and "github.com" in repo_url:
        return repo_url.replace("https://", f"https://{token}@")
    return repo_url


def _sh(cmd: list, cwd: str = None, timeout: int = 60) -> str:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:2])} failed: {r.stderr[:300]}")
    return r.stdout.strip()


def _workspace_dir(session_id: str, repo_url: str) -> Path:
    """Deterministic persistent workspace path for a session + repo."""
    repo_name = repo_url.rstrip("/").split("/")[-1]
    return WORKSPACE_ROOT / session_id / repo_name


def _ensure_clone(repo_url: str, session_id: str = "default") -> str:
    """Clone repo into persistent workspace, return local path."""
    key = f"{session_id}:{repo_url}"
    if key in _clones and os.path.isdir(_clones[key]):
        return _clones[key]
    workspace = _workspace_dir(session_id, repo_url)
    workspace.parent.mkdir(parents=True, exist_ok=True)
    if workspace.exists():
        # Already cloned in a prior run — just pull
        try:
            _sh(["git", "pull", "--rebase"], cwd=str(workspace), timeout=30)
        except Exception:
            pass
    else:
        _sh(["git", "clone", "--depth", "1", _clone_url(repo_url), str(workspace)])
        _sh(["git", "config", "user.email", "astra-agent@astra.ai"], cwd=str(workspace))
        _sh(["git", "config", "user.name", "Astra Agent"], cwd=str(workspace))
    # Ensure astra user (uid 1000) can write files in the workspace when running as root
    if os.getuid() == 0:
        subprocess.run(["chmod", "-R", "777", str(workspace)], capture_output=True)
    _clones[key] = str(workspace)
    return str(workspace)


def _get_workspace(repo_url: str, session_id: str) -> tuple[str, bool]:
    """Return (local_path, is_github). Clones from GitHub when a repo + token are
    available, otherwise builds in a fresh local git workspace so MVPs can be
    built and previewed with NO GitHub required."""
    if repo_url and settings.github_token:
        try:
            return _ensure_clone(repo_url, session_id), True
        except Exception as e:
            # Repo creation blocked/failed → don't let the build die; build locally.
            logger.warning("clone failed (%s) — building in a local workspace instead", str(e)[:160])
    ws = WORKSPACE_ROOT / session_id / "mvp"
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


def _stage_all(local: str) -> None:
    """Stage all files (no commit) so disk contents are tracked in local mode."""
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
    push = subprocess.run(["git", "push"], cwd=local, capture_output=True, text=True, timeout=60)
    if push.returncode != 0:
        raise RuntimeError(f"git push failed: {push.stderr[:200]}")
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=local, capture_output=True, text=True).stdout.strip()


def _make_env() -> dict:
    # openclaude talks to the DeepInfra endpoint below, so it needs a DeepInfra
    # key. Prefer the DeepInfra-specific keys; planner_model_api_key is often an
    # OpenRouter key (sk-or-...) which would 401 against DeepInfra and make every
    # build spin until timeout. Only fall back to it if it's NOT an OpenRouter key.
    planner_key = getattr(settings, "planner_model_api_key", "") or ""
    deepinfra_key = (
        getattr(settings, "deepinfra_api_key", "")
        or getattr(settings, "agent_model_api_key", "")
        or (planner_key if not planner_key.startswith("sk-or-") else "")
    )
    env = os.environ.copy()
    env["OPENAI_BASE_URL"] = "https://api.deepinfra.com/v1/openai"
    env["OPENAI_API_KEY"] = deepinfra_key
    env["OPENAI_MODEL"] = getattr(settings, "mvp_build_model", "") or "moonshotai/Kimi-K2.5"
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
        total_t = sum(int(usage.get(k, 0) or 0) for k in (
            "input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
        turns = int(result_obj.get("num_turns", 0) or 0)
        if total_t <= 0:
            return
        from backend.credits.gold_price import tokens_to_credits
        from backend.credits.store import deduct_credits
        mult = float(getattr(settings, "mvp_credit_multiplier", 2.0) or 2.0)
        credits = max(1, round(tokens_to_credits(total_t) * mult))
        deduct_credits(
            founder_id, credits,
            f"MVP build — {turns} tool rounds, {total_t:,} tokens (x{mult} MVP rate)",
            session_id or None,
        )
        logger.info("MVP build billed founder=%s credits=%s tokens=%s turns=%s", founder_id, credits, total_t, turns)
    except Exception as e:
        logger.warning("MVP build billing failed: %s", e)


def _stream_build_events(cmd: list, cwd: str, timeout: int, env: dict,
                         founder_id: str, app_session_id: str, oc_session_id: str) -> str:
    """Run openclaude with stream-json output, publishing each step (assistant
    text, tool calls, and every file as it's written) live to the session so the
    technical-agent preview shows the build happening — no GitHub needed."""
    import time as _t
    import threading as _th
    from backend.core.events import publish_sync

    files: dict[str, str] = {}
    result_obj = None

    def pub(ev: dict) -> None:
        try:
            publish_sync(app_session_id, {"type": "agent_build", "agent": "technical", **ev})
        except Exception:
            pass

    with _build_semaphore:
        proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, env=env, bufsize=1)
        watchdog = _th.Timer(timeout, proc.kill)
        watchdog.daemon = True
        watchdog.start()
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
                            if name in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
                                path = inp.get("file_path") or inp.get("path") or inp.get("notebook_path") or ""
                                content = inp.get("content") or inp.get("new_string") or ""
                                if path:
                                    files[path] = content
                                    pub({"kind": "file", "path": path, "content": content[:20000], "size": len(content)})
                            elif name == "Bash":
                                pub({"kind": "command", "command": (inp.get("command") or "")[:500]})
                            elif name in ("Read", "Glob", "Grep"):
                                pub({"kind": "tool", "tool": name, "target": str(inp.get("file_path") or inp.get("pattern") or "")[:120]})
                elif etype == "result":
                    result_obj = ev
        finally:
            watchdog.cancel()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()

    if isinstance(result_obj, dict):
        _record_build_usage(result_obj, founder_id, oc_session_id)
        pub({"kind": "done", "files": list(files.keys())})
        return (result_obj.get("result") or "").strip()
    pub({"kind": "done", "files": list(files.keys())})
    return ""


def _run_claude(local: str, prompt: str, session_id: str = None, timeout: int = 480, model: str = None,
                founder_id: str = "", app_session_id: str = "") -> str:
    """
    Send one message to openclaude. When app_session_id is set, the build streams
    live to that session (transcript + files). Otherwise returns the final result.
    """
    if not os.path.exists(OPENCLAUDE_BIN):
        raise RuntimeError(f"openclaude not found at {OPENCLAUDE_BIN}")

    env = _make_env()
    model = model or env.get("OPENAI_MODEL", "moonshotai/Kimi-K2.5")
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
    openai_base = env.get("OPENAI_BASE_URL", "https://api.deepinfra.com/v1/openai")
    openai_model = env.get("OPENAI_MODEL", model)
    if os.getuid() == 0:
        cmd = [
            "sudo", "-u", "astra", "env",
            f"OPENAI_API_KEY={openai_key}",
            f"OPENAI_BASE_URL={openai_base}",
            f"OPENAI_MODEL={openai_model}",
            "HOME=/home/astra",
        ] + oc_args + [full_prompt]
    else:
        cmd = oc_args + [full_prompt]

    if stream:
        return _stream_build_events(cmd, local, timeout, env, founder_id, app_session_id, session_id)

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
    base_url = env.get("OPENAI_BASE_URL", "https://api.deepinfra.com/v1/openai")
    # These review calls run against the DeepInfra endpoint, so use a model valid
    # there (planner_model_name may be an OpenRouter-only slug -> 404).
    model = getattr(settings, "mvp_build_model", "") or "moonshotai/Kimi-K2.5"

    client = openai.OpenAI(base_url=base_url, api_key=api_key)
    missing_str = ", ".join(missing) if missing else "none — MVP may be complete"
    user_msg = (
        f"Goal: {goal}\n"
        f"Context: {context[:800] if context else 'none'}\n"
        f"Still missing files: {missing_str}\n\n"
        f"Agent's last message:\n{agent_output[-2000:]}\n\n"
        f"What do you say next? If MVP is done, respond: DONE"
    )
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _PM_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.2,
        timeout=30.0,
    )
    reply = resp.choices[0].message.content or ""
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
    client = openai.OpenAI(base_url=env["OPENAI_BASE_URL"], api_key=env["OPENAI_API_KEY"])
    # These review calls run against the DeepInfra endpoint, so use a model valid
    # there (planner_model_name may be an OpenRouter-only slug -> 404).
    model = getattr(settings, "mvp_build_model", "") or "moonshotai/Kimi-K2.5"

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
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _PLANNER_REVIEW_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            timeout=60.0,
        )
        raw = resp.choices[0].message.content or "{}"
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


_OC_TEST_PROMPT = """Verify the project you just built in THIS directory and fix any issues.
FIRST detect the actual stack — do not assume a frontend/ or backend/ folder; the
files may live at the repo root (e.g. a root-level Next.js app) or in subfolders.

1. `ls -la` and read package.json / requirements.txt / pyproject.toml to identify the stack.
2. If it's a Node/TypeScript project (package.json present): run `npx tsc --noEmit` if TypeScript is used, and verify every dependency in package.json actually exists on npm — remove any invented packages (e.g. @radix-ui/react-badge).
3. If it's a Python project (.py files / requirements.txt): run a syntax check on the real .py files only (skip folders that don't exist).
4. Find any file that is empty, contains only TODO/placeholder text, or has fewer than 5 lines of real code — rewrite it properly.
5. Ensure every import references a file/module that actually exists in this project.

Fix everything you find, then run: `git add -A && git commit -m "fix: verification pass"`.
If everything is already correct, just say OK."""


def _openclaude_test_pass(local: str, oc_session_id: str) -> str:
    """Ask openclaude to self-test and fix the codebase. Returns its output."""
    logger.info("openclaude self-test pass starting")
    return _run_claude(local, _OC_TEST_PROMPT, session_id=oc_session_id, timeout=600)


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
        # Correct next version — pin to 14.2.21 (latest stable 14.x)
        _NEXT_VERSION = "14.2.21"
        for section in ("dependencies", "devDependencies", "peerDependencies"):
            if section not in data:
                continue
            before = set(data[section])
            data[section] = {k: v for k, v in data[section].items() if k not in _FAKE_PACKAGES}
            removed = before - set(data[section])
            if removed:
                logger.warning("Removed fake npm packages: %s", removed)
                changed = True
            # Fix @next/* packages to match the actual next version
            if "next" in data[section]:
                actual_next = data[section]["next"].lstrip("^~")
                for pkg in list(data[section]):
                    if pkg.startswith("@next/"):
                        data[section][pkg] = actual_next
                        changed = True
                # If next version itself looks wrong (e.g. 14.2.23 doesn't exist), pin it
                import re as _re
                ver = actual_next
                if _re.match(r"14\.\d+\.\d+", ver) and ver > "14.2.21":
                    data[section]["next"] = _NEXT_VERSION
                    for pkg in list(data[section]):
                        if pkg.startswith("@next/"):
                            data[section][pkg] = _NEXT_VERSION
                    changed = True
                    logger.warning("Pinned next + @next/* to %s (was %s)", _NEXT_VERSION, ver)
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
            "Use ONLY these real packages: next@14.2.21, react, react-dom, typescript, tailwindcss, "
            "@tailwindcss/forms, clsx, lucide-react, @clerk/nextjs, @supabase/supabase-js, "
            "framer-motion, zod, react-hook-form. "
            "NEVER use @next/font (use next/font/google). NEVER use @radix-ui/react-badge."
        ),
        "frontend/next.config.js": "Use .js extension ONLY. Never next.config.ts or .mjs.",
        "frontend/middleware.ts": "Use @clerk/nextjs/server. Protect /dashboard/* routes.",
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


def run_mvp_loop(
    repo_url: str,
    goal: str,
    session_id: str = "default",
    context: str = "",
    required_files: list[str] = None,
    max_rounds: int = None,  # kept for API compat, ignored
    founder_id: str = "",
) -> dict:
    """
    Build MVP by calling openclaude once per missing file (no session-id — fresh context each call).
    Avoids session state pollution that caused the PM loop to spin forever.
    """
    if required_files is None:
        required_files = MVP_REQUIRED

    try:
        # GitHub-optional: clone if a repo+token exist, else build in a local
        # workspace and stream files to the preview (no GitHub required).
        local, is_github = _get_workspace(repo_url, session_id)
        oc_session_id = str(uuid.uuid4())
        Path(local, ".oc_session_id").write_text(oc_session_id)
        commits = []

        try:
            from backend.core.events import publish_sync
            publish_sync(session_id, {"type": "agent_build", "agent": "technical",
                                      "kind": "build_start", "goal": goal[:160], "github": is_github})
        except Exception:
            pass

        logger.info("MVP build start (github=%s) for %s", is_github, repo_url or "(local)")
        if is_github:
            _pull(local)

        # Pass 1: ONE autonomous build of the whole MVP in a persistent openclaude
        # session (it loops internally — writes every file, runs/tests, fixes),
        # then iterate until all required files exist. Not one-shot-per-file.
        build_sid = str(uuid.uuid4())
        manifest = "\n".join(f"- {f}" for f in required_files)
        build_prompt = (
            f"Build a COMPLETE, working MVP for this product:\n{goal}\n\n"
            + (f"Context:\n{context}\n\n" if context else "")
            + "Create real, production-ready code for ALL of these files (and any others needed to run):\n"
            + manifest + "\n\n"
            + "Rules: no stubs, no TODOs, no placeholders — every function, route, and component fully "
              "implemented and runnable. Build the ENTIRE app now, file by file, using your Write/Edit/Bash "
              "tools. Keep working until the whole MVP is complete; do not stop after one file."
        )
        logger.info("Pass 1: holistic MVP build (%d target files)", len(required_files))
        _run_claude(local, build_prompt, session_id=build_sid, timeout=1800,
                    founder_id=founder_id, app_session_id=session_id)

        # Completion loop: keep going until required files exist (up to 3 rounds).
        for _round in range(3):
            _stage_all(local)
            missing = _missing_mvp_files(local, required_files)
            if not missing:
                break
            logger.info("Completion round %d: %d still missing", _round + 1, len(missing))
            fix_prompt = (
                "These required files are still missing or incomplete: " + ", ".join(missing)
                + ". Create and fully implement them NOW with your Write tool — real, complete code. "
                + f"Project: {goal}."
            )
            _run_claude(local, fix_prompt, session_id=build_sid, timeout=900,
                        founder_id=founder_id, app_session_id=session_id)

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

        # Pass 2: openclaude self-test + fix (fresh session, reads actual files on disk)
        fix_session = str(uuid.uuid4())
        logger.info("Pass 2: openclaude fix pass")
        _run_claude(local, _OC_TEST_PROMPT, session_id=None, timeout=600, founder_id=founder_id, app_session_id=session_id)
        _sanitize_package_json(local)
        if is_github:
            sha2 = _commit_and_push(local, f"fix: verification pass — {goal[:45]}")
            if sha2:
                commits.append(sha2)
        else:
            _stage_all(local)

        # Pass 3: planner review → fix any remaining issues
        current_files = _staged_files(local)
        review = _planner_review(local, goal, current_files)
        logger.info("Planner review: pass=%s issues=%s", review["pass"], review["issues"])
        if not review["pass"] and review["fix_instructions"]:
            _run_claude(local, review["fix_instructions"], session_id=None, timeout=600, founder_id=founder_id, app_session_id=session_id)
            _sanitize_package_json(local)
            if is_github:
                sha3 = _commit_and_push(local, f"fix: planner fixes — {goal[:45]}")
                if sha3:
                    commits.append(sha3)
            else:
                _stage_all(local)

        _stage_all(local)
        all_files = _list_built_files(local)

        # Auto-deploy to Vercel so there's a live preview URL (uses placeholder env
        # vars so it builds without real keys). Only when pushed to GitHub.
        deploy_url = None
        if is_github and repo_url and getattr(settings, "vercel_token", ""):
            try:
                from backend.core.events import publish_sync
                publish_sync(session_id, {"type": "agent_build", "agent": "technical", "kind": "deploy_start"})
            except Exception:
                pass
            try:
                from backend.tools.vercel_deploy import vercel_deploy_from_github
                dep = vercel_deploy_from_github(
                    repo_url,
                    project_name=Path(local).name[:60],
                    env_vars=_placeholder_env(local),
                    root_directory=_vercel_root_dir(local),
                )
                deploy_url = dep.get("deploy_url") or dep.get("url") or dep.get("deployment_url")
                if deploy_url:
                    try:
                        from backend.core.events import publish_sync
                        publish_sync(session_id, {"type": "agent_build", "agent": "technical", "kind": "deploy", "url": deploy_url})
                    except Exception:
                        pass
            except Exception as e:
                logger.warning("auto vercel deploy failed: %s", e)

        return {
            "success": True,
            "repo_url": repo_url,
            "github_url": f"{repo_url}/tree/main" if is_github else "",
            "deploy_url": deploy_url,
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
    repo_url: str,
    task: str,
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
    repo_url: str,
    files: dict,
    commit_message: str = "feat: add files",
    session_id: str = "default",
) -> dict:
    """
    Write specific files directly to a GitHub repo and push.
    files: {"relative/path.ext": "file content string"}
    """
    if not settings.github_token:
        return {"error": "GITHUB_TOKEN not set"}
    if not files:
        return {"error": "No files provided"}
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
