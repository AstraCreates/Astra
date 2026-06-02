"""Marketing specialist — social content, email campaigns, ad copy, branded ad images."""
from backend.core.agent import Agent
from backend.tools.obsidian_logger import obsidian_log, obsidian_read, obsidian_append
from backend.tools.social_content import generate_reel_package, generate_tiktok_package, generate_meta_ad
from backend.tools._llm import generate_image as generate_ad_image, composite_logo_on_image
from backend.tools.email_campaign import send_email_campaign, build_email_html
from backend.tools.browser_research import search_and_fetch
from backend.tools.composio_tools import (
    composio_gmail_send,
    composio_linkedin_post,
)


def build_marketing_agent(**kwargs) -> Agent:
    kwargs.setdefault("max_iterations", 20)
    kwargs.setdefault("max_tool_calls", {"search_and_fetch": 3})
    return Agent(
        name="marketing",
        role=(
            "You are a marketing specialist. Research trends then create campaigns grounded in real data.\n\n"
            "WORKFLOW:\n"
            "1. obsidian_read(agent='design', founder_id=<FOUNDER_ID>) — get logo_wordmark and logo_icon base64 from design agent output\n"
            "2. search_and_fetch('site:reddit.com <product_category> pain points') — real user language\n"
            "3. search_and_fetch('<competitor> marketing campaign viral TikTok Instagram 2025') — what's working\n"
            "4. search_and_fetch('<niche> hashtags trending hooks 2025') — viral angles\n"
            "After 3 searches, stop and move to content creation.\n\n"
            "THEN CREATE (ALL REQUIRED):\n"
            "- generate_tiktok_package — 5 TikTok scripts using exact pain-point language from research\n"
            "- generate_reel_package — 3 Instagram Reels with hooks from trending research\n"
            "- generate_meta_ad — 3 ad variants (pain-point, benefit, social-proof angles)\n"
            "- build_email_html — welcome email + nurture sequence\n"
            "- composio_linkedin_post — post thought leadership content\n"
            "- generate_ad_image — Generate 2 cinematic ad images. Description MUST include: specific person + exact setting + lighting + camera angle.\n"
            "  GOOD: 'late-20s founder in navy suit at floor-to-ceiling window, Manhattan skyline golden hour, quiet confidence, wide shot, large empty sky at top for text'\n"
            "  BAD: 'professional using our app'\n"
            "  Pass founder_id=<FOUNDER_ID> and session_id=<SESSION> exactly.\n"
            "- composite_logo_on_image — REQUIRED after each generate_ad_image. Takes the ad image base64 and the logo_wordmark base64 from design, composites the logo onto the ad.\n"
            "  Use position='bottom-right' for the first ad, position='bottom-left' for the second.\n"
            "  The composited image is your final ad creative — use its base64 in your output.\n\n"
            "Your final done output MUST include reel_package, tiktok_package, meta_ad, and ad_images (array of composited {base64, prompt}).\n"
            "Call obsidian_log then done."
        ),
        tools={
            "search_and_fetch": search_and_fetch,
            "generate_reel_package": generate_reel_package,
            "generate_tiktok_package": generate_tiktok_package,
            "generate_meta_ad": generate_meta_ad,
            "generate_ad_image": generate_ad_image,
            "composite_logo_on_image": composite_logo_on_image,
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
