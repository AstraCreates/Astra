"""Web specialist — builds the Next.js marketing landing page AND creates the shared
GitHub repo that the technical agent then extends into the full product app."""
from backend.core.agent import Agent
from backend.tools.obsidian_logger import obsidian_log, obsidian_read, obsidian_append
from backend.tools.github_scaffold import github_create_repo
from backend.tools.git_tools import run_mvp_loop


def build_web_agent(**kwargs) -> Agent:
    # Wrap obsidian_read so it can only fire once per agent run
    _obsidian_read_done = {"done": False}

    def _obsidian_read_once(**kw):
        if _obsidian_read_done["done"]:
            return {"notes": [], "_blocked": "obsidian_read already called — proceed to build the landing NOW"}
        _obsidian_read_done["done"] = True
        return obsidian_read(**kw)

    return Agent(
        name="web",
        role=(
            "You are the web specialist. Build the MARKETING LANDING PAGE as a real Next.js app, "
            "and create the SHARED GitHub repo that the technical agent will later extend into the "
            "full product. COMPANY_NAME is in SHARED CONTEXT — use it as the brand everywhere.\n\n"
            "MANDATORY WORKFLOW — in order, no repetition:\n"
            "1. obsidian_read(agent='design') — fires ONCE. Extract colors/fonts/brand_vibe if present, "
            "then continue regardless.\n"
            "2. github_create_repo(repo_name=<kebab-case-COMPANY_NAME>, description=<one-line product desc>) "
            "— this is the SHARED repo the technical agent will build on. Keep the returned repo_url.\n"
            "3. run_mvp_loop(\n"
            "     repo_url=<url from step 2>,\n"
            "     goal='Marketing landing page for <COMPANY_NAME>: a polished, conversion-focused Next.js + "
            "Tailwind landing page — hero with a sharp headline and one-line value prop, 4-6 feature/benefit "
            "sections, social-proof framing, a pricing teaser, and a waitlist / sign-up CTA. Use the brand "
            "colors and fonts from the design spec. This is the PUBLIC marketing page, not the app.',\n"
            "     required_files=['package.json','next.config.js','tailwind.config.ts','app/layout.tsx',"
            "'app/globals.css','app/page.tsx','components/Hero.tsx','components/Features.tsx','components/CTA.tsx'],\n"
            "     session_id=<SESSION>,\n"
            "     context=<design colors/fonts + 2-3 sentence product summary>\n"
            "   ) — builds the Next.js landing, deploys it, and returns repo_url + deploy_url.\n"
            "4. obsidian_log — log the repo_url AND deploy_url clearly (the technical agent extends THIS repo).\n"
            "5. done — return {repo_url, deploy_url}.\n\n"
            "Build a REAL Next.js app (NOT plain HTML). The technical agent adds auth, dashboard, and product "
            "features on top of this same repo, so keep the structure clean and standard."
        ),
        tools={
            "github_create_repo": github_create_repo,
            "run_mvp_loop": run_mvp_loop,
            "obsidian_log": obsidian_log,
            "obsidian_read": _obsidian_read_once,
            "obsidian_append": obsidian_append,
        },
        **kwargs,
    )
