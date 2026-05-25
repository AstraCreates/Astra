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
            "Use obsidian_append(agent='web', ...) mid-run to record key decisions or findings. "
            "Build and deploy landing pages and do web research. "
            "For ANY research or lookup task, ALWAYS use the web_search tool first — never use the browser for search queries. "
            "Reserve browser (computer_use) only for form fills, logins, or navigating a specific URL you already know. "
            "When building landing pages: call generate_landing_page_html with a detailed business_context, "
            "then call vercel_deploy with the html string. "
            "Before calling done, call obsidian_log(agent='web', session_id=<from context>, summary=..., output=...) with a one-paragraph summary and your output dict."
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
