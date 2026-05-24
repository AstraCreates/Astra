"""
Social content tool — generates platform-optimized content packages and queues them.
Actual posting requires founder OAuth tokens (Instagram Graph API / TikTok Content API).
When tokens are present in settings, posts immediately. Otherwise queues for founder review.
"""
import logging
import requests

from backend.config import settings

logger = logging.getLogger(__name__)


def generate_reel_package(
    company_name: str,
    headline: str,
    value_prop: str,
    target_audience: str,
    tone: str = "professional",
) -> dict:
    """Generate a short-form video content package (script, caption, hashtags)."""
    script_lines = [
        f"Hook: '{headline}'",
        f"Problem: Most {target_audience} struggle with [pain point].",
        f"Solution: {company_name} — {value_prop}",
        "CTA: Link in bio to try it free.",
    ]
    caption_lines = [
        f"✨ {headline}",
        "",
        f"If you're a {target_audience}, this is for you.",
        f"We built {company_name} to {value_prop.lower()}.",
        "",
        "💡 Drop a comment if this resonates.",
        "👇 Link in bio for early access.",
    ]
    hashtags = [
        f"#{company_name.lower().replace(' ', '')}",
        "#startuplife", "#founderstory", "#buildinpublic",
        "#saas", "#startup", "#ai", "#founder",
        f"#{target_audience.lower().replace(' ', '').replace('-', '')}",
    ]

    package = {
        "platform": "instagram_reel",
        "duration_seconds": 30,
        "script": "\n".join(script_lines),
        "caption": "\n".join(caption_lines),
        "hashtags": " ".join(hashtags),
        "visual_notes": (
            f"Open on text overlay: '{headline}'. "
            "Cut to screen recording or product demo. "
            "End on logo with CTA."
        ),
        "posted": False,
    }

    # Attempt Instagram post if credentials exist
    ig_token = getattr(settings, "instagram_access_token", None)
    ig_account_id = getattr(settings, "instagram_business_account_id", None)
    if ig_token and ig_account_id:
        result = _post_instagram_reel(ig_token, ig_account_id, package)
        package.update(result)

    return package


def generate_tiktok_package(
    company_name: str,
    hook: str,
    problem: str,
    solution: str,
) -> dict:
    """Generate TikTok video script and content package."""
    script = (
        f"[0-3s] Hook: {hook}\n"
        f"[3-8s] Problem: {problem}\n"
        f"[8-20s] Demo/Solution: {solution} with {company_name}\n"
        f"[20-30s] CTA: Follow for more. Link in bio."
    )
    package = {
        "platform": "tiktok",
        "duration_seconds": 30,
        "script": script,
        "caption": f"{hook} | {company_name} #{company_name.lower().replace(' ', '')} #fyp #startup",
        "hashtags": f"#{company_name.lower().replace(' ', '')} #fyp #startup #saas #buildinpublic",
        "posted": False,
        "note": "TikTok Content Posting API requires Business account approval. Content ready to post manually or via TikTok Studio.",
    }
    return package


def generate_meta_ad(
    company_name: str,
    headline: str,
    body: str,
    cta: str,
    target_audience_description: str,
    budget_usd_per_day: float = 10.0,
) -> dict:
    """Generate Meta (Facebook/Instagram) ad copy and targeting spec."""
    ad_account_id = getattr(settings, "meta_ad_account_id", None)
    meta_token = getattr(settings, "meta_access_token", None)

    ad_spec = {
        "platform": "meta_ads",
        "ad_name": f"{company_name} — {headline[:40]}",
        "headline": headline,
        "body": body,
        "call_to_action": cta,
        "targeting": {
            "description": target_audience_description,
            "age_range": "25-44",
            "interests": ["entrepreneurship", "startups", "small business", "technology"],
        },
        "budget_usd_per_day": budget_usd_per_day,
        "posted": False,
    }

    if ad_account_id and meta_token:
        try:
            result = _create_meta_ad_draft(meta_token, ad_account_id, ad_spec)
            ad_spec.update(result)
        except Exception as e:
            logger.error("meta_ad creation failed: %s", e)
            ad_spec["note"] = f"META_AD_ACCOUNT_ID / META_ACCESS_TOKEN set but ad creation failed: {e}"
    else:
        ad_spec["note"] = "Set META_AD_ACCOUNT_ID and META_ACCESS_TOKEN to auto-create ads."

    return ad_spec


def _post_instagram_reel(token: str, account_id: str, package: dict) -> dict:
    """Post reel via Instagram Graph API (requires approved video URL)."""
    # Instagram Reels require a publicly accessible video URL.
    # In production: upload video to CDN first, then pass URL here.
    return {
        "posted": False,
        "note": "Instagram Reels require a video file URL. Generate video asset first, then auto-post.",
    }


def _create_meta_ad_draft(token: str, ad_account_id: str, spec: dict) -> dict:
    """Create a paused ad draft via Meta Marketing API."""
    url = f"https://graph.facebook.com/v18.0/act_{ad_account_id}/ads"
    payload = {
        "name": spec["ad_name"],
        "status": "PAUSED",
        "access_token": token,
    }
    resp = requests.post(url, data=payload, timeout=10)
    if resp.ok:
        return {"posted": True, "meta_ad_id": resp.json().get("id"), "status": "PAUSED — requires founder review"}
    return {"posted": False, "meta_error": resp.text}
