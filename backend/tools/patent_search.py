import logging
import requests

logger = logging.getLogger(__name__)

_PATENTSVIEW_URL = "https://api.patentsview.org/patents/query"


def patent_search(query: str, assignee: str = None, max_results: int = 10) -> dict:
    """Search USPTO patents via PatentsView public API (no key required)."""
    try:
        q_clause: dict = {"_text_any": {"patent_title": query, "patent_abstract": query}}
        if assignee:
            q_clause = {"_and": [q_clause, {"_contains": {"assignee_organization": assignee}}]}

        payload = {
            "q": q_clause,
            "f": ["patent_number", "patent_title", "patent_date", "patent_abstract",
                  "assignee_organization", "inventor_last_name"],
            "o": {"per_page": max_results, "sort_by": "patent_date", "sort_order": "desc"},
        }
        resp = requests.post(_PATENTSVIEW_URL, json=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        patents = data.get("patents") or []
        return {
            "query": query,
            "total_found": data.get("total_patent_count", 0),
            "patents": [
                {
                    "number": p.get("patent_number"),
                    "title": p.get("patent_title"),
                    "date": p.get("patent_date"),
                    "assignee": (p.get("assignees") or [{}])[0].get("assignee_organization"),
                    "abstract": (p.get("patent_abstract") or "")[:300],
                }
                for p in patents
            ],
        }
    except Exception as e:
        logger.error("patent_search failed: %s", e)
        return {"query": query, "patents": [], "error": str(e)}
