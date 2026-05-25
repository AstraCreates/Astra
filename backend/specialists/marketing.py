"""Marketing specialist — social content, email campaigns, ad copy."""
from backend.core.agent import Agent
from backend.tools.obsidian_logger import obsidian_log, obsidian_read, obsidian_append
from backend.tools.social_content import generate_reel_package, generate_tiktok_package, generate_meta_ad
from backend.tools.email_campaign import send_email_campaign, build_email_html
from backend.tools.composio_tools import (
    composio_gmail_send,
    composio_linkedin_post,
)


def build_marketing_agent(**kwargs) -> Agent:
    return Agent(
        name="marketing",
        role="marketing specialist. Create and publish social content, email campaigns, and ads. Before calling done, call obsidian_log with your agent name, the session_id from context, a one-paragraph summary, and your output dict.",
        tools={
            "generate_reel_package": generate_reel_package,
            "generate_tiktok_package": generate_tiktok_package,
            "generate_meta_ad": generate_meta_ad,
            "build_email_html": build_email_html,
            "send_email_campaign": send_email_campaign,
            "composio_gmail_send": composio_gmail_send,
            "composio_linkedin_post": composio_linkedin_post,
                    "obsidian_log": obsidian_log,
            "obsidian_read": obsidian_read,
            "obsidian_append": obsidian_append,
        },
        **kwargs,
    )
