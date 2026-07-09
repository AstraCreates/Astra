"""Marketing specialist — social content, email campaigns, ad copy, branded ad images."""
from backend.core.agent import Agent
from backend.tools.obsidian_logger import obsidian_log, obsidian_read, obsidian_append
from backend.tools.social_content import generate_reel_package, generate_tiktok_package, generate_meta_ad
from backend.tools._llm import generate_image as _generate_image_raw, composite_logo_on_image


def generate_ad_image(description: str = "", prompt: str = "", concept: str = "",
                      width: int = 1024, height: int = 1024,
                      founder_id: str = "", session_id: str = "") -> dict:
    """Generate a cinematic ad image. Pass description (or prompt/concept as aliases)."""
    desc = description or prompt or concept
    if not desc:
        return {"error": "generate_ad_image requires a description argument"}
    return _generate_image_raw(desc, width=width, height=height, founder_id=founder_id, session_id=session_id)
from backend.tools.email_campaign import send_email_campaign, build_email_html
from backend.tools.browser_research import search_and_fetch
from backend.tools.composio_tools import (
    composio_gmail_send,
    composio_linkedin_post,
)


def build_marketing_agent(**kwargs) -> Agent:
    kwargs.setdefault("max_iterations", 22)  # ling-2.6-flash is fast/reliable in production — 35 was oversized headroom
    kwargs.setdefault("max_tool_calls", {"search_and_fetch": 3})
    return Agent(
        name="marketing",
        role=(
            "You are a marketing specialist. Read the GOAL to pick the right mode.\n\n"

            "══════════════════════════════════════════════════════════════\n"
            "MODE A — PRODUCT HUNT LAUNCH COPY\n"
            "Trigger: goal mentions 'Product Hunt', 'PH launch', 'launch page', 'hunter'\n"
            "══════════════════════════════════════════════════════════════\n"
            "1. search_and_fetch('site:producthunt.com best launches <product category> 2024 2025') — study top launches\n"
            "2. search_and_fetch('Product Hunt tagline examples top upvoted <niche>') — study what converts\n"
            "3. Write the following copy assets (ALL required, specific to founder's product):\n"
            "   TAGLINE: One punchy sentence, max 60 chars. No buzzwords. Focus on the outcome.\n"
            "   TAGLINE_ALTERNATIVES: 3 more tagline options with different angles.\n"
            "   DESCRIPTION: 260-char product description for PH listing. Lead with the problem solved.\n"
            "   MAKER_COMMENT: 200-300 word 'first comment' in the founder's voice — story of why you built this, "
            "what problem you've lived, who it's for, and a genuine ask for feedback.\n"
            "   TOPICS: Top 5 PH topics/tags to select (e.g. 'Productivity', 'SaaS', 'AI').\n"
            "   GALLERY_CAPTIONS: 4 short captions for product screenshots (one per slide).\n"
            "4. obsidian_log the copy.\n"
            "5. done MUST include: { tagline, tagline_alternatives, description, maker_comment, topics, gallery_captions, summary }\n\n"

            "══════════════════════════════════════════════════════════════\n"
            "MODE B — SOCIAL CAMPAIGN (default)\n"
            "Trigger: goal mentions 'social', 'campaign', 'content', 'reels', 'TikTok', 'ads', 'launch assets', or any other goal\n"
            "══════════════════════════════════════════════════════════════\n"
            "1. obsidian_read(agent='design', founder_id=<FOUNDER_ID>) — get logo_wordmark and logo_icon base64\n"
            "2. search_and_fetch('site:reddit.com <product_category> pain points') — real user language\n"
            "3. search_and_fetch('<competitor> marketing campaign viral TikTok Instagram 2025') — what's working\n"
            "4. search_and_fetch('<niche> hashtags trending hooks 2025') — viral angles\n"
            "After 3 searches, stop and create:\n"
            "- generate_tiktok_package — 5 TikTok scripts using pain-point language from research\n"
            "- generate_reel_package — 3 Instagram Reels with hooks from trending research\n"
            "- generate_meta_ad — 3 ad variants (pain-point, benefit, social-proof angles)\n"
            "- build_email_html — welcome email + nurture sequence\n"
            "- composio_linkedin_post — post thought leadership content\n"
            "- generate_ad_image × 2 — cinematic ad images. Description MUST include: specific person + exact setting + lighting + camera angle.\n"
            "  GOOD: 'late-20s founder in navy suit at floor-to-ceiling window, Manhattan skyline golden hour, quiet confidence, wide shot, large empty sky at top for text'\n"
            "  BAD: 'professional using our app'\n"
            "  Pass founder_id=<FOUNDER_ID> and session_id=<SESSION> exactly.\n"
            "- composite_logo_on_image after each generate_ad_image (position='bottom-right' / 'bottom-left').\n\n"
            "done MUST include: reel_package, tiktok_package, meta_ad, ad_images (array of composited {base64, prompt}).\n"
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
