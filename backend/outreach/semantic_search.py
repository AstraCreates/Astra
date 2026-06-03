"""Free semantic-ish contact search.

No paid embedding model and no external vector DB: ranks contacts by TF-IDF
cosine similarity between the query and each contact's text (name, title,
company, industry, location). Good enough for "find contacts like <X>"
natural-language queries over a founder's own list.
"""
from __future__ import annotations

import math
import re
from collections import Counter

_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall((text or "").lower())


def _contact_text(c: dict) -> str:
    return " ".join(str(c.get(k, "") or "") for k in (
        "first_name", "last_name", "title", "company_name",
        "industry", "city", "state", "country", "seniority",
    ))


def rank_contacts(query: str, contacts: list[dict], limit: int = 25) -> list[dict]:
    """Return contacts ranked by relevance to the query (descending)."""
    q_tokens = _tokens(query)
    if not q_tokens or not contacts:
        return contacts[:limit]

    docs = [_tokens(_contact_text(c)) for c in contacts]
    n = len(docs)
    df: Counter = Counter()
    for doc in docs:
        for term in set(doc):
            df[term] += 1
    idf = {term: math.log((n + 1) / (cnt + 1)) + 1.0 for term, cnt in df.items()}

    def vec(tokens: list[str]) -> dict[str, float]:
        tf = Counter(tokens)
        return {t: (tf[t] / len(tokens)) * idf.get(t, math.log(n + 1) + 1.0) for t in tf}

    qv = vec(q_tokens)
    qnorm = math.sqrt(sum(w * w for w in qv.values())) or 1.0

    scored: list[tuple[float, dict]] = []
    for c, doc in zip(contacts, docs):
        if not doc:
            continue
        dv = vec(doc)
        dot = sum(w * dv.get(t, 0.0) for t, w in qv.items())
        dnorm = math.sqrt(sum(w * w for w in dv.values())) or 1.0
        score = dot / (qnorm * dnorm)
        if score > 0:
            scored.append((score, c))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:limit]]
