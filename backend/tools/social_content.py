"""
Social content tool — generates platform-optimized content packages via LLM.
Actual posting requires founder OAuth tokens.
When tokens are present in settings, posts immediately. Otherwise queues for founder review.
"""
import logging
import requests

from backend.config import settings

logger = logging.getLogger(__name__)


def _llm_generate(prompt: str, max_tokens: int = 1500) -> str:
    try:
        from backend.tools._llm import generate
        return generate(prompt, max_tokens=max_tokens)
    except Exception as e:
        logger.warning("LLM social content generation failed: %s", e)
        return ""


def generate_reel_package(
    company_name: str,
    headline: str,
    value_prop: str,
    target_audience: str,
    tone: str = "professional",
) -> dict:
    """Generate Instagram Reel content package. Args: company_name, headline, value_prop, target_audience, tone (optional, default 'professional')."""
    prompt = f"""Write an Instagram Reel script and caption for {company_name}.

Product/value proposition: {value_prop}
Target audience: {target_audience}
Headline: {headline}
Tone: {tone}

Output EXACTLY this format:
SCRIPT:
[0-3s] <hook line that stops scrolling>
[3-8s] <agitate the problem they face>
[8-20s] <demo/explain how {company_name} solves it with specific details>
[20-27s] <real result or transformation>
[27-30s] <CTA>

CAPTION:
<3-5 line caption that adds context, uses emojis, ends with CTA>

HASHTAGS:
<15 relevant hashtags>

VISUAL_NOTES:
<specific shot-by-shot visual direction>"""

    raw = _llm_generate(prompt, max_tokens=800)

    script, caption, hashtags, visual = _parse_social_sections(
        raw,
        fallback_script=(
            f"Hook: '{headline}'\n"
            f"Problem: Most {target_audience} struggle with [pain point].\n"
            f"Solution: {company_name} -- {value_prop}\n"
            "CTA: Link in bio to try it free."
        ),
        fallback_caption=(
            f"{headline}\n\nIf you're a {target_audience}, this is for you.\n"
            f"We built {company_name} to {value_prop.lower()}.\n\n"
            "Drop a comment if this resonates. Link in bio for early access."
        ),
    )

    package = {
        "platform": "instagram_reel",
        "duration_seconds": 30,
        "script": script,
        "caption": caption,
        "hashtags": hashtags or f"#{company_name.lower().replace(' ', '')} #startuplife #buildinpublic #saas #founder",
        "visual_notes": visual,
        "posted": False,
    }

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
    """Generate TikTok video script. Args: company_name, hook (opening line), problem (pain point), solution (what product solves)."""
    prompt = f"""Write a punchy 30-second TikTok script for {company_name}.

Hook: {hook}
Problem it solves: {problem}
Solution: {solution}

Make it feel native to TikTok — fast cuts, relatable, trending format. Use pattern interrupts.
Include: [0-3s] hook, [3-8s] problem, [8-20s] solution demo with specifics, [20-28s] proof/result, [28-30s] CTA.
Also write a TikTok caption (under 150 chars) and 10 hashtags including #fyp.

Format:
SCRIPT:
<full timestamped script>

CAPTION:
<caption>

HASHTAGS:
<hashtags>"""

    raw = _llm_generate(prompt, max_tokens=700)
    script, caption, hashtags, _ = _parse_social_sections(
        raw,
        fallback_script=(
            f"[0-3s] {hook}\n"
            f"[3-8s] {problem}\n"
            f"[8-20s] {solution} with {company_name}\n"
            "[20-30s] Follow for more. Link in bio."
        ),
        fallback_caption=f"{hook} | {company_name}",
    )

    package = {
        "platform": "tiktok",
        "duration_seconds": 30,
        "script": script,
        "caption": caption,
        "hashtags": hashtags or f"#{company_name.lower().replace(' ', '')} #fyp #startup #saas",
        "posted": False,
        "note": "TikTok Content Posting API requires Business account approval. Content ready to post manually.",
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
    """Generate Meta ad copy. Args: company_name, headline, body (ad text), cta (call-to-action text), target_audience_description (string), budget_usd_per_day (float, optional)."""
    prompt = f"""Write high-converting Meta (Facebook/Instagram) ad copy for {company_name}.

Product/offer: {body}
Audience: {target_audience_description}
Desired CTA: {cta}

Write 3 variations of ad copy. Each variation should have:
- A scroll-stopping headline (under 40 chars)
- Primary text (2-3 sentences, conversational, addresses a pain point, creates urgency)
- A short description line

Format:
VARIATION 1:
Headline: <headline>
Primary text: <text>
Description: <description>

VARIATION 2:
...

VARIATION 3:
...

Then pick the best one and output:
BEST HEADLINE: <headline>
BEST PRIMARY TEXT: <primary text>"""

    raw = _llm_generate(prompt, max_tokens=900)

    best_headline = headline
    best_body = body
    if raw:
        for line in raw.splitlines():
            if line.upper().startswith("BEST HEADLINE:"):
                best_headline = line.split(":", 1)[1].strip() or headline
            elif line.upper().startswith("BEST PRIMARY TEXT:"):
                best_body = line.split(":", 1)[1].strip() or body

    ad_account_id = getattr(settings, "meta_ad_account_id", None)
    meta_token = getattr(settings, "meta_access_token", None)

    ad_spec = {
        "platform": "meta_ads",
        "ad_name": f"{company_name} -- {best_headline[:40]}",
        "headline": best_headline,
        "body": best_body,
        "all_variations_raw": raw[:2000] if raw else "",
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
            ad_spec["note"] = f"META_AD_ACCOUNT_ID / META_ACCESS_TOKEN set but creation failed: {e}"
    else:
        ad_spec["note"] = "Set META_AD_ACCOUNT_ID and META_ACCESS_TOKEN to auto-create ads."

    return ad_spec


def _parse_social_sections(
    raw: str,
    fallback_script: str = "",
    fallback_caption: str = "",
) -> tuple[str, str, str, str]:
    """Parse LLM output into (script, caption, hashtags, visual_notes)."""
    if not raw:
        return fallback_script, fallback_caption, "", ""

    sections = {"script": [], "caption": [], "hashtags": [], "visual_notes": [], "visual": []}
    current = None

    for line in raw.splitlines():
        key = line.strip().rstrip(":").lower().replace(" ", "_")
        if key in sections:
            current = key
            continue
        if current:
            sections[current].append(line)

    script = "\n".join(sections["script"]).strip() or fallback_script
    caption = "\n".join(sections["caption"]).strip() or fallback_caption
    hashtags = " ".join(sections["hashtags"]).strip()
    visual = "\n".join(sections["visual_notes"] + sections["visual"]).strip()
    return script, caption, hashtags, visual


def _post_instagram_reel(token: str, account_id: str, package: dict) -> dict:
    return {
        "posted": False,
        "note": "Instagram Reels require a video file URL. Generate video asset first, then auto-post.",
    }


def _create_meta_ad_draft(token: str, ad_account_id: str, spec: dict) -> dict:
    url = f"https://graph.facebook.com/v18.0/act_{ad_account_id}/ads"
    payload = {
        "name": spec["ad_name"],
        "status": "PAUSED",
        "access_token": token,
    }
    resp = requests.post(url, data=payload, timeout=10)
    if resp.ok:
        return {"posted": True, "meta_ad_id": resp.json().get("id"), "status": "PAUSED -- requires founder review"}
    return {"posted": False, "meta_error": resp.text}
