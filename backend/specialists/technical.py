"""Technical specialist — GitHub repos, issues, PRs, Linear, Notion."""
from backend.core.agent import Agent
from backend.tools.obsidian_logger import obsidian_log, obsidian_read, obsidian_append
from backend.tools.github_scaffold import github_create_repo
from backend.tools.composio_tools import (
    composio_github_create_pr,
    composio_github_create_issue,
    composio_linear_create_issue,
    composio_notion_create_page,
    composio_calendar_create_event,
)


def build_technical_agent(**kwargs) -> Agent:
    return Agent(
        name="technical",
        role=(
            "Start every session by calling obsidian_read with your agent name to load prior context. Use obsidian_append mid-run to record key decisions or findings. technical specialist. Scaffold code infrastructure, manage GitHub, Linear, and Notion. "
            "For composio_github_create_issue and composio_github_create_pr: pass only repo name (not owner/repo), "
            "omit owner — it is auto-resolved from the GitHub connection. "
            "For composio_linear_create_issue: do NOT pass team_id — it is fetched automatically. Before calling done, call obsidian_log with your agent name, the session_id from context, a one-paragraph summary, and your output dict."
        ),
        tools={
            "github_create_repo": github_create_repo,
            "composio_github_create_pr": composio_github_create_pr,
            "composio_github_create_issue": composio_github_create_issue,
            "composio_linear_create_issue": composio_linear_create_issue,
            "composio_notion_create_page": composio_notion_create_page,
            "composio_calendar_create_event": composio_calendar_create_event,
                    "obsidian_log": obsidian_log,
            "obsidian_read": obsidian_read,
            "obsidian_append": obsidian_append,
        },
        **kwargs,
    )
