"""
Apollo.io API wrapper.

Two-phase flow (saves credits):
  Phase 1 — SEARCH  POST /mixed_people/api_search   free, no credits, no emails
  Phase 2 — ENRICH  POST /people/match              costs 1 credit per person

The search endpoint is credit-free so we can search freely.
We hard-cap at MAX_PER_PULL contacts and only enrich when the
user explicitly requests emails — that's when credits are spent.
"""
import logging
from typing import Any

import requests

from backend.config import settings

logger = logging.getLogger(__name__)

_BASE = "https://api.apollo.io/api/v1"
_TIMEOUT = 20

# Search is free — show up to 100 results so users can pick what they want
MAX_SEARCH_RESULTS = 100
# Enrichment costs 1 credit per contact — cap how many can be revealed at once
MAX_ENRICH_BATCH = 10


def _key() -> str:
    return settings.apollo_api_key


def _headers() -> dict:
    return {
        "Content-Type": "application/json",
        "x-api-key": _key(),
    }


def _post(endpoint: str, body: dict) -> dict:
    if not _key():
        return {"error": "APOLLO_API_KEY not configured"}
    try:
        r = requests.post(
            f"{_BASE}{endpoint}",
            json=body,
            headers=_headers(),
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()
    except requests.HTTPError as e:
        logger.warning("Apollo %s error %s: %s", endpoint, e.response.status_code if e.response else "?", e)
        try:
            return {"error": e.response.json(), "status_code": e.response.status_code}
        except Exception:
            return {"error": str(e)}
    except Exception as e:
        logger.error("Apollo %s failed: %s", endpoint, e)
        return {"error": str(e)}


def _get(endpoint: str, params: dict) -> dict:
    """GET request — used for credit-free search endpoint."""
    if not _key():
        return {"error": "APOLLO_API_KEY not configured"}
    try:
        r = requests.get(
            f"{_BASE}{endpoint}",
            params=params,
            headers=_headers(),
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()
    except requests.HTTPError as e:
        logger.warning("Apollo %s error %s: %s", endpoint, e.response.status_code if e.response else "?", e)
        try:
            return {"error": e.response.json(), "status_code": e.response.status_code}
        except Exception:
            return {"error": str(e)}
    except Exception as e:
        logger.error("Apollo %s failed: %s", endpoint, e)
        return {"error": str(e)}


def _score_person(p: dict) -> int:
    """Score a search result so we surface the best contacts first.
    Higher = better. Criteria: has email > has phone > recently refreshed > has location."""
    score = 0
    if p.get("has_email"):
        score += 10
    if p.get("has_direct_phone") == "Yes":
        score += 5
    if p.get("has_city"):
        score += 2
    if p.get("has_state"):
        score += 1
    if p.get("has_country"):
        score += 1
    org = p.get("organization") or {}
    if org.get("has_revenue"):
        score += 3
    if org.get("has_employee_count"):
        score += 2
    if org.get("has_industry"):
        score += 2
    return score


def _normalize_search_person(p: dict) -> dict:
    """Normalize a result from the credit-free search endpoint."""
    org = p.get("organization") or {}

    # Apollo's search endpoint returns obfuscated last_name in the "last_name" field.
    # There is no separate "last_name_obfuscated" key.
    first_name = p.get("first_name", "") or ""
    last_name  = p.get("last_name", "") or ""
    # Strip asterisk-only tokens — they add clutter without meaning
    if all(c in "*" for c in last_name.replace(" ", "")):
        last_name = ""

    # Company name: try org object first, fall back to person-level field
    company_name = org.get("name", "") or p.get("organization_name", "")

    # Industry: Apollo may use "industry" or nested tags
    industry = (org.get("industry") or "").strip()

    # Employee count: try two field names
    emp = org.get("estimated_num_employees") or org.get("num_employees") or 0

    # Description: short_description is often null; fall back to a composite
    description = (org.get("short_description") or org.get("seo_description") or "").strip()
    if not description and industry and company_name:
        description = f"{company_name} — {industry}"
    description = description[:200]

    # Website
    website = (org.get("website_url") or org.get("primary_domain") or "").strip()

    return {
        "apollo_id": p.get("id", ""),
        "first_name": first_name,
        "last_name": last_name,
        "title": (p.get("title") or p.get("headline") or "").strip(),
        "company_name": company_name,
        "has_email": bool(p.get("email") or p.get("has_email")),
        "has_phone": bool(p.get("has_direct_phone")),
        "city": p.get("city", ""),
        "state": p.get("state", ""),
        "country": p.get("country", ""),
        "email": "",
        "email_status": p.get("email_status", "unknown"),
        "linkedin_url": p.get("linkedin_url", ""),
        "enriched": False,
        "company_industry": industry,
        "company_size": _size_label(emp),
        "company_website": website,
        "company_description": description,
        "company_funding": org.get("latest_funding_stage", ""),
    }


def _normalize_enriched_person(p: dict) -> dict:
    """Normalize a result from the credit-consuming enrichment endpoint."""
    org = p.get("organization") or {}
    return {
        "apollo_id": p.get("id", ""),
        "first_name": p.get("first_name", ""),
        "last_name": p.get("last_name", ""),
        "email": p.get("email", ""),
        "email_status": p.get("email_status", ""),
        "title": p.get("title", "") or "",
        "seniority": p.get("seniority", ""),
        "linkedin_url": p.get("linkedin_url", ""),
        "city": p.get("city", ""),
        "state": p.get("state", ""),
        "country": p.get("country", ""),
        "company_name": org.get("name", "") or p.get("organization_name", ""),
        "company_domain": org.get("primary_domain", ""),
        "company_industry": org.get("industry", ""),
        "company_size": _size_label(org.get("estimated_num_employees")),
        "company_employees": org.get("estimated_num_employees"),
        "company_funding_stage": org.get("latest_funding_stage", ""),
        "company_linkedin": org.get("linkedin_url", ""),
        "company_website": org.get("website_url", ""),
        "has_email": bool(p.get("email")),
        "has_phone": bool(p.get("direct_phone")),
        "enriched": True,
    }


def _normalize_org(o: dict) -> dict:
    return {
        "apollo_id": o.get("id", ""),
        "name": o.get("name", ""),
        "domain": o.get("primary_domain", ""),
        "website": o.get("website_url", ""),
        "industry": o.get("industry", ""),
        "company_size": _size_label(o.get("estimated_num_employees")),
        "employees": o.get("estimated_num_employees"),
        "funding_stage": o.get("latest_funding_stage", ""),
        "total_funding": o.get("total_funding", 0),
        "city": o.get("city", ""),
        "state": o.get("state", ""),
        "country": o.get("country", ""),
        "linkedin": o.get("linkedin_url", ""),
        "technologies": [t.get("name", "") for t in (o.get("technology_names") or [])],
        "description": o.get("short_description", ""),
    }


def _size_label(n: int | None) -> str:
    if not n:
        return ""
    if n <= 10:     return "1-10"
    if n <= 50:     return "11-50"
    if n <= 200:    return "51-200"
    if n <= 500:    return "201-500"
    if n <= 1000:   return "501-1000"
    if n <= 5000:   return "1001-5000"
    return "5000+"


# ── Phase 1: Credit-free people search ────────────────────────────────────────

def apollo_search_people(
    titles: list[str] | None = None,
    seniorities: list[str] | None = None,
    locations: list[str] | None = None,
    industries: list[str] | None = None,
    company_sizes: list[str] | None = None,
    funding_stages: list[str] | None = None,
    domains_include: list[str] | None = None,
    domains_exclude: list[str] | None = None,
    keywords: list[str] | None = None,
    has_email: bool = False,
    page: int = 1,
    per_page: int = MAX_SEARCH_RESULTS,
) -> dict:
    """
    Credit-free people search via /mixed_people/api_search.
    Returns up to 100 results with no email addresses — free to call.
    User picks which contacts to reveal; call apollo_enrich_batch() for
    the selected contacts to get emails (costs 1 credit each, max 15 at once).
    """
    fetch_size = min(per_page, MAX_SEARCH_RESULTS)

    # Some Apollo endpoint configs require api_key in the body in addition to the header
    params: dict[str, Any] = {
        "api_key": _key(),
        "per_page": fetch_size,
        "page": page,
    }

    # Reliable structured filters (Apollo enum/range fields — these match exactly)
    if titles:
        params["person_titles"] = titles
    if seniorities:
        params["person_seniorities"] = seniorities
    if locations:
        params["person_locations"] = locations
    if company_sizes:
        params["organization_num_employees_ranges"] = company_sizes
    if domains_include:
        params["q_organization_domains_list"] = domains_include

    # Industries → q_keywords (NOT q_organization_industry_tag_names).
    # The tag-names param requires Apollo's exact internal taxonomy strings
    # (e.g. "Computer Software", NOT "SaaS") — wrong names silently return ~0 results.
    # q_keywords is a free-text search across all profile fields and is far more forgiving.
    kw_parts = list(industries or []) + list(keywords or [])
    if kw_parts:
        params["q_keywords"] = " ".join(kw_parts)

    data = _post("/mixed_people/api_search", params)
    if "error" in data:
        return data

    people = data.get("people", [])

    # Exclude domains client-side
    excluded = set(d.lower() for d in (domains_exclude or []))
    if excluded:
        people = [
            p for p in people
            if (p.get("organization") or {}).get("primary_domain", "").lower() not in excluded
        ]

    # Rank by quality score — best contacts first
    people_sorted = sorted(people, key=_score_person, reverse=True)

    # Pagination: Apollo may nest under "pagination" key or expose at top level
    pagination = data.get("pagination") or {}
    total = (
        data.get("total_entries")
        or pagination.get("total_entries")
        or len(people)
    )

    return {
        "contacts": [_normalize_search_person(p) for p in people_sorted],
        "total": total,
        "page": page,
        "per_page": fetch_size,
        "has_more": total > page * fetch_size,
    }


# ── Phase 2: Credit-consuming enrichment ──────────────────────────────────────

def apollo_enrich_person(
    apollo_id: str = "",
    email: str = "",
    first_name: str = "",
    last_name: str = "",
    company_name: str = "",
    domain: str = "",
    linkedin_url: str = "",
) -> dict:
    """
    Reveal full details (email, full name, LinkedIn) for one person.
    Costs 1 credit. Only call this for contacts you intend to reach out to.
    Accepts: apollo_id (from search), email, linkedin_url, or first_name + domain.
    """
    body: dict[str, Any] = {"reveal_personal_emails": False}

    if apollo_id:
        body["id"] = apollo_id
    elif email:
        body["email"] = email
    elif linkedin_url:
        body["linkedin_url"] = linkedin_url
    elif first_name and (domain or company_name):
        body["first_name"] = first_name
        if last_name:
            body["last_name"] = last_name
        if domain:
            body["domain"] = domain
        if company_name:
            body["organization_name"] = company_name
    else:
        return {"error": "Provide apollo_id, email, linkedin_url, or first_name + domain/company_name"}

    data = _post("/people/match", body)
    if "error" in data:
        return data

    person = data.get("person") or {}
    if not person:
        return {"error": "Person not found", "apollo_id": apollo_id}

    return _normalize_enriched_person(person)


def apollo_enrich_batch(contacts: list[dict]) -> list[dict]:
    """
    Reveal emails for up to MAX_ENRICH_BATCH contacts (1 credit each).
    Each contact needs `apollo_id` (or first_name + company_name).
    User should select which contacts they want before calling this.
    """
    batch = contacts[:MAX_ENRICH_BATCH]
    results = []
    for contact in batch:
        enriched = apollo_enrich_person(
            apollo_id=contact.get("apollo_id", ""),
            first_name=contact.get("first_name", ""),
            last_name=contact.get("last_name", ""),
            company_name=contact.get("company_name", ""),
        )
        if "error" not in enriched:
            results.append(enriched)
        else:
            # Keep original data even if enrichment failed
            results.append({**contact, "enriched": False, "enrich_error": enriched.get("error")})
    return results


# ── Company search ────────────────────────────────────────────────────────────

def apollo_search_companies(
    locations: list[str] | None = None,
    industries: list[str] | None = None,
    company_sizes: list[str] | None = None,
    funding_stages: list[str] | None = None,
    keywords: list[str] | None = None,
    technologies: list[str] | None = None,
    domains_include: list[str] | None = None,
    page: int = 1,
    per_page: int = MAX_SEARCH_RESULTS,
) -> dict:
    """Search Apollo's company database. Does not consume credits."""
    body: dict[str, Any] = {"page": page, "per_page": min(per_page, MAX_SEARCH_RESULTS)}

    if locations:
        body["organization_locations"] = locations
    if industries:
        body["organization_industry_tag_ids"] = industries
    if company_sizes:
        body["organization_num_employees_ranges"] = company_sizes
    if funding_stages:
        body["organization_latest_funding_stage_cd"] = funding_stages
    if keywords:
        body["q_keywords"] = " ".join(keywords)
    if technologies:
        body["currently_using_any_of_technology_uids"] = technologies
    if domains_include:
        body["q_organization_domains"] = "\n".join(domains_include)

    data = _post("/mixed_companies/search", body)
    if "error" in data:
        return data

    orgs = data.get("organizations", []) or data.get("accounts", [])
    pagination = data.get("pagination", {})

    return {
        "companies": [_normalize_org(o) for o in orgs],
        "total": pagination.get("total_entries", len(orgs)),
        "page": pagination.get("page", page),
        "has_more": page < pagination.get("total_pages", 1),
    }
