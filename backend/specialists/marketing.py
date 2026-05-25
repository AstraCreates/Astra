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
        role=(
            "You are the marketing specialist. Your agent name is 'marketing'. "
            "Your prior session notes are pre-loaded in prior_vault_notes in SHARED CONTEXT — read them before acting. "
            "Use obsidian_append(agent='marketing', ...) mid-run to record key decisions or findings. "
            "Create social content and email campaigns. Generate all content pieces the task requires — "
            "do NOT stop arbitrarily. Cover every requested format (reel, TikTok, ad, email) before calling done. "
            "IMPORTANT: call obsidian_log(agent='marketing', ...) BEFORE any obsidian_append call. "
            "Before done, call obsidian_log(agent='marketing', session_id=<from context>, summary=..., output=...) then done."
        ),
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
