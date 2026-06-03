"""
Multi-source contact discovery scraper.

Builds Astra's own contact database by pulling from free public sources:
  1. Web search (DuckDuckGo) — find people by title/company/location
  2. Company website scraping — team pages, about pages, contact emails
  3. GitHub public API — organisation members, commit emails
  4. Hacker News Algolia API — "Who is hiring" threads, founders
  5. Hunter.io domain search (free tier) — emails at a domain
  6. Apollo (enrichment only when available)

All results are normalised to the outreach_contacts schema and stored in
Supabase so searches become free after the first crawl.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any
from urllib.parse import urlparse

import requests

from backend.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = 12
_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", re.IGNORECASE
)
_BLOCKED_EMAIL_DOMAINS = {
    "example.com", "test.com", "sentry.io", "amazonaws.com",
    "cloudfront.net", "wixpress.com", "squarespace.com",
    "w3.org", "schema.org", "googleapis.com",
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _clean_email(email: str) -> str | None:
    email = email.lower().strip()
    domain = email.split("@")[-1] if "@" in email else ""
    if domain in _BLOCKED_EMAIL_DOMAINS:
        return None
    if any(x in email for x in [".png", ".jpg", ".gif", ".svg", ".css", ".js"]):
        return None
    return email


def _extract_emails_from_text(text: str) -> list[str]:
    found = _EMAIL_RE.findall(text)
    cleaned = [_clean_email(e) for e in found]
    return list({e for e in cleaned if e})


def _domain_from_url(url: str) -> str:
    try:
        parsed = urlparse(url if url.startswith("http") else f"https://{url}")
        return parsed.netloc.lower().lstrip("www.")
    except Exception:
        return url


def _get(url: str, params: dict | None = None, headers: dict | None = None) -> dict | str | None:
    try:
        r = requests.get(url, params=params, headers=headers or {}, timeout=_TIMEOUT)
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            return r.text
    except Exception as e:
        logger.debug("GET %s failed: %s", url, e)
        return None


def _normalize_contact(
    email: str = "",
    first_name: str = "",
    last_name: str = "",
    title: str = "",
    company_name: str = "",
    company_domain: str = "",
    linkedin_url: str = "",
    city: str = "",
    country: str = "",
    industry: str = "",
    company_size: str = "",
    seniority: str = "",
    source: str = "scraper",
    **_,
) -> dict:
    return {
        "email": email.lower().strip(),
        "first_name": first_name.strip(),
        "last_name": last_name.strip(),
        "title": title.strip(),
        "company_name": company_name.strip(),
        "company_domain": company_domain.lower().strip(),
        "linkedin_url": linkedin_url.strip(),
        "city": city.strip(),
        "country": country.strip(),
        "industry": industry.strip(),
        "company_size": company_size,
        "seniority": seniority,
        "source": source,
    }


# ── Source 1: Web search ───────────────────────────────────────────────────────

def discover_via_web_search(
    titles: list[str],
    industries: list[str] | None = None,
    locations: list[str] | None = None,
    limit: int = 30,
) -> list[dict]:
    """
    Use DuckDuckGo to find people matching title/industry/location.
    Parses search snippets and LinkedIn URLs from results.
    """
    from backend.tools.web_search import web_search

    contacts: list[dict] = []
    seen_urls: set[str] = set()

    title_str = " OR ".join(f'"{t}"' for t in titles[:4])
    industry_str = " ".join(industries[:2]) if industries else ""
    location_str = locations[0] if locations else ""

    queries = [
        f'site:linkedin.com/in {title_str} {industry_str} {location_str}',
        f'{title_str} {industry_str} {location_str} email contact',
        f'{title_str} {industry_str} startup founder "contact us"',
    ]

    for q in queries:
        if len(contacts) >= limit:
            break
        results = web_search(q)
        if not isinstance(results, dict):
            continue
        for item in results.get("results", [])[:10]:
            url = item.get("url", "")
            snippet = item.get("snippet", "") + " " + item.get("title", "")
            if url in seen_urls:
                continue
            seen_urls.add(url)

            # Extract from LinkedIn URL
            if "linkedin.com/in/" in url:
                slug = url.split("linkedin.com/in/")[-1].strip("/").split("?")[0]
                name_parts = slug.replace("-", " ").split()
                first = name_parts[0].capitalize() if name_parts else ""
                last = " ".join(p.capitalize() for p in name_parts[1:]) if len(name_parts) > 1 else ""

                # Try to infer title from snippet
                inferred_title = ""
                for t in titles:
                    if t.lower() in snippet.lower():
                        inferred_title = t
                        break

                contacts.append(_normalize_contact(
                    first_name=first,
                    last_name=last,
                    title=inferred_title,
                    linkedin_url=url,
                    source="web_search_linkedin",
                ))
                continue

            # Extract emails from snippet
            emails = _extract_emails_from_text(snippet)
            for email in emails:
                if "@" not in email:
                    continue
                domain = email.split("@")[-1]
                contacts.append(_normalize_contact(
                    email=email,
                    company_domain=domain,
                    source="web_search_email",
                ))

    return contacts[:limit]


# ── Source 2: Company website scraping ────────────────────────────────────────

def scrape_company_contacts(domain: str, max_emails: int = 20) -> list[dict]:
    """
    Fetch a company's website and extract emails from team/about/contact pages.
    """
    from backend.tools.browser_research import fetch_and_read

    contacts: list[dict] = []
    pages_to_try = [
        f"https://{domain}/about",
        f"https://{domain}/team",
        f"https://{domain}/contact",
        f"https://{domain}/about-us",
        f"https://{domain}/our-team",
        f"https://www.{domain}",
    ]

    seen_emails: set[str] = set()

    for page_url in pages_to_try:
        if len(seen_emails) >= max_emails:
            break
        try:
            result = fetch_and_read(page_url)
            if not result or isinstance(result, dict) and result.get("error"):
                continue

            text = ""
            if isinstance(result, dict):
                text = result.get("text", "") or result.get("content", "") or str(result)
            elif isinstance(result, str):
                text = result

            emails = _extract_emails_from_text(text)
            for email in emails:
                if email in seen_emails:
                    continue
                seen_emails.add(email)
                contacts.append(_normalize_contact(
                    email=email,
                    company_domain=domain,
                    source="website_scrape",
                ))
                if len(seen_emails) >= max_emails:
                    break
        except Exception as e:
            logger.debug("Scrape %s failed: %s", page_url, e)

    return contacts


# ── Source 3: GitHub public API ───────────────────────────────────────────────

def get_github_org_contacts(org_name: str, limit: int = 30) -> list[dict]:
    """
    Pull public member emails from a GitHub organisation.
    No auth needed for public data; uses commit emails as a fallback.
    """
    contacts: list[dict] = []
    headers = {"Accept": "application/vnd.github+json"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"

    # Get org members
    members = _get(
        f"https://api.github.com/orgs/{org_name}/public_members",
        params={"per_page": min(limit, 100)},
        headers=headers,
    )
    if not isinstance(members, list):
        return contacts

    for m in members[:limit]:
        username = m.get("login", "")
        if not username:
            continue

        # Get full profile
        profile = _get(f"https://api.github.com/users/{username}", headers=headers)
        if not isinstance(profile, dict):
            continue

        name = profile.get("name", "") or username
        name_parts = name.split(" ", 1) if name else ["", ""]
        email = profile.get("email", "")

        if not email:
            # Try to extract email from recent commits
            repos = _get(f"https://api.github.com/users/{username}/repos",
                         params={"sort": "pushed", "per_page": 3}, headers=headers)
            if isinstance(repos, list):
                for repo in repos[:2]:
                    repo_name = repo.get("name", "")
                    commits = _get(
                        f"https://api.github.com/repos/{username}/{repo_name}/commits",
                        params={"author": username, "per_page": 1},
                        headers=headers,
                    )
                    if isinstance(commits, list) and commits:
                        commit_email = (
                            (commits[0].get("commit") or {})
                            .get("author", {})
                            .get("email", "")
                        )
                        if commit_email and "noreply" not in commit_email:
                            email = commit_email
                            break

        if not email and not profile.get("company"):
            continue

        company = (profile.get("company") or "").lstrip("@")
        contacts.append(_normalize_contact(
            email=email,
            first_name=name_parts[0],
            last_name=name_parts[1] if len(name_parts) > 1 else "",
            title=profile.get("bio", ""),
            company_name=company,
            company_domain=_domain_from_url(profile.get("blog", "") or ""),
            city=profile.get("location", ""),
            linkedin_url=f"https://github.com/{username}",
            source="github",
        ))
        time.sleep(0.1)  # be kind to GitHub API

    return contacts


# ── Source 4: Hacker News (Who is Hiring) ─────────────────────────────────────

def get_hn_hiring_contacts(keyword: str = "", limit: int = 50) -> list[dict]:
    """
    Parse Hacker News "Who is Hiring" threads via Algolia API.
    Returns founders / companies currently hiring.
    """
    contacts: list[dict] = []

    # Find the most recent "Ask HN: Who is hiring?" thread
    search_url = "https://hn.algolia.com/api/v1/search"
    threads = _get(search_url, params={
        "query": "Ask HN: Who is hiring?",
        "tags": "story,ask_hn",
        "numericFilters": "points>100",
        "hitsPerPage": 3,
    })

    if not isinstance(threads, dict) or not threads.get("hits"):
        return contacts

    story_id = threads["hits"][0].get("objectID", "")
    if not story_id:
        return contacts

    # Get all comments (job listings) from that thread
    comments_url = f"https://hn.algolia.com/api/v1/items/{story_id}"
    story = _get(comments_url)
    if not isinstance(story, dict):
        return contacts

    comments = story.get("children", [])
    seen: set[str] = set()

    for comment in comments[:200]:
        if len(contacts) >= limit:
            break

        text = comment.get("text", "") or ""
        if keyword and keyword.lower() not in text.lower():
            continue

        # Extract emails
        emails = _extract_emails_from_text(text)
        for email in emails:
            if email in seen:
                continue
            seen.add(email)

            domain = email.split("@")[-1]
            # Try to infer company from email domain
            company = domain.split(".")[0].capitalize() if domain else ""

            contacts.append(_normalize_contact(
                email=email,
                company_domain=domain,
                company_name=company,
                source="hackernews_hiring",
            ))

    return contacts[:limit]


# ── Source 5: Hunter.io domain search (free tier) ────────────────────────────

def hunt_domain_contacts(domain: str, limit: int = 10) -> list[dict]:
    """Use Hunter.io domain search to find emails at a company."""
    from backend.tools.hunter_tools import hunter_domain_search

    result = hunter_domain_search(domain=domain, limit=limit)
    if "error" in result:
        return []

    contacts = []
    for e in result.get("emails", []):
        contacts.append(_normalize_contact(
            email=e.get("email", ""),
            first_name=e.get("first_name", ""),
            last_name=e.get("last_name", ""),
            title=e.get("position", ""),
            seniority=e.get("seniority", ""),
            company_name=result.get("organization", ""),
            company_domain=domain,
            industry=result.get("industry", ""),
            company_size=result.get("company_size", ""),
            source="hunter_domain",
        ))
    return contacts


# ── Bulk discovery + store ────────────────────────────────────────────────────

def bulk_discover_and_store(
    founder_id: str,
    titles: list[str] | None = None,
    industries: list[str] | None = None,
    locations: list[str] | None = None,
    domains: list[str] | None = None,
    github_orgs: list[str] | None = None,
    hn_keyword: str = "",
    limit_per_source: int = 50,
) -> dict:
    """
    Run all available scrapers and store results in the Supabase contacts table.
    Returns a summary of contacts discovered and stored.
    """
    all_contacts: list[dict] = []

    # Web search
    if titles:
        try:
            found = discover_via_web_search(titles, industries, locations, limit=limit_per_source)
            all_contacts.extend(found)
            logger.info("Web search: %d contacts", len(found))
        except Exception as e:
            logger.warning("Web search scraper failed: %s", e)

    # Company website scraping
    for domain in (domains or []):
        try:
            found = scrape_company_contacts(domain)
            all_contacts.extend(found)
            logger.info("Website scrape %s: %d contacts", domain, len(found))
        except Exception as e:
            logger.warning("Website scrape %s failed: %s", domain, e)

    # GitHub orgs
    for org in (github_orgs or []):
        try:
            found = get_github_org_contacts(org, limit=limit_per_source)
            all_contacts.extend(found)
            logger.info("GitHub %s: %d contacts", org, len(found))
        except Exception as e:
            logger.warning("GitHub scraper %s failed: %s", org, e)

    # HN hiring
    if hn_keyword or titles:
        try:
            kw = hn_keyword or (titles[0] if titles else "")
            found = get_hn_hiring_contacts(keyword=kw, limit=limit_per_source)
            all_contacts.extend(found)
            logger.info("HN hiring: %d contacts", len(found))
        except Exception as e:
            logger.warning("HN scraper failed: %s", e)

    # Hunter domain search
    for domain in (domains or []):
        try:
            found = hunt_domain_contacts(domain, limit=25)
            all_contacts.extend(found)
            logger.info("Hunter %s: %d contacts", domain, len(found))
        except Exception as e:
            logger.warning("Hunter %s failed: %s", domain, e)

    # Only keep contacts with an email — LinkedIn-only contacts can't be emailed
    # and would violate the unique (founder_id, email) constraint with empty strings
    usable = [c for c in all_contacts if c.get("email")]

    # Store to Supabase
    stored = 0
    if usable and founder_id:
        try:
            from backend.db.client import get_outreach_db
            db = get_outreach_db()
            rows = [{**c, "founder_id": founder_id} for c in usable]
            # Upsert in batches of 50
            for i in range(0, len(rows), 50):
                batch = rows[i:i + 50]
                db.table("outreach_contacts").upsert(
                    batch,
                    on_conflict="founder_id,email",
                    ignore_duplicates=True,
                ).execute()
                stored += len(batch)
        except Exception as e:
            logger.error("Store contacts failed: %s", e)

    return {
        "discovered": len(all_contacts),
        "usable": len(usable),
        "stored": stored,
        "sources": {
            "web_search": len([c for c in all_contacts if "web_search" in c.get("source", "")]),
            "website_scrape": len([c for c in all_contacts if c.get("source") == "website_scrape"]),
            "github": len([c for c in all_contacts if c.get("source") == "github"]),
            "hackernews": len([c for c in all_contacts if c.get("source") == "hackernews_hiring"]),
            "hunter": len([c for c in all_contacts if c.get("source") == "hunter_domain"]),
        },
    }


# ── Local DB search (query our own database) ──────────────────────────────────

def search_local_contacts(
    founder_id: str,
    titles: list[str] | None = None,
    industries: list[str] | None = None,
    locations: list[str] | None = None,
    company_sizes: list[str] | None = None,
    seniorities: list[str] | None = None,
    page: int = 1,
    limit: int = 25,
) -> dict:
    """
    Query the Supabase contacts table.
    Searches both the founder's own contacts AND the shared __global__ pool
    (populated once by the Hunter seeder, shared across all founders).
    """
    from backend.tools.contact_seeder import GLOBAL_FOUNDER_ID
    founder_ids = list({founder_id, GLOBAL_FOUNDER_ID})

    try:
        from backend.db.client import get_outreach_db
        db = get_outreach_db()
        query = db.table("outreach_contacts").select("*").in_("founder_id", founder_ids)

        if industries:
            query = query.in_("industry", industries)
        if locations:
            query = query.in_("country", locations)
        if company_sizes:
            query = query.in_("company_size", company_sizes)
        if seniorities:
            query = query.in_("seniority", seniorities)

        result = query.order("created_at", desc=True).range(
            (page - 1) * limit, page * limit - 1
        ).execute()

        contacts = result.data or []

        # Title filter is flexible (substring match) — done client-side
        if titles:
            titles_lower = [t.lower() for t in titles]
            contacts = [
                c for c in contacts
                if any(t in (c.get("title") or "").lower() for t in titles_lower)
            ]

        return {
            "contacts": contacts,
            "total": len(contacts),
            "page": page,
            "source": "local_db",
        }
    except Exception as e:
        logger.warning("Local search failed: %s", e)
        return {"contacts": [], "total": 0, "page": page, "source": "local_db"}
