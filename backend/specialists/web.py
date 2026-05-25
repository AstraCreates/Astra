"""Web specialist — landing page, Vercel deploy, Cloudflare DNS, PostHog, Clarity."""
from backend.core.agent import Agent
from backend.tools.obsidian_logger import obsidian_log, obsidian_read, obsidian_append
from backend.tools.vercel_deploy import vercel_deploy, vercel_deploy_from_github, generate_landing_page_html
from backend.tools.github_scaffold import github_create_repo
from backend.tools.web_search import web_search
from backend.tools.cloudflare_tools import cloudflare_setup_vercel_domain, cloudflare_generate_instructions
from backend.tools.posthog_tools import posthog_generate_integration
from backend.tools.clarity_tools import clarity_generate_integration


def build_web_agent(**kwargs) -> Agent:
    return Agent(
        name="web",
        role=(
            "You are the web specialist. Your agent name is 'web'. "
            "Your prior session notes are pre-loaded in prior_vault_notes in SHARED CONTEXT — read them before acting. "
            "Build and deploy a high-converting landing page. WORKFLOW:\n"
            "(1) generate_landing_page_html — use specific, compelling copy from research context. "
            "Fields: company_name, page_title, headline (punchy, 8-12 words), subheadline, "
            "value_props (4-6 specific features with real numbers), business_context, cta_text.\n"
            "(2) vercel_deploy — deploy with url-safe project_slug.\n"
            "(3) posthog_generate_integration — add analytics snippet to include in handoff.\n"
            "(4) clarity_generate_integration — add session recording snippet.\n"
            "(5) cloudflare_setup_vercel_domain — wire DNS if custom domain provided.\n"
            "(6) obsidian_log then done.\n"
            "Do NOT call web_search before building — use research from prior_results."
        ),
        tools={
            "generate_landing_page_html": generate_landing_page_html,
            "vercel_deploy": vercel_deploy,
            "vercel_deploy_from_github": vercel_deploy_from_github,
            "github_create_repo": github_create_repo,
            "web_search": web_search,
            "cloudflare_setup_vercel_domain": cloudflare_setup_vercel_domain,
            "cloudflare_generate_instructions": cloudflare_generate_instructions,
            "posthog_generate_integration": posthog_generate_integration,
            "clarity_generate_integration": clarity_generate_integration,
            "obsidian_log": obsidian_log,
            "obsidian_read": obsidian_read,
            "obsidian_append": obsidian_append,
        },
        **kwargs,
    )
