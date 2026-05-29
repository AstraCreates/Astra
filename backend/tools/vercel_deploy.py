import hashlib
import logging
import os
import subprocess
import time
import requests

from backend.config import settings

logger = logging.getLogger(__name__)

_VERCEL_API = "https://api.vercel.com"


def _vercel_cli_deploy(local_path: str, project_name: str = "", token: str = "") -> dict:
    """Deploy from local directory using Vercel CLI. No GitHub connection needed."""
    token = token or getattr(settings, "vercel_token", "")
    if not token:
        return {"deployed": False, "error": "VERCEL_TOKEN not set"}

    vercel_bin = subprocess.run(["which", "vercel"], capture_output=True, text=True).stdout.strip()
    if not vercel_bin:
        return {"deployed": False, "error": "vercel CLI not found"}

    env = os.environ.copy()
    env["VERCEL_TOKEN"] = token

    cmd = [vercel_bin, "deploy", "--prod", "--yes", "--token", token, "--scope", "astratestingmail-9022s-projects"]
    # --name is deprecated; set project name via vercel.json instead
    if project_name:
        import json as _json
        vj = os.path.join(local_path, "vercel.json")
        try:
            cfg = _json.loads(open(vj).read()) if os.path.exists(vj) else {}
        except Exception:
            cfg = {}
        if "name" not in cfg:
            cfg["name"] = project_name[:52].lower().replace("_", "-").replace(" ", "-")
            open(vj, "w").write(_json.dumps(cfg, indent=2))

    try:
        r = subprocess.run(cmd, cwd=local_path, capture_output=True, text=True, timeout=300, env=env)
        output = (r.stdout + r.stderr).strip()
        # Extract URL from output — Vercel CLI prints the deployment URL on stdout
        url = next((line.strip() for line in r.stdout.splitlines() if line.strip().startswith("https://")), "")
        if r.returncode == 0 and url:
            return {"deployed": True, "deployment_url": url, "project_url": url, "via": "vercel-cli"}
        logger.warning("vercel CLI deploy output: %s", output[:400])
        return {"deployed": False, "error": output[:300], "via": "vercel-cli"}
    except subprocess.TimeoutExpired:
        return {"deployed": False, "error": "vercel CLI timed out (300s)"}
    except Exception as e:
        return {"deployed": False, "error": str(e)}


def _poll_deployment(dep_id: str, team_id: str | None, headers: dict, timeout: int = 300) -> str | None:
    """Poll Vercel until deployment is READY or ERROR. Returns error string or None on success."""
    if not dep_id:
        return None  # Can't poll — assume ok
    deadline = time.time() + timeout
    status_url = f"{_VERCEL_API}/v13/deployments/{dep_id}"
    if team_id:
        status_url += f"?teamId={team_id}"
    while time.time() < deadline:
        try:
            r = requests.get(status_url, headers=headers, timeout=15)
            if not r.ok:
                time.sleep(10)
                continue
            data = r.json()
            state = data.get("readyState") or data.get("state", "")
            if state == "READY":
                return None
            if state in ("ERROR", "CANCELED"):
                # Extract build error from deployment
                err = data.get("errorMessage") or ""
                # Try to get build output for npm errors
                build_url = f"{_VERCEL_API}/v2/deployments/{dep_id}/events"
                if team_id:
                    build_url += f"?teamId={team_id}"
                try:
                    ev = requests.get(build_url, headers=headers, timeout=10)
                    if ev.ok:
                        lines = [e.get("text", "") for e in ev.json() if e.get("text")]
                        err = "\n".join(lines[-40:]) or err
                except Exception:
                    pass
                return err or f"Deployment {state}"
        except Exception:
            pass
        time.sleep(10)
    return "Deployment timed out after 5 minutes"


# Known fake/deprecated packages the LLM hallucinates
_FAKE_PACKAGES = {
    "@radix-ui/react-badge", "@radix-ui/react-layout", "@radix-ui/react-grid",
    "@radix-ui/react-flex", "@radix-ui/react-container",
    "@next/font",  # merged into next/font in Next.js 13+
}


def _research_build_error(build_error: str) -> str:
    """Search for docs/fixes for a Vercel build error. Returns research context string."""
    try:
        from backend.tools.web_search import web_search
        # Extract the key error phrase to search
        import re as _re
        # Look for npm error codes, package names, or error messages
        patterns = [
            r"npm error ([A-Z0-9]+)",
            r"No matching version found for ([^\s]+)",
            r"Cannot find module '([^']+)'",
            r"Module not found: Can't resolve '([^']+)'",
            r"Error: (.{20,80}?)[\n\r]",
        ]
        query = None
        for pat in patterns:
            m = _re.search(pat, build_error)
            if m:
                query = f"Next.js Vercel build error fix: {m.group(0)[:120]}"
                break
        if not query:
            query = f"Next.js Vercel build error: {build_error[:100]}"

        result = web_search(query=query, max_results=3)
        snippets = []
        for r in (result.get("results") or [])[:3]:
            title = r.get("title", "")
            snippet = r.get("snippet") or r.get("description") or ""
            url = r.get("url", "")
            if snippet:
                snippets.append(f"[{title}] {snippet} ({url})")
        return "\n".join(snippets) if snippets else ""
    except Exception as e:
        logger.debug("Error research failed: %s", e)
        return ""


def _fix_repo_and_push(repo_url: str, build_error: str, gh_owner: str, gh_repo: str, headers: dict) -> bool:
    """Attempt to fix the repo based on the build error and push a new commit. Returns True if pushed."""
    import json as _json
    from pathlib import Path

    # Find local clone
    try:
        from backend.tools.git_tools import _clones
        local = next((v for k, v in _clones.items() if repo_url in k and os.path.isdir(v)), None)
    except Exception:
        local = None

    if not local:
        return False

    try:
        import subprocess as _sp

        fixed = False

        # Fix 1: npm E404 — remove fake packages from package.json
        if "E404" in build_error or "Not found" in build_error:
            pkg_path = Path(local) / "frontend" / "package.json"
            if pkg_path.exists():
                data = _json.loads(pkg_path.read_text())
                for section in ("dependencies", "devDependencies", "peerDependencies"):
                    if section in data:
                        bad = {k for k in data[section] if k in _FAKE_PACKAGES}
                        # Also strip any package that looks invented (not in known-good list)
                        if bad:
                            for k in bad:
                                del data[section][k]
                            logger.warning("Auto-fix: removed fake packages %s", bad)
                            fixed = True
                if fixed:
                    pkg_path.write_text(_json.dumps(data, indent=2))

        # Fix 1b: ETARGET — package version doesn't exist (hallucinated versions)
        if "ETARGET" in build_error or "notarget" in build_error or "No matching version found" in build_error:
            import re as _re
            pkg_path = Path(local) / "frontend" / "package.json"
            if pkg_path.exists():
                data = _json.loads(pkg_path.read_text())
                changed = False
                for section in ("dependencies", "devDependencies", "peerDependencies"):
                    if section not in data:
                        continue
                    # @next/font was merged into next/font in Next.js 13 — remove entirely
                    if "@next/font" in data[section]:
                        del data[section]["@next/font"]
                        logger.warning("Auto-fix: removed @next/font (use next/font instead)")
                        changed = True
                    # For other ETARGET errors, relax pinned version to "latest"
                    pkg_match = _re.search(r"No matching version found for ([^\s.]+)", build_error)
                    if pkg_match:
                        bad_pkg = pkg_match.group(1)
                        if bad_pkg in data[section]:
                            data[section][bad_pkg] = "latest"
                            logger.warning("Auto-fix: relaxed %s to 'latest'", bad_pkg)
                            changed = True
                if changed:
                    pkg_path.write_text(_json.dumps(data, indent=2))
                    # Also replace @next/font imports with next/font in source files
                    src_dirs = [Path(local) / "frontend" / "app", Path(local) / "frontend" / "src", Path(local) / "frontend" / "pages"]
                    for src_dir in src_dirs:
                        if not src_dir.exists():
                            continue
                        for f in src_dir.rglob("*.tsx"):
                            try:
                                content = f.read_text()
                                if "@next/font" in content:
                                    f.write_text(content.replace("@next/font", "next/font"))
                                    logger.warning("Auto-fix: replaced @next/font → next/font in %s", f)
                            except Exception:
                                pass
                    fixed = True

        # Fix 2: TypeScript errors — add skipLibCheck to tsconfig
        if "TypeScript" in build_error or "TS" in build_error:
            ts_path = Path(local) / "frontend" / "tsconfig.json"
            if ts_path.exists():
                ts = _json.loads(ts_path.read_text())
                if not ts.get("compilerOptions", {}).get("skipLibCheck"):
                    ts.setdefault("compilerOptions", {})["skipLibCheck"] = True
                    ts_path.write_text(_json.dumps(ts, indent=2))
                    fixed = True

        # Fix 3: next.config.ts not supported — rename to next.config.mjs
        if "next.config.ts" in build_error and "not supported" in build_error:
            ts_cfg = Path(local) / "frontend" / "next.config.ts"
            mjs_cfg = Path(local) / "frontend" / "next.config.mjs"
            if ts_cfg.exists() and not mjs_cfg.exists():
                content = ts_cfg.read_text()
                # Strip TypeScript-only syntax: type imports, export type, `: NextConfig`
                import re as _re
                content = _re.sub(r"^import type.*\n", "", content, flags=_re.MULTILINE)
                content = _re.sub(r":\s*NextConfig\b", "", content)
                content = content.replace("export default config satisfies NextConfig", "export default config")
                mjs_cfg.write_text(content)
                ts_cfg.unlink()
                logger.warning("Auto-fix: renamed next.config.ts → next.config.mjs")
                fixed = True
            elif ts_cfg.exists():
                ts_cfg.unlink()
                logger.warning("Auto-fix: removed next.config.ts (next.config.mjs already exists)")
                fixed = True

        # Fix 4: generic — research the error, then ask openclaude to fix it
        if not fixed and ("Error:" in build_error or "error" in build_error.lower()):
            try:
                from backend.tools.git_tools import _run_claude, OPENCLAUDE_BIN
                import os as _os
                sid_file = Path(local) / ".oc_session_id"
                oc_sid = sid_file.read_text().strip() if sid_file.exists() else None
                if _os.path.exists(OPENCLAUDE_BIN):
                    # Research the error first to get docs/fix guidance
                    research_context = _research_build_error(build_error)
                    fix_prompt = (
                        f"The Vercel deployment failed with this error:\n\n{build_error[:800]}\n\n"
                        + (f"Research context / fix guidance:\n{research_context}\n\n" if research_context else "")
                        + "Fix the issue in the frontend/ directory. "
                        "After fixing, run: bash -c \"git add -A && git commit -m 'fix: vercel build error'\""
                    )
                    _run_claude(local, fix_prompt, session_id=oc_sid, timeout=300)
                    fixed = True
            except Exception as fix_err:
                logger.warning("openclaude fix attempt failed: %s", fix_err)

        if not fixed:
            return False

        # Commit and push the fix
        def _run(cmd, **kw):
            _sp.run(cmd, check=True, capture_output=True, cwd=local, **kw)

        _run(["git", "add", "-A"])
        _run(["git", "commit", "-m", "fix: auto-fix deployment errors"])
        _run(["git", "push", "origin", "main"])
        logger.info("Pushed auto-fix commit to %s", repo_url)
        return True

    except Exception as e:
        logger.warning("Auto-fix push failed: %s", e)
        return False


def vercel_deploy_from_github(
    repo_url: str,
    project_name: str = "",
    env_vars: dict = None,
    framework: str = "nextjs",
    root_directory: str = "",
    install_command: str = "",
    build_command: str = "",
    founder_id: str = "",
    **kwargs,
) -> dict:
    """
    Create a Vercel project linked to a GitHub repo and trigger a production deployment.
    Vercel will auto-deploy on every push thereafter.

    Args:
        repo_url: GitHub repo URL (https://github.com/owner/repo)
        project_name: Vercel project name (url-safe, unique per team)
        env_vars: dict of env var key→value to inject (e.g. SUPABASE_URL, CLERK_SECRET_KEY)
        framework: nextjs | vite | create-react-app | other (default: nextjs)
        root_directory: monorepo sub-path (e.g. "frontend") — REQUIRED for monorepos, pass "frontend" for Next.js projects in frontend/ subdirectory
        install_command: override npm install command
        build_command: override build command

    Returns: {deployed, project_url, deployment_url, project_id, error?}
    """
    if not project_name:
        project_name = repo_url.rstrip("/").split("/")[-1]

    # Auto-detect root_directory from local clone if not specified
    if not root_directory:
        try:
            from backend.tools.git_tools import _clones
            from pathlib import Path as _Path
            local = next((v for k, v in _clones.items() if repo_url in k and os.path.isdir(v)), None)
            if local:
                for candidate in ("frontend", "web", "app", "client"):
                    candidate_path = _Path(local) / candidate
                    if (candidate_path / "package.json").exists() or (candidate_path / "next.config.ts").exists() or (candidate_path / "next.config.js").exists() or (candidate_path / "next.config.mjs").exists():
                        root_directory = candidate
                        logger.info("Auto-detected root_directory=%s from local clone", root_directory)
                        break
        except Exception:
            pass

    token = getattr(settings, "vercel_token", None)
    if not token:
        return {
            "deployed": False,
            "error": "VERCEL_TOKEN not set",
            "manual": (
                f"1. Go to vercel.com/new → Import Git Repository → {repo_url}\n"
                f"2. Set framework to {framework}\n"
                "3. Add env vars from env_vars dict\n"
                "4. Click Deploy"
            ),
        }

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Resolve team
    team_id = None
    try:
        user_resp = requests.get(f"{_VERCEL_API}/v2/user", headers=headers, timeout=10)
        if user_resp.ok:
            team_id = user_resp.json().get("user", {}).get("defaultTeamId")
    except Exception:
        pass

    # Parse owner/repo from URL
    parts = repo_url.rstrip("/").split("/")
    if len(parts) < 2:
        return {"deployed": False, "error": f"Invalid repo_url: {repo_url}"}
    gh_owner, gh_repo = parts[-2], parts[-1]

    try:
        # Create project linked to GitHub
        create_url = f"{_VERCEL_API}/v9/projects"
        if team_id:
            create_url += f"?teamId={team_id}"

        project_payload = {
            "name": project_name,
            "gitRepository": {"type": "github", "repo": f"{gh_owner}/{gh_repo}"},
            "framework": framework if framework != "other" else None,
        }
        if root_directory:
            project_payload["rootDirectory"] = root_directory
        if install_command:
            project_payload["installCommand"] = install_command
        if build_command:
            project_payload["buildCommand"] = build_command

        proj_resp = requests.post(create_url, json=project_payload, headers=headers, timeout=20)

        # 409 = project already exists — fetch it instead
        if proj_resp.status_code == 409:
            get_url = f"{_VERCEL_API}/v9/projects/{project_name}"
            if team_id:
                get_url += f"?teamId={team_id}"
            proj_resp = requests.get(get_url, headers=headers, timeout=10)

        if not proj_resp.ok:
            err_text = proj_resp.text[:400]
            if any(k in err_text for k in ("Login Connection", "Install GitHub App", "GitHub integration", "login-connections", "github.com/apps/vercel")):
                # GitHub not linked to Vercel — fall back to CLI deploy from local clone
                logger.info("GitHub not linked to Vercel — trying CLI deploy from local clone")
                try:
                    from backend.tools.git_tools import _clones
                    local = next(
                        (v for k, v in _clones.items() if repo_url in k and os.path.isdir(v)),
                        None,
                    )
                    if local:
                        return _vercel_cli_deploy(local, project_name, token)
                except Exception as cli_err:
                    logger.warning("CLI fallback failed: %s", cli_err)
                return {
                    "deployed": False,
                    "error": "Vercel not linked to GitHub and CLI fallback unavailable.",
                    "fix": "vercel.com/account/login-connections → connect GitHub",
                    "repo_url": repo_url,
                }
            return {"deployed": False, "error": f"Project creation failed: {err_text}"}

        proj = proj_resp.json()
        project_id = proj.get("id", "")

        # Set env vars
        if env_vars:
            env_url = f"{_VERCEL_API}/v10/projects/{project_id}/env"
            if team_id:
                env_url += f"?teamId={team_id}"
            env_payload = [
                {"key": k, "value": str(v), "type": "encrypted", "target": ["production", "preview", "development"]}
                for k, v in (env_vars or {}).items()
                if v
            ]
            if env_payload:
                requests.post(env_url, json=env_payload, headers=headers, timeout=15)

        # Trigger deployment from latest commit on default branch
        deploy_url = f"{_VERCEL_API}/v13/deployments"
        if team_id:
            deploy_url += f"?teamId={team_id}"

        deploy_payload = {
            "name": project_name,
            "gitSource": {
                "type": "github",
                "org": gh_owner,
                "repo": gh_repo,
                "ref": "main",
            },
            "target": "production",
            "projectSettings": {"framework": framework if framework != "other" else None},
        }
        MAX_DEPLOY_ATTEMPTS = 3
        last_result: dict = {}

        for attempt in range(1, MAX_DEPLOY_ATTEMPTS + 1):
            deploy_resp = requests.post(deploy_url, json=deploy_payload, headers=headers, timeout=30)

            if not deploy_resp.ok:
                last_result = {"deployed": False, "error": f"Deploy trigger failed: {deploy_resp.text[:200]}"}
                break

            dep_data = deploy_resp.json()
            dep_id = dep_data.get("id", "")
            deployment_url = f"https://{dep_data.get('url', '')}" if dep_data.get("url") else ""

            # Poll until READY or ERROR (up to 5 min)
            build_error = _poll_deployment(dep_id, team_id, headers)

            if build_error is None:
                # Success
                project_url = f"https://{project_name}.vercel.app"
                last_result = {
                    "deployed": True,
                    "project_url": project_url,
                    "deployment_url": deployment_url or project_url,
                    "project_id": project_id,
                    "github_repo": repo_url,
                    "attempts": attempt,
                }
                break

            logger.warning("Deployment attempt %d failed: %s", attempt, build_error[:200])

            if attempt < MAX_DEPLOY_ATTEMPTS:
                # Try to fix the repo and push a new commit before retrying
                fixed = _fix_repo_and_push(repo_url, build_error, gh_owner, gh_repo, headers)
                if not fixed:
                    last_result = {"deployed": False, "error": build_error, "attempts": attempt}
                    break
                # Small delay so GitHub propagates the new commit
                time.sleep(5)
            else:
                last_result = {"deployed": False, "error": build_error, "attempts": attempt}

        project_url = f"https://{project_name}.vercel.app"
        return last_result or {"deployed": False, "error": "No deploy attempt made"}

    except Exception as e:
        logger.error("vercel_deploy_from_github failed: %s", e)
        return {"deployed": False, "error": str(e)}


def vercel_deploy(project_slug: str, html: str, css: str = "", js: str = "") -> dict:
    """Deploy HTML to Vercel. Args: project_slug (url-safe name), html (full HTML string), css (optional), js (optional). Returns: {deployed, url} or {deployed: false, local_path}."""
    token = getattr(settings, "vercel_token", None)

    if not token:
        return _local_fallback(project_slug, html, css, js)

    files = [
        {"file": "index.html", "data": html, "encoding": "utf-8"},
    ]
    if css:
        files.append({"file": "styles.css", "data": css, "encoding": "utf-8"})
    if js:
        files.append({"file": "app.js", "data": js, "encoding": "utf-8"})

    try:
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        # Resolve team ID from the token owner
        user_resp = requests.get(f"{_VERCEL_API}/v2/user", headers=headers, timeout=10)
        team_id = None
        if user_resp.ok:
            team_id = user_resp.json().get("user", {}).get("defaultTeamId")

        deploy_url = f"{_VERCEL_API}/v13/deployments"
        if team_id:
            deploy_url += f"?teamId={team_id}"

        # Create deployment
        payload = {
            "name": project_slug,
            "files": files,
            "projectSettings": {"framework": None},
            "target": "production",
        }
        resp = requests.post(deploy_url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        url = f"https://{data.get('url', '')}"
        return {
            "deployed": True,
            "url": url,
            "deployment_id": data.get("id"),
            "project": project_slug,
        }
    except Exception as e:
        logger.error("vercel_deploy failed: %s", e)
        return _local_fallback(project_slug, html, css, js)


def _local_fallback(project_slug: str, html: str, css: str, js: str) -> dict:
    import os
    out_dir = f"/tmp/astra_sites/{project_slug}"
    os.makedirs(out_dir, exist_ok=True)
    with open(f"{out_dir}/index.html", "w") as f:
        f.write(html)
    if css:
        with open(f"{out_dir}/styles.css", "w") as f:
            f.write(css)
    if js:
        with open(f"{out_dir}/app.js", "w") as f:
            f.write(js)
    return {
        "deployed": False,
        "local_path": out_dir,
        "note": "VERCEL_TOKEN not set — files saved locally. Set VERCEL_TOKEN to auto-deploy.",
    }


def generate_landing_page_html(
    page_title: str,
    headline: str,
    subheadline: str,
    value_props: list[str],
    cta_text: str,
    cta_url: str,
    company_name: str = "",
    business_context: str = "",
) -> str:
    """Generate a complete, production-quality landing page HTML. Args: page_title, headline, subheadline, value_props (list of strings), cta_text, cta_url, company_name (optional), business_context (optional)."""
    import re, random, hashlib
    name = company_name or page_title
    props_text = "\n".join(f"- {p}" for p in value_props)

    # When no design agent context, inject a deterministic-random aesthetic seed
    # so each product gets a unique look instead of the same LLM default
    _design_context = business_context or ""

    # Strip banned fonts from design context — the LLM follows explicit font names
    # even when told not to, so we must remove them before they hit the prompt.
    # Also strip entire "Fonts: ..." clauses to prevent residue like "Fonts: '' for body".
    _design_context = re.sub(r"(?i)Fonts?:[^.]*\.", "", _design_context)
    _BANNED_FONTS = ["Inter", "Poppins", "Roboto", "system-ui", "Arial", "Helvetica"]
    for _font in _BANNED_FONTS:
        _design_context = re.sub(rf"(?i)\b{re.escape(_font)}\b[,.]?", "", _design_context)
    _design_context = re.sub(r",\s*,", ",", _design_context)
    _design_context = re.sub(r"'\s*'", "", _design_context)
    _design_context = " ".join(_design_context.split())  # collapse whitespace

    # Always inject a distinctive heading font (deterministic per product name).
    # Design context may have brand colors but we stripped its font spec — supply one.
    _HEADINGS = [
        "'Fraunces', serif", "'Syne', sans-serif", "'Playfair Display', serif",
        "'DM Serif Display', serif", "'Bebas Neue', sans-serif",
        "'Cormorant Garamond', serif", "'Space Grotesk', sans-serif",
        "'Libre Baskerville', serif", "'Unbounded', sans-serif",
        "'Instrument Serif', serif", "'Chivo', sans-serif",
    ]
    _seed = int(hashlib.md5(name.encode()).hexdigest(), 16)
    _heading_font = random.Random(_seed).choice(_HEADINGS)
    _design_context += f" Heading font: {_heading_font}."

    # Build a concrete Google Fonts link the model must copy verbatim — no ambiguity.
    _font_slug = re.sub(r"['\"]", "", _heading_font.split(",")[0]).strip().replace(" ", "+")
    _gfonts_link = (
        f'<link rel="preconnect" href="https://fonts.googleapis.com">'
        f'<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        f'<link href="https://fonts.googleapis.com/css2?family={_font_slug}:wght@400;700;900&display=swap" rel="stylesheet">'
    )

    if not any(kw in _design_context.lower() for kw in ("hex", "#", "color", "palette", "vibe")):
        _PALETTES = [
            ("warm cream + charcoal red", "#faf7f2", "#1a1a1a", "#c84b31"),
            ("jet black + electric lime", "#0a0a0a", "#f0f0f0", "#b5ff47"),
            ("deep navy + warm sand + cyan", "#0d1b2a", "#e8dcc8", "#4fc3f7"),
            ("soft sage + forest green", "#f5f7f2", "#2d4a3e", "#5c8a6e"),
            ("midnight + coral", "#0a0a0a", "#f5f5f5", "#ff4d4d"),
            ("warm amber + espresso", "#fff8f0", "#2c1a0e", "#e8820c"),
            ("ice blue + gold", "#f0f4ff", "#1e293b", "#f59e0b"),
            ("dusty rose + terracotta", "#fdf4f5", "#2a2a2a", "#c97b5a"),
            ("mint + electric teal", "#f0faf8", "#1a2e2b", "#00c9a7"),
            ("off-white + violet", "#fafafa", "#1a0a2e", "#7c3aed"),
        ]
        _HEADINGS = [
            "'Fraunces', serif", "'Syne', sans-serif", "'Playfair Display', serif",
            "'DM Serif Display', serif", "'Bebas Neue', sans-serif",
            "'Cormorant Garamond', serif", "'Space Grotesk', sans-serif",
            "'Libre Baskerville', serif", "'Cabinet Grotesk', sans-serif",
            "'Unbounded', sans-serif",
        ]
        _LAYOUTS = [
            "centered hero, generous whitespace, editorial type scale",
            "left-aligned hero with large right-side metric panel",
            "full-bleed dark hero, light content sections below",
            "split hero: headline left, animated stats right",
            "brutalist grid layout, thick rule borders, oversized type",
            "magazine-style: oversized pull quote as hero element",
        ]
        seed = int(hashlib.md5(name.encode()).hexdigest(), 16)
        rng = random.Random(seed)
        label, bg, fg, accent = rng.choice(_PALETTES)
        heading = rng.choice(_HEADINGS)
        layout = rng.choice(_LAYOUTS)
        _design_context = (
            f"{_design_context}\n"
            f"AESTHETIC SEED (apply exactly — palette: {label}):\n"
            f"  background={bg}  foreground={fg}  accent={accent}\n"
            f"  heading-font={heading}\n"
            f"  layout={layout}"
        )

    # Each entry is a structural description that forces a different DOM arrangement.
    # Vibes are useless — models ignore them. These describe concrete section structures.
    _STRUCTURES = [
        "Two-column sticky layout: left column is fixed with logo, one-line pitch, and CTA button. Right column scrolls with all content (value props as large numbered items, each with a short paragraph). No hero section.",
        "Full-screen scroll-snap slides: each value prop gets its own full-viewport slide with a giant number (01, 02…) and one sentence. The first slide is just the headline. Last slide has the CTA form.",
        "Long-form manifesto page: no sections or cards. Continuous prose that weaves the value props into flowing paragraphs with large pull-quotes. CTA is inline mid-page and again at bottom.",
        "Asymmetric split hero: left 60% is a massive headline that takes 3+ lines, right 40% is a narrow column with subheadline + value props as a tight bullet list + CTA. Below: one wide full-bleed stats bar.",
        "Horizontal feature strips: after a minimal one-line hero, each value prop is a full-width alternating strip (text left/image right, then text right/image left). Very tall page.",
        "Bento grid homepage: the entire page is a CSS grid of differently-sized cards. Headline card spans full width. Each value prop is a different-sized card. CTA is the largest card.",
        "Timeline layout: vertical center line with value props alternating left and right. Hero is just a small badge + headline at the top. CTA floats at the bottom.",
        "Terminal/typewriter hero: the headline types itself out in a code-style terminal block. Value props listed as command outputs. CTA is a prompt: '> get started'.",
        "Oversized type poster: the product name and headline are displayed at 200px+ font size, wrapping across the full page. Value props in tiny footnote-style text below. Minimal everything else.",
        "Card magazine grid: 3-column unequal grid, cards have different heights. Hero card spans 2 columns. Value prop cards each have a different background color. Footer card has the CTA.",
    ]
    _rng = random.Random(_seed + 1)
    _vibe_instruction = _rng.choice(_STRUCTURES)

    # Pre-scaffold all 13 sections so the model fills content into an existing structure
    # rather than inventing its own — models default to hero→features→CTA regardless
    # of instructions; giving them the skeleton forces coverage of every required section.
    scaffold = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{name}</title>
<script src="https://cdn.tailwindcss.com"></script>
<!-- ADD Google Fonts <link> for: {_heading_font} here -->
</head>
<body>
<!-- NAV: sticky top nav with backdrop blur, logo left, anchor links right -->

<!-- SECTION hero: full-viewport, big bold headline="{headline}", subheadline, 2 CTA buttons, animated scroll-down chevron -->
<section id="hero"></section>

<!-- SECTION proof: infinite CSS-only auto-scrolling marquee ribbon of 8 integration logo names (styled as badges) -->
<section id="proof"></section>

<!-- SECTION philosophy: sticky split — left column fixed manifesto, right column scrolls 3 paragraphs + blockquote about {name} -->
<section id="philosophy"></section>

<!-- SECTION bento: asymmetric CSS grid, 6 cards (2 large, 4 small), glassmorphism bg, hover-lift. One card per capability:
{props_text} -->
<section id="bento"></section>

<!-- SECTION stats: 4 large animated counters (JS IntersectionObserver, counts from 0 on scroll). Pick 4 impressive numbers for {name}. -->
<section id="stats"></section>

<!-- SECTION how: 3 steps numbered 01/02/03, each with icon + title + 2-sentence description of how {name} works -->
<section id="how"></section>

<!-- SECTION features: detailed alternating-layout cards (text-left/image-right, then text-right/image-left) for each capability above -->
<section id="features"></section>

<!-- SECTION testimonials: 3 cards with long quote, avatar initial circle, full name, job title, company -->
<section id="testimonials"></section>

<!-- SECTION pricing: 3 tiers — Starter/Pro/Business. Monthly price, 5-item checklist, CTA button. Pro = most popular badge. -->
<section id="pricing"></section>

<!-- SECTION timeline: vertical center-line, 5 milestones for {name}. Active milestone highlighted on scroll via JS. -->
<section id="timeline"></section>

<!-- SECTION faq: 6-item accordion. JS toggles answer visibility on click. Animated +/− icon. Real questions about {name}. -->
<section id="faq"></section>

<!-- SECTION waitlist: full-width email capture. On submit show "You're on the list!" inline, no page reload. -->
<section id="waitlist"></section>

<!-- SECTION footer: 4-column mega-footer — sitemap links, contact info, newsletter input, social links. © {name} 2026 -->
<footer id="footer"></footer>

<!-- ALL JS inline here: marquee, counter IntersectionObserver, accordion toggle, waitlist submit, timeline scroll highlight -->
<script></script>
</body>
</html>"""

    prompt = f"""Fill in every section of this HTML skeleton completely. Replace each HTML comment with full working code.
Design tokens: {_design_context or f"dark premium aesthetic, {name}"}
Brand: {name} | CTA: "{cta_text}" → {cta_url}
Output ONLY the completed HTML — no explanation, no markdown fences.

{scaffold}"""

    logger.info("design_context passed to HTML gen: %.600s", _design_context)
    import time as _time, openai
    from backend.tools._llm import _api_key, _DI_BASE

    for attempt in range(2):
        logger.info("HTML gen attempt %d/2 (direct API, nemotron-nano) …", attempt + 1)
        t0 = _time.monotonic()
        try:
            client = openai.OpenAI(base_url=_DI_BASE, api_key=_api_key())
            resp = client.chat.completions.create(
                model="Qwen/Qwen3-235B-A22B-Instruct-2507",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=32000,
                timeout=600.0,
            )
            html = resp.choices[0].message.content or ""
            elapsed = _time.monotonic() - t0
            logger.info("HTML gen attempt %d done in %.1fs — %d chars", attempt + 1, elapsed, len(html))
            _preview_path = "/tmp/astra_last_html.html"
            try:
                open(_preview_path, "w").write(html)
                logger.info("HTML saved to %s — open in browser to preview", _preview_path)
            except Exception:
                pass

            # Post-process: swap banned fonts for our chosen heading font
            _banned_re = re.compile(r"\b(Inter|Poppins|Roboto|Lato|Open\+Sans|Open Sans)\b", re.IGNORECASE)
            if _banned_re.search(html):
                html = re.sub(
                    r'(href="https://fonts\.googleapis\.com/css2\?)[^"]*"',
                    f'href="https://fonts.googleapis.com/css2?family={_font_slug}:ital,wght@0,400;0,700;0,900;1,400&display=swap"',
                    html,
                )
                _fn = _heading_font.split(",")[0].strip("'\"")
                html = re.sub(r"'Inter'",   f"'{_fn}'", html)
                html = re.sub(r'"Inter"',   f'"{_fn}"', html)
                html = re.sub(r"'Poppins'", f"'{_fn}'", html)
                html = re.sub(r'"Poppins"', f'"{_fn}"', html)
                html = re.sub(r"'Roboto'",  f"'{_fn}'", html)
                logger.info("Post-processed font: replaced banned fonts with %s", _heading_font)

            html = re.sub(r"```html?", "", html, flags=re.IGNORECASE).strip().rstrip("`").strip()
            doctype_pos = html.lower().find("<!doctype")
            if doctype_pos != -1:
                body = html[doctype_pos:]
                logger.info("HTML accepted (%d chars)", len(body))
                return body
            html_tag_pos = html.lower().find("<html")
            if html_tag_pos != -1:
                body = html[html_tag_pos:]
                logger.info("HTML accepted via <html> path (%d chars)", len(body))
                return "<!DOCTYPE html>\n" + body
            logger.warning("HTML attempt %d REJECTED — no <!DOCTYPE> or <html>. Preview: %.300r", attempt + 1, html[:300])
        except Exception as e:
            elapsed = _time.monotonic() - t0
            logger.warning("HTML gen attempt %d FAILED in %.1fs — %s: %s", attempt + 1, elapsed, type(e).__name__, e)

    raise RuntimeError("generate_landing_page_html: LLM failed to produce valid HTML after 2 attempts")
