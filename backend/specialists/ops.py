"""Ops specialist — project coordination, fundraising, investor outreach, comms, scheduling."""
from backend.core.agent import Agent
from backend.tools.obsidian_logger import obsidian_log, obsidian_read, obsidian_append
from backend.tools.pdf_generator import generate_pdf
from backend.tools.composio_tools import (
    composio_gmail_send,
    composio_calendar_create_event,
    composio_notion_create_page,
    composio_linear_create_issue,
)


def build_ops_agent(**kwargs) -> Agent:
    return Agent(
        name="ops",
        role=(
            "Start every session by calling obsidian_read with your agent name to load prior context. Use obsidian_append mid-run to record key decisions or findings. operations specialist. Handle everything that keeps the company running day-to-day: "
            "project management, fundraising docs, investor outreach, team coordination, and scheduling. "
            "Responsibilities: "
            "(1) Project tracking — create Linear issues for action items, milestones, and blockers. "
            "(2) Fundraising — generate pitch decks, one-pagers, exec summaries, and investor update emails as PDFs. "
            "(3) Investor outreach — send personalized emails via composio_gmail_send. "
            "(4) Scheduling — book meetings, calls, and deadlines via composio_calendar_create_event. "
            "(5) Knowledge base — document decisions, SOPs, and OKRs in Notion via composio_notion_create_page. "
            "(6) Synthesis — when other agents finish, consolidate their outputs into an executive summary PDF. "
            "Always call at least one tool. Never just describe what should be done — do it. Before calling done, call obsidian_log with your agent name, the session_id from context, a one-paragraph summary, and your output dict."
        ),
        tools={
            "generate_pdf": generate_pdf,
            "composio_gmail_send": composio_gmail_send,
            "composio_calendar_create_event": composio_calendar_create_event,
            "composio_notion_create_page": composio_notion_create_page,
            "composio_linear_create_issue": composio_linear_create_issue,
                    "obsidian_log": obsidian_log,
            "obsidian_read": obsidian_read,
            "obsidian_append": obsidian_append,
        },
        **kwargs,
    )
