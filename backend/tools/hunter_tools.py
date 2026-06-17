"""
Hunter.io API wrapper.

Endpoints used:
  /discover           — find companies/people matching a query
  /domain-search      — all emails at a domain
  /email-finder       — find email for a specific person
  /email-verifier     — verify an email address
  /companies/find     — enrich a company by domain
  /people/find        — enrich a person by email
  /combined/find      — combined person + company enrichment
"""
import logging
from typing import Any

import requests

from backend.config import settings

logger = logging.getLogger(__name__)

_BASE = "https://api.hunter.io/v2"
_TIMEOUT = 15


def _key() -> str:
    return settings.hunter_api_key


def _get(endpoint: str, params: dict) -> dict:
    if not _key():
        return {"error": "HUNTER_API_KEY not configured"}
    try:
        params["api_key"] = _key()
        r = requests.get(f"{_BASE}{endpoint}", params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except requests.HTTPError as e:
        logger.warning("Hunter %s error: %s", endpoint, e)
        return {"error": str(e), "status_code": e.response.status_code if e.response else None}
    except Exception as e:
        logger.error("Hunter %s failed: %s", endpoint, e)
        return {"error": str(e)}


# ── Domain search ─────────────────────────────────────────────────────────────

def hunter_domain_search(
    domain: str,
    limit: int = 10,
    offset: int = 0,
    type: str = "",          # "personal" | "generic" | ""
    seniority: str = "",     # "junior" | "senior" | "executive" | ""
    department: str = "",    # "executive" | "it" | "finance" | "management" | "sales" | "legal" | "support" | "hr" | "marketing" | "communication" | "education" | "design" | "health" | "media" | ""
) -> dict:
    """Return all email addresses found at a domain, with optional filters."""
    params: dict[str, Any] = {"domain": domain, "limit": limit, "offset": offset}
    if type:
        params["type"] = type
    if seniority:
        params["seniority"] = seniority
    if department:
        params["department"] = department

    data = _get("/domain-search", params)
    if "error" in data:
        return data

    d = data.get("data", {})
    emails = d.get("emails", [])
    return {
        "domain": domain,
        "organization": d.get("organization", ""),
        "description": d.get("description", ""),
        "industry": d.get("industry", ""),
        "company_size": d.get("company_size", ""),
        "linkedin": d.get("linkedin", ""),
        "twitter": d.get("twitter", ""),
        "emails": [
            {
                "email": e.get("value", ""),
                "first_name": e.get("first_name", ""),
                "last_name": e.get("last_name", ""),
                "position": e.get("position", ""),
                "seniority": e.get("seniority", ""),
                "department": e.get("department", ""),
                "linkedin": e.get("linkedin", ""),
                "confidence": e.get("confidence", 0),
                "verification_status": e.get("verification", {}).get("status", ""),
            }
            for e in emails
        ],
        "total": d.get("meta", {}).get("total", len(emails)),
    }


# ── Email finder ──────────────────────────────────────────────────────────────

def hunter_find_email(
    domain: str,
    first_name: str,
    last_name: str,
    company: str = "",
) -> dict:
    """Find the email address for a specific person at a domain."""
    params: dict[str, Any] = {
        "domain": domain,
        "first_name": first_name,
        "last_name": last_name,
    }
    if company:
        params["company"] = company

    data = _get("/email-finder", params)
    if "error" in data:
        return data

    d = data.get("data", {})
    return {
        "email": d.get("email", ""),
        "score": d.get("score", 0),
        "position": d.get("position", ""),
        "twitter": d.get("twitter", ""),
        "linkedin_url": d.get("linkedin_url", ""),
        "confidence": d.get("confidence", ""),
        "sources": d.get("sources", []),
    }


# ── Email verifier ────────────────────────────────────────────────────────────

def hunter_verify_email(email: str) -> dict:
    """Verify whether an email address is deliverable."""
    data = _get("/email-verifier", {"email": email})
    if "error" in data:
        return data

    d = data.get("data", {})
    return {
        "email": email,
        "status": d.get("status", ""),           # valid | invalid | accept_all | webmail | disposable | unknown
        "score": d.get("score", 0),
        "regexp": d.get("regexp", False),
        "gibberish": d.get("gibberish", False),
        "disposable": d.get("disposable", False),
        "webmail": d.get("webmail", False),
        "mx_records": d.get("mx_records", False),
        "smtp_server": d.get("smtp_server", False),
        "smtp_check": d.get("smtp_check", False),
        "accept_all": d.get("accept_all", False),
        "block": d.get("block", False),
    }


# ── Company enrichment ────────────────────────────────────────────────────────

def hunter_enrich_company(domain: str) -> dict:
    """Return company metadata for a domain."""
    data = _get("/companies/find", {"domain": domain})
    if "error" in data:
        return data

    d = data.get("data", {})
    return {
        "domain": domain,
        "name": d.get("name", ""),
        "description": d.get("description", ""),
        "industry": d.get("industry", ""),
        "company_type": d.get("company_type", ""),
        "country": d.get("country", ""),
        "city": d.get("city", ""),
        "employees_count": d.get("employees_count"),
        "company_size": d.get("company_size", ""),
        "founded_year": d.get("founded_year"),
        "linkedin": d.get("linkedin", ""),
        "twitter": d.get("twitter", ""),
        "facebook": d.get("facebook", ""),
        "phone_number": d.get("phone_number", ""),
        "technologies": d.get("technologies", []),
        "alexa_ranking": d.get("alexa_ranking"),
    }


# ── Person enrichment ─────────────────────────────────────────────────────────

def hunter_enrich_person(email: str) -> dict:
    """Return person metadata for an email address."""
    data = _get("/people/find", {"email": email})
    if "error" in data:
        return data

    d = data.get("data", {})
    return {
        "email": email,
        "first_name": d.get("first_name", ""),
        "last_name": d.get("last_name", ""),
        "position": d.get("position", ""),
        "seniority": d.get("seniority", ""),
        "department": d.get("department", ""),
        "company_name": d.get("company", {}).get("name", ""),
        "company_domain": d.get("company", {}).get("domain", ""),
        "linkedin": d.get("linkedin", ""),
        "twitter": d.get("twitter", ""),
        "phone": d.get("phone_number", ""),
        "city": d.get("city", ""),
        "country": d.get("country", ""),
        "confidence": d.get("confidence", 0),
    }


# ── Combined enrichment ───────────────────────────────────────────────────────

def hunter_enrich_combined(email: str) -> dict:
    """Return both person and company data for an email address."""
    data = _get("/combined/find", {"email": email})
    if "error" in data:
        return data

    d = data.get("data", {})
    person = d.get("person", {})
    company = d.get("company", {})

    return {
        "email": email,
        "person": {
            "first_name": person.get("first_name", ""),
            "last_name": person.get("last_name", ""),
            "position": person.get("position", ""),
            "seniority": person.get("seniority", ""),
            "department": person.get("department", ""),
            "linkedin": person.get("linkedin", ""),
            "twitter": person.get("twitter", ""),
            "phone": person.get("phone_number", ""),
            "city": person.get("city", ""),
            "country": person.get("country", ""),
            "confidence": person.get("confidence", 0),
        },
        "company": {
            "name": company.get("name", ""),
            "domain": company.get("domain", ""),
            "description": company.get("description", ""),
            "industry": company.get("industry", ""),
            "company_size": company.get("company_size", ""),
            "employees_count": company.get("employees_count"),
            "country": company.get("country", ""),
            "city": company.get("city", ""),
            "linkedin": company.get("linkedin", ""),
            "technologies": company.get("technologies", []),
            "founded_year": company.get("founded_year"),
        },
    }


# ── Composite: search domains + store contacts ────────────────────────────────

def hunter_search_by_domains(
    founder_id: str = "",
    domains: list[str] | None = None,
    seniority: str = "",
    department: str = "",
    limit_per_domain: int = 10,
) -> dict:
    """
    Domain-search a list of domains via Hunter and store all contacts in
    the Supabase outreach_contacts table under this founder.

    Caches results per domain — if we've already searched a domain in the
    last 90 days (from any founder), we reuse those contacts without burning
    another Hunter API credit. This dramatically extends the 50/month free limit.

    Args:
        founder_id:        The founder's ID (contacts stored under this).
        domains:           List of company domains, e.g. ["darden.com", "wingstop.com"].
        seniority:         Filter by seniority: "junior" | "senior" | "executive" | "".
        department:        Filter by dept: "executive" | "sales" | "management" | "it" | "".
        limit_per_domain:  Max emails per domain (max 10 on free tier).

    Returns summary of contacts found and stored.
    """
    from backend.tools._arg_utils import parse_list_arg
    domains = parse_list_arg(domains, "domains")
    if not domains:
        return {"error": "domains is required — pass a list of company domains, e.g. [\"acme.com\", \"example.com\"]"}
    if not founder_id:
        return {"error": "founder_id is required"}
    import time
    from datetime import datetime, timedelta, timezone
    all_contacts: list[dict] = []
    cached_domains: set[str] = set()

    # Check Supabase cache first — skip Hunter call if domain was searched recently
    try:
        from backend.db.client import get_supabase
        db = get_supabase()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        for domain in domains:
            res = (
                db.table("outreach_contacts")
                .select("email,first_name,last_name,title,company_name,company_domain,linkedin_url,seniority,industry,company_size")
                .eq("company_domain", domain)
                .eq("source", "hunter")
                .gte("created_at", cutoff)
                .limit(limit_per_domain)
                .execute()
            )
            if res.data:
                cached_domains.add(domain)
                for row in res.data:
                    all_contacts.append({
                        "founder_id": founder_id,
                        "email": row.get("email", ""),
                        "first_name": row.get("first_name", ""),
                        "last_name": row.get("last_name", ""),
                        "title": row.get("title", ""),
                        "company_name": row.get("company_name", ""),
                        "company_domain": row.get("company_domain", domain),
                        "linkedin_url": row.get("linkedin_url", ""),
                        "seniority": row.get("seniority", ""),
                        "industry": row.get("industry", ""),
                        "company_size": row.get("company_size", ""),
                        "city": "",
                        "country": "",
                        "source": "hunter",
                    })
    except Exception as e:
        logger.warning("Cache lookup failed (will call Hunter): %s", e)

    domains_to_search = [d for d in domains if d not in cached_domains]

    for domain in domains_to_search:
        result = hunter_domain_search(
            domain=domain,
            limit=min(limit_per_domain, 10),
            seniority=seniority,
            department=department,
        )
        if "error" in result:
            logger.warning("Hunter domain search failed for %s: %s", domain, result["error"])
            continue

        org = result.get("organization", "")
        industry = result.get("industry", "")
        company_size = result.get("company_size", "")

        for e in result.get("emails", []):
            email = e.get("email", "").lower().strip()
            if not email:
                continue
            all_contacts.append({
                "founder_id": founder_id,
                "email": email,
                "first_name": e.get("first_name", ""),
                "last_name": e.get("last_name", ""),
                "title": e.get("position", ""),
                "company_name": org,
                "company_domain": domain,
                "linkedin_url": e.get("linkedin", ""),
                "seniority": e.get("seniority", ""),
                "industry": industry,
                "company_size": company_size,
                "city": "",
                "country": "",
                "source": "hunter",
            })

        time.sleep(0.3)  # avoid Hunter rate limit

    stored = hunter_store_contacts(founder_id, all_contacts)
    return {
        "domains_searched": len(domains),
        "contacts_found": len(all_contacts),
        "contacts_stored": stored.get("stored", 0),
        "cached_domains": len(cached_domains),
        "contacts": all_contacts,
    }


def hunter_store_contacts(founder_id: str = "", contacts: list[dict] | None = None) -> dict:
    """
    Store a list of contacts (from any Hunter call) into the Supabase
    outreach_contacts table. Deduplicates by (founder_id, email).

    Args:
        founder_id: The founder's ID.
        contacts:   List of contact dicts — must have at least 'email'.

    Returns: { "stored": N }
    """
    from backend.tools._arg_utils import parse_list_arg
    contacts = parse_list_arg(contacts, "contacts") or []
    if not contacts:
        return {"stored": 0}

    # Filter to only contacts with a valid email
    valid = [c for c in contacts if isinstance(c, dict) and c.get("email") and "@" in c["email"]]
    if not valid:
        return {"stored": 0}

    try:
        from backend.db.client import get_supabase
        db = get_supabase()
        rows = [{
            "founder_id": founder_id,
            "email": c.get("email", "").lower().strip(),
            "first_name": c.get("first_name", ""),
            "last_name": c.get("last_name", ""),
            "title": c.get("title", "") or c.get("position", ""),
            "company_name": c.get("company_name", "") or c.get("organization", ""),
            "company_domain": c.get("company_domain", ""),
            "linkedin_url": c.get("linkedin_url", "") or c.get("linkedin", ""),
            "seniority": c.get("seniority", ""),
            "industry": c.get("industry", ""),
            "company_size": c.get("company_size", ""),
            "city": c.get("city", ""),
            "country": c.get("country", ""),
            "source": c.get("source", "hunter"),
        } for c in valid]

        stored = 0
        for i in range(0, len(rows), 50):
            db.table("outreach_contacts").upsert(
                rows[i:i + 50],
                on_conflict="founder_id,email",
                ignore_duplicates=True,
            ).execute()
            stored += len(rows[i:i + 50])

        return {"stored": stored}
    except Exception as e:
        logger.error("hunter_store_contacts failed: %s", e)
        return {"stored": 0, "error": str(e)}
