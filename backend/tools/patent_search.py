import logging

logger = logging.getLogger(__name__)


def patent_search(query: str, assignee: str = None, max_results: int = 10) -> dict:
    """Search patents via Google Patents (DuckDuckGo site search). PatentsView is defunct."""
    try:
        from ddgs import DDGS
        search_query = f"site:patents.google.com {query}"
        if assignee:
            search_query += f" {assignee}"
        with DDGS() as ddgs:
            raw = list(ddgs.text(search_query, max_results=max_results))
        patents = []
        for r in raw:
            url = r.get("href", "")
            title = r.get("title", "")
            snippet = r.get("body", "")
            # Extract patent number from Google Patents URL (patents.google.com/patent/US...)
            import re
            num_match = re.search(r"/patent/([A-Z]{2}\d+)", url)
            patents.append({
                "number": num_match.group(1) if num_match else "",
                "title": title,
                "url": url,
                "abstract": snippet[:400],
                "assignee": assignee or "",
            })
        formatted_lines = [f"Patent search: {query}\n"]
        for p in patents:
            formatted_lines.append(f"- [{p['number'] or p['title']}]({p['url']}): {p['abstract'][:200]}")
        return {
            "query": query,
            "total_found": len(patents),
            "patents": patents,
            "formatted": "\n".join(formatted_lines),
        }
    except Exception as e:
        logger.error("patent_search failed: %s", e)
        return {"query": query, "patents": [], "error": str(e), "formatted": f"Patent search failed: {e}"}
