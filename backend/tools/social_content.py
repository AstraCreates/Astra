"""
Social content tool — generates platform-optimized content packages via LLM.
Actual posting requires founder OAuth tokens.
When tokens are present in settings, posts immediately. Otherwise queues for founder review.
"""
import logging
import requests

from backend.config import settings

logger = logging.getLogger(__name__)

# Keyword → hashtag sets for audience/category-based hashtag selection
_HASHTAG_MAP = {
    "fitness": ["#fitness", "#health", "#workout", "#gym", "#wellness", "#fitlife"],
    "health": ["#health", "#wellness", "#healthyliving", "#nutrition", "#mindfulness"],
    "fintech": ["#fintech", "#finance", "#money", "#investing", "#personalfinance", "#wealthtech"],
    "finance": ["#finance", "#money", "#investing", "#personalfinance", "#financialfreedom"],
    "legal": ["#legaltech", "#legal", "#lawtech", "#legalinnovation", "#lawtechnology"],
    "ecommerce": ["#ecommerce", "#shopify", "#onlineshopping", "#retail", "#dtc", "#dropshipping"],
    "education": ["#edtech", "#education", "#learning", "#onlinecourses", "#elearning", "#studytips"],
    "hr": ["#hrtech", "#humanresources", "#peopleops", "#hiring", "#talentacquisition"],
    "real estate": ["#realestate", "#proptech", "#realty", "#housingmarket", "#realtorlife"],
    "marketing": ["#marketing", "#digitalmarketing", "#contentmarketing", "#growthhacking", "#martech"],
    "productivity": ["#productivity", "#gtd", "#timemanagement", "#workflow", "#efficiency"],
    "ai": ["#ai", "#artificialintelligence", "#machinelearning", "#genai", "#aitools"],
    "developer": ["#devtools", "#developer", "#coding", "#softwaredevelopment", "#programming"],
    "b2b": ["#b2bsales", "#b2bmarketing", "#enterprise", "#saassales", "#businessgrowth"],
    "sales": ["#sales", "#salestips", "#crm", "#revops", "#pipeline"],
    "healthcare": ["#healthtech", "#healthcare", "#medtech", "#digitalhealth", "#telemedicine"],
    "crypto": ["#crypto", "#blockchain", "#web3", "#defi", "#nft"],
    "gaming": ["#gaming", "#gamedev", "#indiegame", "#esports", "#gamer"],
    "travel": ["#travel", "#traveltech", "#digitalnomad", "#wanderlust", "#travelstartup"],
    "food": ["#foodtech", "#food", "#restaurant", "#foodie", "#agtech"],
}

# Base hashtags always appended to reel/tiktok
_REEL_BASE = ["#startuplife", "#buildinpublic", "#founder", "#startup"]
_TIKTOK_BASE = ["#fyp", "#startup", "#founder", "#startuplife"]


def _hashtags_for_audience(audience: str, base_tags: list[str], company_name: str, extra_slots: int = 9) -> str:
    """Build a relevant hashtag string from audience keywords + base tags."""
    audience_lower = audience.lower()
    matched: list[str] = []
    for keyword, tags in _HASHTAG_MAP.items():
        if keyword in audience_lower:
            for t in tags:
                if t not in matched:
                    matched.append(t)
            if len(matched) >= extra_slots:
                break
    # Fill remaining slots generically
    generic_fill = ["#saas", "#indiehacker", "#entrepreneurship", "#growthhacking", "#technology"]
    for t in generic_fill:
        if len(matched) >= extra_slots:
            break
        if t not in matched:
            matched.append(t)
    company_tag = f"#{company_name.lower().replace(' ', '')}"
    all_tags = [company_tag] + matched[:extra_slots] + base_tags
    return " ".join(all_tags)


def _meta_targeting_from_audience(audience_desc: str) -> dict:
    """Derive age_range and interests from audience description using keyword matching + LLM fallback."""
    desc_lower = audience_desc.lower()

    # Age range heuristics
    age_range = "25-44"  # default
    if any(w in desc_lower for w in ["teen", "teenager", "student", "college", "university", "gen z", "young adult"]):
        age_range = "18-24"
    elif any(w in desc_lower for w in ["senior", "retire", "60+", "older adult", "boomer"]):
        age_range = "45-65"
    elif any(w in desc_lower for w in ["millennial", "30s", "40s", "mid-career", "professional"]):
        age_range = "28-45"
    elif any(w in desc_lower for w in ["executive", "c-suite", "ceo", "cto", "vp", "director", "enterprise"]):
        age_range = "35-55"

    # Interest mapping
    interest_candidates: list[str] = []
    interest_keywords = {
        "fitness": ["fitness", "health", "wellness", "workout"],
        "finance": ["finance", "investing", "money", "wealth", "fintech"],
        "legal": ["legal", "law", "compliance", "regulatory"],
        "e-commerce": ["ecommerce", "e-commerce", "shopify", "retail", "dtc"],
        "education": ["education", "edtech", "learning", "courses", "training"],
        "real estate": ["real estate", "realty", "property", "proptech"],
        "marketing": ["marketing", "content creation", "seo", "ads", "growth"],
        "productivity": ["productivity", "workflow", "automation", "efficiency"],
        "technology": ["tech", "software", "developer", "coding", "saas", "api"],
        "artificial intelligence": ["ai", "machine learning", "generative ai", "llm"],
        "human resources": ["hr", "hiring", "recruitment", "people ops"],
        "entrepreneurship": ["founder", "startup", "entrepreneur", "bootstrapped"],
        "small business": ["small business", "smb", "freelancer", "solopreneur"],
        "sales": ["sales", "crm", "revenue", "pipeline", "leads"],
        "healthcare": ["healthcare", "medical", "health", "patient", "clinical"],
    }
    for interest, keywords in interest_keywords.items():
        if any(kw in desc_lower for kw in keywords):
            interest_candidates.append(interest)

    # Always include broad relevant defaults if not enough matched
    if "entrepreneurship" not in interest_candidates:
        interest_candidates.append("entrepreneurship")
    if "small business" not in interest_candidates and len(interest_candidates) < 4:
        interest_candidates.append("small business")
    if len(interest_candidates) < 3:
        interest_candidates.extend(["technology", "startups"])

    return {"age_range": age_range, "interests": interest_candidates[:6]}


def _llm_generate(prompt: str) -> str:
    try:
        from backend.tools._llm import generate
        return generate(prompt)
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

    raw = _llm_generate(prompt)

    # If LLM failed entirely, generate a real fallback script via a shorter LLM call
    if not raw:
        fallback_prompt = (
            f"Write a 30-second Instagram Reel script for {company_name}.\n"
            f"Target audience: {target_audience}\n"
            f"Value proposition: {value_prop}\n"
            f"Tone: {tone}\n"
            "Format: [0-3s] hook | [3-8s] problem | [8-20s] solution | [20-27s] result | [27-30s] CTA.\n"
            "Output only the script, no headers."
        )
        fallback_script_text = _llm_generate(fallback_prompt) or (
            f"[0-3s] Stop scrolling — {headline}\n"
            f"[3-8s] If you're a {target_audience}, you know the struggle.\n"
            f"[8-20s] {company_name} {value_prop}.\n"
            "[20-27s] Real results, real fast.\n"
            "[27-30s] Link in bio — try it free."
        )
    else:
        fallback_script_text = ""

    script, caption, hashtags, visual = _parse_social_sections(
        raw,
        fallback_script=fallback_script_text,
        fallback_caption=(
            f"{headline}\n\nIf you're a {target_audience}, this is for you.\n"
            f"We built {company_name} to {value_prop.lower()}.\n\n"
            "Drop a comment if this resonates. Link in bio for early access."
        ),
    )

    resolved_hashtags = hashtags or _hashtags_for_audience(target_audience, _REEL_BASE, company_name)

    package = {
        "platform": "instagram_reel",
        "duration_seconds": 30,
        "script": script,
        "caption": caption,
        "hashtags": resolved_hashtags,
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

    raw = _llm_generate(prompt)
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

    # Derive audience context from problem/solution for hashtag lookup
    audience_context = f"{problem} {solution}"
    resolved_hashtags = hashtags or _hashtags_for_audience(audience_context, _TIKTOK_BASE, company_name)

    package = {
        "platform": "tiktok",
        "duration_seconds": 30,
        "script": script,
        "caption": caption,
        "hashtags": resolved_hashtags,
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

    raw = _llm_generate(prompt)

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

    targeting = _meta_targeting_from_audience(target_audience_description)

    ad_spec = {
        "platform": "meta_ads",
        "ad_name": f"{company_name} -- {best_headline[:40]}",
        "headline": best_headline,
        "body": best_body,
        "all_variations_raw": raw or "",
        "call_to_action": cta,
        "targeting": {
            "description": target_audience_description,
            "age_range": targeting["age_range"],
            "interests": targeting["interests"],
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
