"""
Examples library — searchable code snippets, templates, and patterns.
Agents call search_examples(query) to pull relevant examples rather than
having everything injected into their system prompt.
"""
import os
import re
from pathlib import Path

_LIBRARY_DIR = Path(__file__).parent.parent / "examples"

# Maps specialist role prefixes to preferred categories
_AGENT_CATEGORY_HINTS: dict[str, list[str]] = {
    "technical":          ["auth", "payments", "database", "deployment", "design"],
    "technical_scaffold": ["auth", "payments", "database", "deployment", "design"],
    "technical_infra":    ["deployment", "database"],
    "technical_data":     ["database"],
    "web":                ["design", "marketing", "deployment", "auth"],
    "design":             ["design", "marketing"],
    "marketing":          ["marketing", "email", "sales"],
    "marketing_outreach": ["email", "sales", "marketing"],
    "marketing_seo":      ["marketing", "design"],
    "marketing_content":  ["marketing", "email"],
    "marketing_paid":     ["marketing"],
    "sales":              ["sales", "email", "marketing"],
    "sales_pipeline":     ["sales", "email"],
    "sales_enablement":   ["sales", "email"],
    "research":           ["research"],
    "research_market":    ["research"],
    "research_financial": ["research"],
    "research_regulatory":["research", "legal"],
    "legal":              ["legal"],
    "legal_docs":         ["legal"],
    "legal_entity":       ["legal"],
    "legal_ip":           ["legal", "research"],
    "ops":                ["payments", "email", "legal", "database"],
    "finance_model":      ["research"],
    "finance_fundraise":  ["research", "legal"],
}


def _load_examples() -> list[dict]:
    """Load all example files from the library."""
    examples: list[dict] = []
    if not _LIBRARY_DIR.exists():
        return examples
    for path in sorted(_LIBRARY_DIR.rglob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue

        # Parse frontmatter
        title, tags, category, applies_to = "", [], "", []
        if text.startswith("---"):
            end = text.find("---", 3)
            if end != -1:
                fm = text[3:end]
                body = text[end + 3:].strip()
                for line in fm.splitlines():
                    line = line.strip()
                    if line.startswith("title:"):
                        title = line[6:].strip().strip('"')
                    elif line.startswith("category:"):
                        category = line[9:].strip()
                    elif line.startswith("tags:"):
                        raw = re.findall(r"[\w.\-/+]+", line[5:])
                        tags = raw
                    elif line.startswith("applies_to:"):
                        raw = re.findall(r"[\w_]+", line[11:])
                        applies_to = raw
            else:
                body = text
        else:
            body = text

        examples.append({
            "path": str(path.relative_to(_LIBRARY_DIR)),
            "category": category or path.parent.name,
            "title": title or path.stem.replace("_", " ").title(),
            "tags": tags,
            "applies_to": applies_to,
            "content": body,
        })
    return examples


def search_examples(
    query: str = "",
    category: str = "",
    agent_role: str = "",
    max_results: int = 3,
) -> dict:
    """
    Search the examples library for code patterns, templates, and scaffolds.

    Use this before writing code for a task you haven't done before — auth,
    payments, email, legal templates, etc. Returns matching examples with
    full content so you can copy-paste the working pattern.

    Args:
        query:      What you're looking for. E.g. "nextauth google oauth",
                    "stripe checkout webhook", "supabase rls schema",
                    "cold email b2b sequence", "privacy policy gdpr".
        category:   Narrow to a category: auth, payments, email, database,
                    deployment, legal, sales, research, design, marketing.
                    Leave blank to search all.
        agent_role: Your agent role name (e.g. "technical", "marketing_outreach").
                    Boosts results relevant to your specialty.
        max_results: Max examples to return (default 3, max 5).

    Returns:
        {"examples": [{"title", "category", "path", "content"}, ...], "count": int}
    """
    if not query:
        # Real production bug: models called search_examples() with no
        # query, hitting a raw TypeError repeatedly with zero corrective
        # signal — fall back to the category/agent_role if given, since
        # that's still a usable (if broad) search, and only error if
        # nothing at all was passed.
        query = category or agent_role
        if not query:
            return {"examples": [], "count": 0, "error": "search_examples requires 'query' (e.g. search_examples('nextauth google oauth'))"}
    max_results = min(max_results, 5)
    examples = _load_examples()
    if not examples:
        return {"examples": [], "count": 0, "error": "Examples library not found"}

    # Tokenise query
    query_tokens = set(re.findall(r"\w+", query.lower()))

    # Preferred categories for this agent
    preferred_cats = set(_AGENT_CATEGORY_HINTS.get(agent_role, []))

    scored: list[tuple[float, dict]] = []
    for ex in examples:
        # Category filter
        if category and ex["category"] != category:
            continue

        # Scoring: token overlap across title + tags + content header
        searchable = (
            ex["title"].lower() + " " +
            " ".join(ex["tags"]) + " " +
            ex["category"].lower() + " " +
            ex["content"][:500].lower()
        )
        searchable_tokens = set(re.findall(r"\w+", searchable))
        overlap = len(query_tokens & searchable_tokens)
        if overlap == 0:
            continue

        # Boost for agent-relevant categories
        cat_boost = 1.5 if ex["category"] in preferred_cats else 1.0
        # Boost for applies_to match
        role_boost = 1.3 if agent_role in ex.get("applies_to", []) else 1.0

        score = overlap * cat_boost * role_boost
        scored.append((score, ex))

    scored.sort(key=lambda x: x[0], reverse=True)
    results = [ex for _, ex in scored[:max_results]]

    return {
        "examples": [
            {"title": e["title"], "category": e["category"], "path": e["path"], "content": e["content"]}
            for e in results
        ],
        "count": len(results),
    }


def list_example_categories(agent_role: str = "") -> dict:
    """
    List all available example categories in the library.

    Args:
        agent_role: Your agent role — returns preferred categories first.

    Returns:
        {"categories": [...], "preferred_for_your_role": [...]}
    """
    examples = _load_examples()
    cats = sorted({e["category"] for e in examples})
    preferred = _AGENT_CATEGORY_HINTS.get(agent_role, [])
    return {
        "categories": cats,
        "preferred_for_your_role": [c for c in preferred if c in cats],
    }
