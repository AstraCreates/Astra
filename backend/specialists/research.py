"""Research specialist — web search, news, patent search."""
from backend.core.agent import Agent
from backend.tools.obsidian_logger import obsidian_log, obsidian_read, obsidian_append
from backend.tools.web_search import web_search, news_search
from backend.tools.patent_search import patent_search


def build_research_agent(**kwargs) -> Agent:
    return Agent(
        name="research",
        role=(
            "Start every session by calling obsidian_read with your agent name to load prior context. Use obsidian_append mid-run to record key decisions or findings. market research specialist. ALWAYS call web_search or news_search at least twice before calling done. "
            "Search for: (1) market size and competitors, (2) target industries and data sources. "
            "Never call done without tool results — your output must contain real search data. Before calling done, call obsidian_log with your agent name, the session_id from context, a one-paragraph summary, and your output dict."
        ),
        tools={
            "web_search": web_search,
            "news_search": news_search,
            "patent_search": patent_search,
                    "obsidian_log": obsidian_log,
            "obsidian_read": obsidian_read,
            "obsidian_append": obsidian_append,
        },
        **kwargs,
    )
