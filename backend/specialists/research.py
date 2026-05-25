"""Research specialist — web search, news, patent search."""
from backend.core.agent import Agent
from backend.tools.obsidian_logger import obsidian_log, obsidian_read, obsidian_append
from backend.tools.web_search import web_search, news_search
from backend.tools.patent_search import patent_search


def build_research_agent(**kwargs) -> Agent:
    return Agent(
        name="research",
        role=(
            "You are the research specialist. Your agent name is 'research'. "
            "Start every session by calling obsidian_read(agent='research') to load prior context. "
            "Use obsidian_append(agent='research', ...) mid-run to record key decisions or findings. "
            "Call web_search or news_search 2-3 times max. Do NOT keep searching beyond that. "
            "Search for: (1) market size and competitors, (2) target industries and data sources. "
            "After 2-3 searches, call obsidian_log(agent='research', ...) then immediately call done. "
            "Never call done without tool results — your output must contain real search data."
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
