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

    cmd = [vercel_bin, "deploy", "--prod", "--yes", "--token", token]
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
    import re
    name = company_name or page_title
    props_text = "\n".join(f"- {p}" for p in value_props)

    prompt = f"""You are a senior product designer and frontend engineer who specialises in clean, premium, intentional UI. Write a complete single-file HTML landing page. Output ONLY raw HTML — no markdown, no backticks, no explanation.

PRODUCT
Name: {name}
Headline: {headline}
Subheadline: {subheadline}
Value props:
{props_text}
CTA: "{cta_text}" → {cta_url}
Design context (use any hex colors, fonts, brand_vibe specified here — they override all defaults): {business_context or "N/A"}

═══════════════════════════════════════
MANDATORY DESIGN SYSTEM — violating any rule is a failure
═══════════════════════════════════════

SPACING: Strict 8-point grid. Every margin, padding, gap must be a multiple of 8px (8, 16, 24, 32, 48, 64, 96, 128). Zero random values.

TYPOGRAPHY: Pick ONE distinctive heading font loaded from Google Fonts (NOT Inter, NOT Roboto, NOT Poppins, NOT Montserrat — choose something with character: Fraunces, Playfair Display, Space Grotesk, DM Serif Display, Syne, Cabinet Grotesk, Switzer, Clash Display, etc.). Pair with ONE clean body font. Define a type scale and use it consistently. Hero h1: clamp(3rem,6vw,5.5rem), weight 700-900, letter-spacing -0.03em. Section headers: 1.75rem-2.5rem. Body: 1rem/1.7. Never mix weights randomly.

COLORS: If design context has hex values, use them exactly. Otherwise pick a palette that fits the product — do NOT default to dark blue #06080f every time. Consider: warm off-white with charcoal (#1a1a1a), or sage green with cream, or deep navy with gold, or pure white with black and one sharp accent. The palette must feel intentional for THIS specific product. No purple unless brand calls for it.

BORDERS & RADIUS: Pick ONE radius and use it everywhere (either 4px, 8px, 12px, or 16px — not mixed). Cards, buttons, inputs all match.

LAYOUT SECTIONS (in this order):
1. Nav: logo left (custom font, brand name), nav links center or right, single CTA button. Position: sticky. Border-bottom: 1px solid. Backdrop-filter: blur(12px). Background: semi-transparent version of page background.
2. Hero: asymmetric OR centered — choose based on product. Large headline, concise subheadline (1 sentence max), ONE primary CTA button, optional ghost secondary. No sparkles. No emojis. No gradient text. Specific copy only.
3. Social proof bar: real-looking metrics (format as "X,XXX" or "Y%" or "$ZM") with labels. Thin top/bottom borders. Subtle background.
4. Features: 3-col grid desktop, 1-col mobile. Each card: consistent padding, ONE small icon or number, bold title, 2-line description. Hover: 0.15s border-color transition only — no lift, no scale, no shadow explosion.
5. How it works: numbered steps (1, 2, 3) in a horizontal row. Step number large and in accent color. Dividers between. Clean.
6. CTA section: 1 headline, 1 sentence, 1 button. That's it.
7. Footer: © {name} 2026. Privacy · Terms · Contact. One line. Top border only.

BANNED — automatic failure if any of these appear:
✗ Purple gradient hero (unless brand color is purple)
✗ Sparkle emoji ✨ anywhere
✗ Emojis as UI icons or in headings
✗ Fake testimonials with AI-generated-looking avatars
✗ Social icons linking to # or twitter.com/
✗ "Build your dreams" / "Launch faster" / "Where ideas become reality" type filler copy
✗ Card hover that lifts, scales, rotates, or bounces
✗ Lottie animations or any JS animation
✗ Inconsistent border radii
✗ Random spacing not on the 8pt grid
✗ Inter/Roboto/Poppins/Montserrat as heading font
✗ Multiple gradient backgrounds stacked
✗ Copyright saying "YourSiteName" or "2024" (use {name} and 2026)

TECHNICAL:
- All CSS in one <style> block — zero CDN, zero external dependencies EXCEPT Google Fonts (one @import is fine)
- Two breakpoints: 768px (tablet) and 480px (mobile)
- Every button, link, and interactive element must be functional or clearly labeled
- Meta tags: charset, viewport, description, og:title, og:description
- Favicon: <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>◆</text></svg>">
- No placeholder text. No "Lorem ipsum". No "Coming soon" unless product is pre-launch.

The result must look like it was designed by a real product team, not generated. Every choice should feel intentional. Restraint and consistency over novelty.

Start the output with <!DOCTYPE html> immediately."""

    try:
        from backend.tools._llm import generate
        html = generate(prompt, model="claude")
        html = re.sub(r"^```html?\s*", "", html, flags=re.IGNORECASE | re.MULTILINE).strip().rstrip("`").strip()
        if html.startswith("<!"):
            return html
        logger.warning("LLM HTML didn't start with <!DOCTYPE — falling back to template")
    except Exception as e:
        logger.warning("LLM HTML generation failed (%s) — using template", e)

    # Fallback template
    icons = ["◆", "◈", "◉", "◎", "◇", "◊"]
    steps = ["Define your goal", "Astra builds it", "You launch"]

    props_cards = ""
    for i, prop in enumerate(value_props[:6]):
        icon = icons[i % len(icons)]
        props_cards += f"""
        <div class="feat">
          <div class="feat-icon">{icon}</div>
          <p class="feat-text">{prop}</p>
        </div>"""

    steps_html = ""
    for i, step in enumerate(steps, 1):
        steps_html += f"""
        <div class="step">
          <div class="step-num">{i:02d}</div>
          <p class="step-text">{step}</p>
        </div>"""

    year = 2025
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>{page_title}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    :root {{
      --bg: #06080f;
      --bg2: #0d1117;
      --bg3: #141b26;
      --line: rgba(148,163,200,.1);
      --line2: rgba(148,163,200,.18);
      --fg: #f0f4ff;
      --fg2: rgba(240,244,255,.6);
      --fg3: rgba(240,244,255,.35);
      --blue: #3b82f6;
      --blue2: #2563eb;
      --r: 12px;
    }}

    html {{ background: var(--bg); color: var(--fg); scroll-behavior: smooth; }}

    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      -webkit-font-smoothing: antialiased;
      min-height: 100vh;
    }}

    a {{ color: inherit; text-decoration: none; }}

    /* NAV */
    nav {{
      position: sticky; top: 0; z-index: 50;
      display: flex; align-items: center; justify-content: space-between;
      padding: 16px clamp(20px,5vw,64px);
      background: rgba(6,8,15,.88);
      backdrop-filter: blur(12px);
      border-bottom: 1px solid var(--line2);
    }}
    .nav-brand {{ font-weight: 700; font-size: 1rem; letter-spacing: -.01em; }}
    .nav-cta {{
      background: var(--blue); color: #fff;
      padding: 10px 22px; border-radius: 8px;
      font-size: .875rem; font-weight: 600;
      transition: background .15s;
    }}
    .nav-cta:hover {{ background: var(--blue2); }}

    /* HERO */
    .hero {{
      max-width: 860px; margin: 0 auto;
      padding: clamp(72px,10vw,120px) clamp(20px,5vw,48px) clamp(56px,8vw,96px);
      text-align: center;
    }}
    .hero-eyebrow {{
      display: inline-block;
      font-size: .75rem; font-weight: 500; letter-spacing: .18em; text-transform: uppercase;
      color: var(--blue); margin-bottom: 24px;
    }}
    .hero h1 {{
      font-size: clamp(2.4rem,6vw,4.5rem);
      font-weight: 800; line-height: 1.06; letter-spacing: -.03em;
      margin-bottom: 24px;
    }}
    .hero h1 em {{ font-style: normal; color: var(--fg2); }}
    .hero-sub {{
      font-size: clamp(1rem,1.8vw,1.2rem);
      line-height: 1.65; color: var(--fg2);
      max-width: 580px; margin: 0 auto 40px;
    }}
    .hero-actions {{ display: flex; gap: 12px; justify-content: center; flex-wrap: wrap; }}
    .btn-primary {{
      display: inline-flex; align-items: center; gap: 8px;
      background: var(--blue); color: #fff;
      padding: 14px 28px; border-radius: 8px;
      font-size: 1rem; font-weight: 600;
      transition: background .15s, transform .15s;
    }}
    .btn-primary:hover {{ background: var(--blue2); transform: translateY(-1px); }}
    .btn-ghost {{
      display: inline-flex; align-items: center;
      padding: 14px 28px; border-radius: 8px;
      border: 1px solid var(--line2);
      font-size: 1rem; color: var(--fg2);
      transition: border-color .15s, color .15s;
    }}
    .btn-ghost:hover {{ border-color: var(--fg2); color: var(--fg); }}

    /* STATS */
    .stats {{
      display: flex; justify-content: center; gap: 0;
      border-top: 1px solid var(--line2); border-bottom: 1px solid var(--line2);
      background: var(--bg2);
    }}
    .stat {{
      flex: 1; max-width: 220px;
      padding: 32px 24px; text-align: center;
      border-right: 1px solid var(--line2);
    }}
    .stat:last-child {{ border-right: none; }}
    .stat-val {{ font-size: 2rem; font-weight: 800; letter-spacing: -.03em; }}
    .stat-label {{ font-size: .8rem; color: var(--fg3); margin-top: 4px; letter-spacing: .08em; text-transform: uppercase; }}

    /* FEATURES */
    .section {{ padding: clamp(56px,8vw,96px) clamp(20px,5vw,64px); max-width: 1120px; margin: 0 auto; }}
    .section-label {{ font-size: .75rem; font-weight: 500; letter-spacing: .18em; text-transform: uppercase; color: var(--blue); margin-bottom: 16px; }}
    .section-title {{ font-size: clamp(1.6rem,3.5vw,2.6rem); font-weight: 800; letter-spacing: -.025em; margin-bottom: 48px; }}

    .feats {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }}
    .feat {{
      background: var(--bg2); border: 1px solid var(--line2);
      border-radius: var(--r); padding: 28px 24px;
      transition: border-color .2s;
    }}
    .feat:hover {{ border-color: rgba(59,130,246,.4); }}
    .feat-icon {{ font-size: 1.4rem; color: var(--blue); margin-bottom: 16px; }}
    .feat-text {{ font-size: .95rem; line-height: 1.6; color: var(--fg2); }}

    /* HOW IT WORKS */
    .how {{ background: var(--bg2); border-top: 1px solid var(--line2); border-bottom: 1px solid var(--line2); }}
    .steps {{ display: flex; gap: 0; }}
    .step {{
      flex: 1; padding: 40px 32px;
      border-right: 1px solid var(--line2);
      text-align: center;
    }}
    .step:last-child {{ border-right: none; }}
    .step-num {{
      font-size: 2.5rem; font-weight: 900; letter-spacing: -.04em;
      color: var(--blue); opacity: .6; margin-bottom: 12px;
    }}
    .step-text {{ font-size: .95rem; color: var(--fg2); line-height: 1.5; }}

    /* CTA BANNER */
    .cta-section {{
      text-align: center;
      padding: clamp(64px,10vw,112px) clamp(20px,5vw,64px);
    }}
    .cta-section h2 {{
      font-size: clamp(1.8rem,4vw,3rem);
      font-weight: 800; letter-spacing: -.03em; margin-bottom: 16px;
    }}
    .cta-section p {{ font-size: 1.1rem; color: var(--fg2); margin-bottom: 36px; }}

    /* FOOTER */
    footer {{
      border-top: 1px solid var(--line2);
      padding: 32px clamp(20px,5vw,64px);
      display: flex; align-items: center; justify-content: space-between;
      flex-wrap: wrap; gap: 12px;
    }}
    footer span {{ font-size: .85rem; color: var(--fg3); }}
    .footer-links {{ display: flex; gap: 24px; }}
    .footer-links a {{ font-size: .85rem; color: var(--fg3); transition: color .15s; }}
    .footer-links a:hover {{ color: var(--fg); }}

    @media (max-width: 640px) {{
      .stats {{ flex-wrap: wrap; }}
      .stat {{ max-width: 50%; border-bottom: 1px solid var(--line2); }}
      .steps {{ flex-direction: column; }}
      .step {{ border-right: none; border-bottom: 1px solid var(--line2); }}
      .step:last-child {{ border-bottom: none; }}
      footer {{ flex-direction: column; text-align: center; }}
    }}
  </style>
</head>
<body>

  <nav>
    <span class="nav-brand">{name}</span>
    <a href="{cta_url}" class="nav-cta">{cta_text}</a>
  </nav>

  <section class="hero">
    <span class="hero-eyebrow">Introducing {name}</span>
    <h1>{headline}</h1>
    <p class="hero-sub">{subheadline}</p>
    <div class="hero-actions">
      <a href="{cta_url}" class="btn-primary">{cta_text} &rarr;</a>
      <a href="#features" class="btn-ghost">See how it works</a>
    </div>
  </section>

  <div class="stats">
    <div class="stat"><div class="stat-val">6</div><div class="stat-label">AI Agents</div></div>
    <div class="stat"><div class="stat-val">72h</div><div class="stat-label">To first launch</div></div>
    <div class="stat"><div class="stat-val">1</div><div class="stat-label">Instruction to start</div></div>
  </div>

  <div id="features" class="section">
    <div class="section-label">What you get</div>
    <div class="section-title">Everything you need to launch faster</div>
    <div class="feats">{props_cards}
    </div>
  </div>

  <div class="how">
    <div class="section">
      <div class="section-label">How it works</div>
      <div class="section-title">Three steps to your product</div>
      <div class="steps">{steps_html}
      </div>
    </div>
  </div>

  <div class="cta-section">
    <h2>Ready to build?</h2>
    <p>Join founders who are launching faster with {name}.</p>
    <a href="{cta_url}" class="btn-primary">{cta_text} &rarr;</a>
  </div>

  <footer>
    <span>&copy; {year} {name}. All rights reserved.</span>
    <div class="footer-links">
      <a href="#">Privacy</a>
      <a href="#">Terms</a>
      <a href="#">Contact</a>
    </div>
  </footer>

</body>
</html>"""
