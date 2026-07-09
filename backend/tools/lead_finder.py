"""Lead discovery — find target leads via web search + enrichment."""
import json
import logging
import re
from typing import Optional

from backend.tools.web_search import web_search
from backend.tools._llm import generate

logger = logging.getLogger(__name__)


_SOCIAL_DOMAINS = {"linkedin.com", "twitter.com", "x.com", "facebook.com", "instagram.com", "tiktok.com"}


def find_leads(
    industry: str = "",
    job_title: str = "owner",
    location: str = "",
    company_size: str = "",
    max_results: int = 10,
    no_website: bool = False,
) -> dict:
    """
    Search for potential leads matching criteria. Returns enriched contact list.
    Set no_website=True to target businesses that likely lack their own website (searches Yelp/GMaps listings).
    """
    if not industry:
        # Real production bug: models called find_leads() with no industry,
        # hitting a raw TypeError repeatedly with zero corrective signal —
        # a structured error the model can actually read and fix beats a
        # crash it can only blindly retry.
        return {"error": "find_leads requires 'industry' (e.g. find_leads(industry='restaurant', job_title='owner', max_results=10))"}
    try:
        max_results = int(max_results)
    except (TypeError, ValueError):
        max_results = 10
    if no_website:
        # Search local directory listings — these surface businesses without dedicated sites
        query_parts = [f'site:yelp.com OR site:maps.google.com "{industry}"']
        if location:
            query_parts.append(location)
        query = " ".join(query_parts)
    else:
        query_parts = [f"{job_title} {industry}"]
        if location:
            query_parts.append(location)
        if company_size:
            query_parts.append(f"{company_size} company")
        query_parts.append("contact email")
        query = " ".join(query_parts)

    try:
        raw = web_search(query=query, max_results=max_results + 4)
        results = [r for r in raw.get("results", [])
                   if not any(d in r.get("url", "") for d in _SOCIAL_DOMAINS)]

        leads = []
        for r in results:
            lead = {
                "name": _extract_name(r.get("title", "")),
                "company": _extract_company(r.get("title", ""), r.get("url", "")),
                "title": job_title,
                "url": r.get("url", ""),
                "snippet": r.get("snippet", "")[:200],
                "source": "web_search",
            }
            if lead["company"] or lead["url"]:
                leads.append(lead)

        return {
            "leads": leads[:max_results],
            "count": len(leads),
            "query": query,
            "industry": industry,
            "job_title": job_title,
        }
    except Exception as e:
        logger.error("find_leads failed: %s", e)
        return {"error": str(e), "leads": []}


def enrich_lead(
    company_name: str,
    website: str = "",
) -> dict:
    """
    Enrich a lead with company info: size, funding, tech stack, contacts.
    """
    query = f"{company_name} company size funding employees"
    if website:
        query += f" site:{website}"

    try:
        raw = web_search(query=query, max_results=5)
        results = raw.get("results", [])
        snippets = [r.get("snippet", "") for r in results]

        enriched = {
            "company": company_name,
            "website": website,
            "signals": snippets[:3],
            "funding_signals": [s for s in snippets if any(w in s.lower() for w in ["raised", "series", "funding", "million", "seed"])],
            "size_signals": [s for s in snippets if any(w in s.lower() for w in ["employees", "team", "people", "staff"])],
        }

        # Estimate company stage
        text_all = " ".join(snippets).lower()
        if any(w in text_all for w in ["series b", "series c", "ipo", "public"]):
            enriched["stage"] = "growth"
        elif any(w in text_all for w in ["series a", "raised $"]):
            enriched["stage"] = "early_growth"
        elif any(w in text_all for w in ["seed", "pre-seed", "bootstrapped", "early"]):
            enriched["stage"] = "early"
        else:
            enriched["stage"] = "unknown"

        return enriched
    except Exception as e:
        logger.error("enrich_lead failed: %s", e)
        return {"error": str(e), "company": company_name}


def build_outreach_sequence(
    product_name: str,
    value_prop: str,
    lead_name: str,
    lead_company: str,
    lead_title: str,
    sequence_length: int = 3,
) -> dict:
    """
    Generate a multi-touch cold outreach email sequence for a lead.
    Returns list of emails with subject, body, and send_day.
    """
    try:
        sequence_length = int(sequence_length)
    except (TypeError, ValueError):
        sequence_length = 3
    _SEND_DAYS = [1, 4, 10]
    _TYPES = ["intro", "follow_up_1", "break_up"]

    # Try LLM-generated personalized emails first
    try:
        pain = _pain_point(lead_title)
        prompt = (
            f"You are a B2B sales copywriter. Write {sequence_length} cold outreach emails for the following lead.\n\n"
            f"Lead name: {lead_name}\n"
            f"Lead title: {lead_title}\n"
            f"Lead company: {lead_company}\n"
            f"Product: {product_name}\n"
            f"Value proposition: {value_prop}\n"
            f"Primary pain point for this role: {pain}\n\n"
            f"Rules:\n"
            f"- Email 1: problem-focused intro, reference their role specifically, end with a soft ask for 15 min\n"
            f"- Email 2 (if requested): brief follow-up, mention a concrete benefit or outcome\n"
            f"- Email 3 (if requested): short break-up email, leave door open\n"
            f"- Keep each body under 120 words, plain text, conversational, no marketing fluff\n"
            f"- Do NOT sign off with a name — end with 'Best,'\n\n"
            f"Return ONLY a JSON array of {sequence_length} objects: "
            f'[{{"subject": "...", "body": "..."}}, ...]'
        )
        raw = generate(prompt, model="fast", json_mode=False, temperature=0.7)
        # Extract JSON array from response
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            raise ValueError("No JSON array found in LLM response")
        llm_emails = json.loads(match.group(0))
        if not isinstance(llm_emails, list) or len(llm_emails) < sequence_length:
            raise ValueError("LLM returned wrong number of emails")

        emails = []
        for i in range(sequence_length):
            emails.append({
                "send_day": _SEND_DAYS[i] if i < len(_SEND_DAYS) else _SEND_DAYS[-1] + (i - len(_SEND_DAYS) + 1) * 7,
                "subject": llm_emails[i].get("subject", f"{product_name} for {lead_company}"),
                "body": llm_emails[i].get("body", ""),
                "type": _TYPES[i] if i < len(_TYPES) else f"follow_up_{i}",
            })

    except Exception as e:
        logger.warning("build_outreach_sequence LLM failed, using templates: %s", e)
        # Fallback to template strings
        emails = []
        pain = _pain_point(lead_title)

        emails.append({
            "send_day": 1,
            "subject": f"Quick question about {lead_company}'s {pain}",
            "body": (
                f"Hi {lead_name},\n\n"
                f"I noticed {lead_company} is growing — congrats on that.\n\n"
                f"We built {product_name} specifically for {lead_title}s who are dealing with "
                f"{pain}. {value_prop}\n\n"
                f"Would it make sense to connect for 15 minutes this week?\n\n"
                f"Best,"
            ),
            "type": "intro",
        })

        if sequence_length >= 2:
            emails.append({
                "send_day": 4,
                "subject": f"Re: {lead_company} + {product_name}",
                "body": (
                    f"Hi {lead_name},\n\n"
                    f"Wanted to follow up — we've helped similar companies save significant time on "
                    f"{pain}.\n\n"
                    f"Happy to share a quick demo if you're curious. No pressure.\n\n"
                    f"Best,"
                ),
                "type": "follow_up_1",
            })

        if sequence_length >= 3:
            emails.append({
                "send_day": 10,
                "subject": f"Last note — {product_name} for {lead_company}",
                "body": (
                    f"Hi {lead_name},\n\n"
                    f"I'll keep this short — if the timing isn't right, totally understand.\n\n"
                    f"If {pain} becomes a priority for {lead_company}, "
                    f"we'd love to help. Feel free to reach out anytime.\n\n"
                    f"Best,"
                ),
                "type": "break_up",
            })

    return {
        "product": product_name,
        "lead": {"name": lead_name, "company": lead_company, "title": lead_title},
        "sequence": emails,
        "total_emails": len(emails),
    }


def _pain_point(title: str) -> str:
    t = title.lower()
    if any(w in t for w in ["ceo", "founder", "co-founder"]):
        return "fundraising and go-to-market execution"
    if "president" in t:
        return "scaling revenue while managing costs"
    if any(w in t for w in ["cto", "vp engineering", "head of engineering"]):
        return "shipping faster without accumulating technical debt"
    if any(w in t for w in ["engineer", "developer", "architect"]):
        return "reducing repetitive work and speeding up delivery"
    if any(w in t for w in ["cmo", "vp marketing", "head of marketing"]):
        return "generating qualified pipeline at a lower CAC"
    if any(w in t for w in ["marketing", "demand", "growth hacker"]):
        return "running campaigns that convert without blowing budget"
    if any(w in t for w in ["vp sales", "head of sales", "chief revenue"]):
        return "shortening the sales cycle and hitting quota consistently"
    if any(w in t for w in ["sales", "account executive", "account manager", "revenue"]):
        return "filling the top of funnel and closing deals faster"
    if any(w in t for w in ["cpo", "vp product", "head of product"]):
        return "aligning roadmap to revenue and shipping on time"
    if any(w in t for w in ["product manager", "pm ", " pm", "product owner"]):
        return "cutting scope creep and getting features shipped"
    if any(w in t for w in ["operations", "coo", "head of ops"]):
        return "eliminating manual processes and reporting overhead"
    if any(w in t for w in ["finance", "cfo", "controller"]):
        return "forecasting accurately and reducing financial ops overhead"
    if any(w in t for w in ["hr", "people", "recruiting", "talent"]):
        return "hiring faster and reducing time-to-productivity for new hires"
    return "time-consuming manual work slowing down the team"


def _extract_name(title: str) -> str:
    parts = title.split(" - ")
    if parts:
        candidate = parts[0].strip()
        if len(candidate.split()) <= 4:
            return candidate
    return ""


def _extract_company(title: str, url: str) -> str:
    parts = title.split(" - ")
    if len(parts) >= 2:
        return parts[-1].strip()
    try:
        from urllib.parse import urlparse
        domain = urlparse(url).netloc.replace("www.", "")
        return domain.split(".")[0].capitalize()
    except Exception:
        return ""
