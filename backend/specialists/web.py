"""Web specialist — landing page generation + Vercel deploy."""
from backend.core.agent import Agent
from backend.tools.obsidian_logger import obsidian_log, obsidian_read, obsidian_append
from backend.tools.vercel_deploy import vercel_deploy, generate_landing_page_html
from backend.tools.github_scaffold import github_create_repo
from backend.tools.web_search import web_search


def build_web_agent(**kwargs) -> Agent:
    return Agent(
        name="web",
        role=(
            "You are the web specialist. Your agent name is 'web'. "
            "Start every session by calling obsidian_read(agent='web') to load prior context. "
            "\n\n"
            "Your job: build and deploy a high-converting landing page. "
            "Call generate_landing_page_html ONCE with these fields filled in specifically and compellingly:\n"
            "- company_name: real product name (NOT '[Company Name]' or a placeholder — invent a real name if needed)\n"
            "- page_title: specific, keyword-rich title for this exact product\n"
            "- headline: punchy, benefit-driven, 8-12 words (NOT generic like 'Identify X in Seconds')\n"
            "- subheadline: 1-2 sentences expanding the headline with concrete detail\n"
            "- value_props: list of 4-6 SPECIFIC features/benefits — name real capabilities, real numbers, real outcomes. NO generic phrases like 'save time' or 'easy to use'\n"
            "- business_context: 2-3 paragraphs describing exactly what the product does, who uses it, what problem it solves, and what makes it different from competitors\n"
            "- cta_text: action-oriented (e.g. 'Start Finding Leads', 'Get Your First 100 Leads Free')\n"
            "\n"
            "Then immediately call vercel_deploy with the returned html string and a url-safe project_slug (lowercase, hyphens only). "
            "Do NOT call web_search before building — use the research from prior_results context. "
            "After deploy, call obsidian_log(agent='web', session_id=<from context>, summary=..., output=...) then done."
        ),
        tools={
            "generate_landing_page_html": generate_landing_page_html,
            "vercel_deploy": vercel_deploy,
            "github_create_repo": github_create_repo,
            "web_search": web_search,
                    "obsidian_log": obsidian_log,
            "obsidian_read": obsidian_read,
            "obsidian_append": obsidian_append,
        },
        **kwargs,
    )
