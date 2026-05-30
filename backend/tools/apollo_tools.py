"""
Apollo.io API wrapper.

Endpoints:
  POST /people/search          — search contacts with rich filters
  POST /organizations/search   — search companies
  POST /people/match           — enrich a single person by email / LinkedIn
  POST /organizations/enrich   — enrich a company by domain
"""
import logging
from typing import Any

import requests

from backend.config import settings

logger = logging.getLogger(__name__)

_BASE = "https://api.apollo.io/api/v1"
_TIMEOUT = 20


def _key() -> str:
    return settings.apollo_api_key


def _post(endpoint: str, body: dict) -> dict:
    if not _key():
        return {"error": "APOLLO_API_KEY not configured"}
    try:
        r = requests.post(
            f"{_BASE}{endpoint}",
            json=body,
            headers={
                "Content-Type": "application/json",
                "x-api-key": _key(),
            },
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


def _normalize_person(p: dict) -> dict:
    """Flatten Apollo's nested person object to a clean flat dict."""
    org = p.get("organization") or {}
    return {
        "apollo_id": p.get("id", ""),
        "first_name": p.get("first_name", ""),
        "last_name": p.get("last_name", ""),
        "email": p.get("email", ""),
        "email_status": p.get("email_status", ""),   # verified | unverified | likely | guessed
        "title": p.get("title", ""),
        "seniority": p.get("seniority", ""),
        "departments": p.get("departments", []),
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
        "company_city": org.get("city", ""),
        "company_country": org.get("country", ""),
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
        "twitter": o.get("twitter_url", ""),
        "technologies": [t.get("name", "") for t in (o.get("technology_names") or [])],
        "keywords": o.get("keywords", []),
        "founded_year": o.get("founded_year"),
        "description": o.get("short_description", ""),
    }


def _size_label(n: int | None) -> str:
    if not n:
        return ""
    if n <= 10:
        return "1-10"
    if n <= 50:
        return "11-50"
    if n <= 200:
        return "51-200"
    if n <= 500:
        return "201-500"
    if n <= 1000:
        return "501-1000"
    if n <= 5000:
        return "1001-5000"
    return "5000+"


# ── People search ─────────────────────────────────────────────────────────────

def apollo_search_people(
    titles: list[str] | None = None,
    seniorities: list[str] | None = None,      # "c_suite" | "vp" | "director" | "manager" | "senior" | "entry"
    locations: list[str] | None = None,
    industries: list[str] | None = None,
    company_sizes: list[str] | None = None,    # e.g. ["1,10", "11,50", "51,200"]
    funding_stages: list[str] | None = None,   # e.g. ["seed", "series_a"]
    domains_include: list[str] | None = None,
    domains_exclude: list[str] | None = None,
    keywords: list[str] | None = None,
    has_email: bool = True,
    page: int = 1,
    per_page: int = 25,
) -> dict:
    """Search Apollo's people database with rich filters. Returns normalized contacts."""
    body: dict[str, Any] = {
        "page": page,
        "per_page": min(per_page, 100),
    }

    if titles:
        body["person_titles"] = titles
    if seniorities:
        body["person_seniorities"] = seniorities
    if locations:
        body["person_locations"] = locations
    if industries:
        body["organization_industry_tag_ids"] = industries  # pass raw tag names — Apollo accepts these
        body["q_organization_industry_tag_id"] = industries
    if company_sizes:
        body["organization_num_employees_ranges"] = company_sizes
    if funding_stages:
        body["organization_latest_funding_stage_cd"] = funding_stages
    if domains_include:
        body["q_organization_domains"] = "\n".join(domains_include)
    if keywords:
        body["q_keywords"] = " ".join(keywords)
    if has_email:
        body["contact_email_status"] = ["verified", "unverified", "likely"]

    data = _post("/mixed_people/search", body)
    if "error" in data:
        return data

    people = data.get("people", []) or data.get("contacts", [])
    pagination = data.get("pagination", {})

    # Exclude domains from results client-side if Apollo doesn't filter server-side
    excluded = set(d.lower() for d in (domains_exclude or []))
    if excluded:
        people = [
            p for p in people
            if (p.get("organization") or {}).get("primary_domain", "").lower() not in excluded
        ]

    return {
        "contacts": [_normalize_person(p) for p in people],
        "total": pagination.get("total_entries", len(people)),
        "page": pagination.get("page", page),
        "total_pages": pagination.get("total_pages", 1),
        "has_more": page < pagination.get("total_pages", 1),
    }


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
    per_page: int = 25,
) -> dict:
    """Search Apollo's company database."""
    body: dict[str, Any] = {"page": page, "per_page": min(per_page, 100)}

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


# ── Person enrichment ─────────────────────────────────────────────────────────

def apollo_enrich_person(
    email: str = "",
    first_name: str = "",
    last_name: str = "",
    domain: str = "",
    linkedin_url: str = "",
) -> dict:
    """Enrich a single person by email, LinkedIn URL, or name + domain."""
    body: dict[str, Any] = {"reveal_personal_emails": False}
    if email:
        body["email"] = email
    elif linkedin_url:
        body["linkedin_url"] = linkedin_url
    elif first_name and last_name and domain:
        body["first_name"] = first_name
        body["last_name"] = last_name
        body["domain"] = domain
    else:
        return {"error": "Provide email, linkedin_url, or first_name + last_name + domain"}

    data = _post("/people/match", body)
    if "error" in data:
        return data

    person = data.get("person") or {}
    if not person:
        return {"error": "Person not found", "email": email}

    return _normalize_person(person)


# ── Company enrichment ────────────────────────────────────────────────────────

def apollo_enrich_company(domain: str) -> dict:
    """Enrich a company by domain."""
    data = _post("/organizations/enrich", {"domain": domain})
    if "error" in data:
        return data

    org = data.get("organization") or {}
    if not org:
        return {"error": "Company not found", "domain": domain}

    return _normalize_org(org)
