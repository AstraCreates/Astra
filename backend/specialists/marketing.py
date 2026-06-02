"""Marketing specialist — social content, email campaigns, ad copy."""
from backend.core.agent import Agent
from backend.tools.obsidian_logger import obsidian_log, obsidian_read, obsidian_append
from backend.tools.social_content import generate_reel_package, generate_tiktok_package, generate_meta_ad
from backend.tools._llm import generate_image as generate_ad_image
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
            "RESEARCH FIRST — call search_and_fetch EXACTLY 3 times (no more), then move on:\n"
            "1. search_and_fetch('site:reddit.com <product_category> <target_audience> pain points') — real user language\n"
            "2. search_and_fetch('<competitor> marketing campaign viral TikTok Instagram 2025') — what's working\n"
            "3. search_and_fetch('<niche> hashtags trending hooks 2025') — viral angles\n"
            "After 3 searches, you MUST stop searching and move to content creation immediately.\n\n"
            "THEN CREATE (ALL of these are REQUIRED — do not skip any):\n"
            "- generate_tiktok_package — 5 TikTok scripts using exact pain-point language from research\n"
            "- generate_reel_package — 3 Instagram Reels with hooks from trending research\n"
            "- generate_meta_ad — 3 ad variants (pain-point, benefit, social-proof angles)\n"
            "- build_email_html — welcome email + nurture sequence\n"
            "- composio_linkedin_post — post thought leadership content\n"
            "- generate_ad_image — REQUIRED. Generate 2 ad images with SPECIFIC, CINEMATIC descriptions.\n"
            "  GOOD description: 'late-20s founder, sharp navy suit, standing at floor-to-ceiling window overlooking Manhattan at golden hour, holding phone, expression of quiet confidence, wide shot with large empty sky at top for text overlay'\n"
            "  BAD description: 'professional using our app' or 'person at desk'\n"
            "  The description must include: person/subject details, exact setting (city/place/time of day), lighting, camera angle, emotional tone.\n"
            "  Pass founder_id=<FOUNDER_ID value> and session_id=<SESSION value> exactly as shown above.\n\n"
            "All copy must use specific language from real user complaints found in research. "
            "No generic templates. "
            "Your final done output MUST include reel_package, tiktok_package, meta_ad, and ad_images (array of {url|base64,prompt}) for preview rendering. "
            "Call obsidian_log then done."
        ),
        tools={
            "search_and_fetch": search_and_fetch,
            "generate_reel_package": generate_reel_package,
            "generate_tiktok_package": generate_tiktok_package,
            "generate_meta_ad": generate_meta_ad,
            "generate_ad_image": generate_ad_image,
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
