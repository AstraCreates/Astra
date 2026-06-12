"""Yelp Fusion API — competitor search, business data, reviews (read-only)."""
import logging
import requests
from backend.config import settings

logger = logging.getLogger(__name__)
_BASE = "https://api.yelp.com/v3"
_TIMEOUT = 15


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.yelp_api_key}", "accept": "application/json"}


def _not_configured() -> dict:
    return {"error": "YELP_API_KEY not configured"}


def _get(path: str, params: dict | None = None) -> dict:
    if not settings.yelp_api_key:
        return _not_configured()
    try:
        r = requests.get(f"{_BASE}{path}", headers=_headers(), params=params or {}, timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error("Yelp GET %s failed: %s", path, e)
        return {"error": str(e)}


def yelp_search_businesses(term: str, location: str, limit: int = 10, sort_by: str = "rating") -> dict:
    """Search local businesses by type and location. Good for competitor research."""
    data = _get("/businesses/search", {
        "term": term,
        "location": location,
        "limit": min(limit, 50),
        "sort_by": sort_by,
    })
    if "error" in data:
        return data
    businesses = [
        {
            "id": b.get("id"),
            "name": b.get("name"),
            "rating": b.get("rating"),
            "review_count": b.get("review_count"),
            "price": b.get("price"),
            "phone": b.get("phone"),
            "address": ", ".join((b.get("location") or {}).get("display_address") or []),
            "categories": [c.get("title") for c in (b.get("categories") or [])],
            "url": b.get("url"),
        }
        for b in (data.get("businesses") or [])
    ]
    return {"businesses": businesses, "count": len(businesses), "term": term, "location": location}


def yelp_get_business(business_id: str) -> dict:
    """Get detailed info for a specific business including hours, photos, attributes."""
    data = _get(f"/businesses/{business_id}")
    if "error" in data:
        return data
    return {
        "id": data.get("id"),
        "name": data.get("name"),
        "rating": data.get("rating"),
        "review_count": data.get("review_count"),
        "price": data.get("price"),
        "phone": data.get("phone"),
        "address": ", ".join((data.get("location") or {}).get("display_address") or []),
        "hours": data.get("hours"),
        "photos": (data.get("photos") or [])[:3],
        "categories": [c.get("title") for c in (data.get("categories") or [])],
        "url": data.get("url"),
        "is_claimed": data.get("is_claimed"),
        "attributes": data.get("attributes"),
    }


def yelp_get_reviews(business_id: str) -> dict:
    """Get top 3 reviews for a business (Yelp API limit)."""
    data = _get(f"/businesses/{business_id}/reviews", {"limit": 3, "sort_by": "yelp_sort"})
    if "error" in data:
        return data
    reviews = [
        {
            "rating": r.get("rating"),
            "text": (r.get("text") or "")[:400],
            "user": (r.get("user") or {}).get("name"),
            "time_created": r.get("time_created"),
        }
        for r in (data.get("reviews") or [])
    ]
    return {"reviews": reviews, "total": data.get("total", 0), "business_id": business_id}


def yelp_search_categories(location: str, category: str, limit: int = 20) -> dict:
    """Search by Yelp category alias (e.g. 'beautysvc', 'gyms', 'restaurants').
    Useful for market sizing and competitor landscape in a specific area."""
    data = _get("/businesses/search", {
        "categories": category,
        "location": location,
        "limit": min(limit, 50),
        "sort_by": "review_count",
    })
    if "error" in data:
        return data
    businesses = (data.get("businesses") or [])
    ratings = [b.get("rating", 0) for b in businesses if b.get("rating")]
    avg_rating = round(sum(ratings) / len(ratings), 1) if ratings else 0
    return {
        "category": category,
        "location": location,
        "total_found": data.get("total", 0),
        "avg_rating": avg_rating,
        "price_distribution": {
            p: sum(1 for b in businesses if b.get("price") == p)
            for p in ("$", "$$", "$$$", "$$$$")
        },
        "top_businesses": [
            {"name": b.get("name"), "rating": b.get("rating"), "review_count": b.get("review_count")}
            for b in businesses[:5]
        ],
    }
