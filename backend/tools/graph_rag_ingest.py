"""Offline GraphRAG v2 ingestion from Company Brain JSON records."""
from __future__ import annotations

import hashlib
import itertools
import json
import logging
import re
import time
from collections import Counter, defaultdict
from typing import Any

from backend.tools.graph_rag_v2 import _connect, context_snapshot_path, init_graph_store

logger = logging.getLogger(__name__)


ENTITY_STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "company", "brain",
    "record", "records", "decision", "source", "truth", "session", "founder",
}

# Single generic words that are NOT concepts — these polluted the graph as
# per-word nodes. Blocked for single-token candidates; multi-word phrases and
# proper nouns are unaffected (e.g. "data pipeline" / "Webull" still pass).
GENERIC_WORDS = {
    "website", "websites", "online", "their", "system", "systems", "feature",
    "features", "data", "users", "user", "product", "products", "service",
    "services", "platform", "platforms", "market", "markets", "business",
    "businesses", "customer", "customers", "tool", "tools", "team", "teams",
    "page", "pages", "content", "value", "growth", "model", "models", "plan",
    "plans", "goal", "goals", "time", "people", "things", "thing", "based",
    "using", "real", "make", "build", "need", "needs", "want", "help", "work",
    "works", "good", "great", "best", "more", "most", "other", "into", "than",
    "they", "them", "have", "will", "your", "about", "which", "these", "those",
}


# Standalone tokens that are platform internals (workspace names, agent/workstream
# codes, the test org) — not company knowledge. Matched case-insensitively for
# SINGLE-token candidates only; multi-word phrases like "primary research" survive.
INTERNAL_NAMES = {
    "primary", "astratesting", "agent", "founder", "workspace", "session",
    "technical", "research", "sales", "marketing", "design", "legal", "ops",
    "web", "finance", "specialist", "orchestrator", "copilot",
    "auto-logged", "untitled", "n/a", "tbd",
}


def _is_internal_token(name: str) -> bool:
    """True for machine identifiers leaked from agent-output JSON — repo/workspace
    names, snake_case field/tool keys, agent codes, domain fragments, hash suffixes.
    These are never business concepts. Multi-word phrases and proper-noun tech
    (e.g. 'Next.js') are preserved."""
    n = name.strip()
    if " " in n:
        return False                       # real multi-word concept
    if n.lower() in INTERNAL_NAMES:        # workspace/agent/org internal name
        return True
    if "/" in n:                           # path: astratesting/goon-44a472
        return True
    if re.search(r"-[0-9a-f]{6,}$", n.lower()):   # workspace/repo hash suffix
        return True
    if "_" in n and n.lower() == n:        # snake_case key: market_brief, t_technical
        return True
    if "." in n and n.lower() == n:        # lowercase domain fragment: nip.io
        return True
    if re.fullmatch(r"t_[a-z]+", n):       # agent code: t_technical
        return True
    return False


def _is_generic_single(name: str) -> bool:
    """True for a bare single-token generic/stopword, or a machine identifier
    (the node-spam class)."""
    n = name.strip()
    if _is_internal_token(n):
        return True
    if " " in n:
        return False
    low = n.lower()
    return low in GENERIC_WORDS or low in ENTITY_STOPWORDS


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _doc_hash(record: dict[str, Any]) -> str:
    raw = json.dumps(
        {
            "id": record.get("id"),
            "title": record.get("title"),
            "content": record.get("content") or record.get("text"),
            "updated_at": record.get("updated_at"),
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def _chunk_text(text: str, size: int = 1_200, overlap: int = 160) -> list[str]:
    clean = re.sub(r"\s+", " ", text or "").strip()
    if not clean:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(clean):
        chunks.append(clean[start:start + size])
        if start + size >= len(clean):
            break
        start += max(1, size - overlap)
    return chunks


_VALID_ENTITY_TYPES = {"person", "org", "product", "technology", "metric", "location", "concept"}


def _clean_entity_name(name: str) -> str:
    return re.sub(r"\s+", " ", str(name or "")).strip(" .,:;\"'`-")


def _is_meaningful_entity(name: str) -> bool:
    """Reject the single-generic-word noise that polluted the graph. Keep named
    entities (proper nouns, products with caps/digits) and multi-word concepts."""
    n = _clean_entity_name(name)
    if len(n) < 3 or len(n) > 60:
        return False
    if n.lower() in ENTITY_STOPWORDS:
        return False
    if " " in n:                                  # multi-word concept
        return True
    if n[0].isupper():                            # proper noun (Goon, Bloomberg, GPT4)
        return True
    if any(c.isdigit() for c in n):               # versioned term (v2, h100)
        return True
    return False                                  # bare single lowercase word → drop


def _llm_extract_entities(title: str, combined: str, limit: int) -> list[dict[str, str]]:
    """Pull real entities + multi-word concepts via the LLM (one call per record)."""
    try:
        from backend.tools._llm import generate
    except Exception:
        return []
    prompt = (
        "Extract the key ENTITIES and CONCEPTS from this company-knowledge text for a "
        "knowledge graph. Return named entities (people, companies, products, technologies, "
        "places), metrics, and meaningful MULTI-WORD concepts (e.g. 'confidence scoring', "
        "'retail investors'). Do NOT return generic single words like 'website', 'online', "
        "'their', 'system', 'feature', 'data', 'users'. "
        f"At most {limit} items, most important first.\n\n"
        f"TITLE: {title}\nTEXT: {combined[:3000]}\n\n"
        'Respond with ONLY a JSON array: '
        '[{"name": "...", "type": "person|org|product|technology|metric|location|concept"}]'
    )
    try:
        raw = generate(prompt, max_tokens=500, model="fast", temperature=0.2, json_mode=True)
    except Exception as exc:
        logger.warning("graph_rag entity extraction LLM call failed for %r: %s", title[:80], exc)
        return []
    m = re.search(r"\[.*\]", raw or "", re.DOTALL)
    if not m:
        logger.warning("graph_rag entity extraction returned no JSON array for %r", title[:80])
        return []
    try:
        items = json.loads(m.group(0))
    except Exception as exc:
        logger.warning("graph_rag entity extraction JSON parse failed for %r: %s", title[:80], exc)
        return []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        name = _clean_entity_name(it.get("name"))
        # Trust the LLM's typing, but drop empties, generics, and dupes.
        if not name or len(name) < 3 or _is_generic_single(name):
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        etype = str(it.get("type") or "concept").lower()
        if etype not in _VALID_ENTITY_TYPES:
            etype = "concept"
        out.append({"name": name, "type": etype, "description": f"Mentioned in {title}"})
        if len(out) >= limit:
            break
    return out


def _heuristic_entities(title: str, combined: str, limit: int) -> list[dict[str, str]]:
    """LLM-free fallback: capitalized proper-noun phrases + multi-word terms ONLY.
    Never emits bare single lowercase words (the original node-spam bug)."""
    candidates: Counter[str] = Counter()
    for match in re.findall(r"\b[A-Z][A-Za-z0-9&_-]*(?:[ ]+[A-Z][A-Za-z0-9&_-]*){0,3}\b", combined):
        name = _clean_entity_name(match)
        if _is_meaningful_entity(name):
            candidates[name] += 1
    entities = []
    for name, _count in candidates.most_common(limit):
        etype = "org" if (" " in name or any(c.isupper() for c in name[1:])) else "concept"
        entities.append({"name": name, "type": etype, "description": f"Mentioned in {title}"})
    return entities


def _extract_entities(title: str, text: str, limit: int = 12) -> list[dict[str, str]]:
    """Real entities/concepts only — no per-word node spam.

    LLM extraction (concepts + named entities) first; strict heuristic fallback
    (proper-noun / multi-word phrases) if the LLM is unavailable. Every candidate
    must pass _is_meaningful_entity, so single generic words never become nodes."""
    combined = f"{title}\n{text}".strip()
    if not combined:
        return []
    ents = _llm_extract_entities(title, combined, limit)
    if not ents:
        ents = _heuristic_entities(title, combined, limit)
    # Final backstop regardless of source: never emit a generic single word.
    return [e for e in ents if not _is_generic_single(e["name"]) and len(e["name"]) >= 3][:limit]


def _node_id(founder_id: str, name: str) -> str:
    digest = hashlib.sha1(f"{founder_id}:{name.lower()}".encode()).hexdigest()[:16]
    return f"node_{digest}"


def _chunk_id(founder_id: str, doc_hash: str, index: int) -> str:
    return f"chunk_{hashlib.sha1(f'{founder_id}:{doc_hash}:{index}'.encode()).hexdigest()[:16]}"


def run_graph_rag_sync(founder_id: str) -> dict[str, Any]:
    """Build/update the founder's SQLite graph from existing company-brain JSON."""
    from backend.tools.company_brain import get_company_brain

    brain = get_company_brain(founder_id)
    records = [
        rec for rec in brain.get("records", [])
        if rec.get("status", "active") == "active" and (rec.get("content") or rec.get("text") or rec.get("title"))
    ]
    init_graph_store(founder_id)
    inserted_chunks = 0
    node_mentions: Counter[str] = Counter()
    edge_weights: Counter[tuple[str, str]] = Counter()
    node_payloads: dict[str, dict[str, str]] = {}

    with _connect(founder_id) as conn:
        for rec in records:
            doc_hash = _doc_hash(rec)
            exists = conn.execute(
                "SELECT 1 FROM graph_chunks WHERE founder_id = ? AND doc_hash = ? LIMIT 1",
                (founder_id, doc_hash),
            ).fetchone()
            if exists:
                continue
            title = str(rec.get("title") or rec.get("source") or "Untitled")
            source = str(rec.get("source") or "")
            text = str(rec.get("content") or rec.get("text") or "")
            entities = _extract_entities(title, text)
            node_ids = []
            for ent in entities:
                nid = _node_id(founder_id, ent["name"])
                node_ids.append(nid)
                node_mentions[nid] += 1
                node_payloads[nid] = ent
                conn.execute(
                    """
                    INSERT INTO graph_nodes(id, founder_id, name, type, description, importance)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        description = excluded.description,
                        importance = graph_nodes.importance + 1
                    """,
                    (nid, founder_id, ent["name"], ent["type"], ent["description"], 1.0),
                )
            for a, b in itertools.combinations(sorted(set(node_ids)), 2):
                edge_weights[(a, b)] += 1
            for idx, chunk in enumerate(_chunk_text(f"{title}\n{text}")):
                cid = _chunk_id(founder_id, doc_hash, idx)
                conn.execute(
                    """
                    INSERT OR IGNORE INTO graph_chunks(id, founder_id, text, source, title, doc_hash)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (cid, founder_id, chunk, source, title, doc_hash),
                )
                conn.execute(
                    """
                    INSERT INTO graph_chunks_fts(rowid, text, title)
                    SELECT rowid, text, title FROM graph_chunks WHERE id = ?
                    """,
                    (cid,),
                )
                inserted_chunks += 1
                for nid in set(node_ids):
                    conn.execute(
                        "INSERT OR IGNORE INTO graph_chunk_entities(chunk_id, node_id) VALUES (?, ?)",
                        (cid, nid),
                    )
        for (source, target), weight in edge_weights.items():
            eid = f"edge_{hashlib.sha1(f'{source}:{target}'.encode()).hexdigest()[:16]}"
            conn.execute(
                """
                INSERT INTO graph_edges(id, founder_id, source, target, relation, weight)
                VALUES (?, ?, ?, ?, 'co_mentions', ?)
                ON CONFLICT(id) DO UPDATE SET weight = graph_edges.weight + excluded.weight
                """,
                (eid, founder_id, source, target, float(weight)),
            )
        communities = _build_communities(founder_id, conn)
        _write_snapshot(founder_id, conn)
        conn.commit()

    return {
        "ok": True,
        "founder_id": founder_id,
        "record_count": len(records),
        "inserted_chunks": inserted_chunks,
        "node_count": len(node_payloads),
        "edge_count": len(edge_weights),
        "community_count": communities,
        "snapshot_path": str(context_snapshot_path(founder_id)),
    }


def rebuild_graph_rag(founder_id: str) -> dict[str, Any]:
    """Wipe the founder's graph DB and re-ingest from brain JSON with the CURRENT
    extractor. Use this to clear legacy single-word node spam — the graph is
    derived from the brain records (source of truth), so nothing is lost."""
    from pathlib import Path as _Path
    from backend.tools.graph_rag_v2 import graph_db_path
    base = str(graph_db_path(founder_id))
    for suffix in ("", "-wal", "-shm"):
        try:
            _Path(base + suffix).unlink()
        except FileNotFoundError:
            pass
        except Exception:
            pass
    return run_graph_rag_sync(founder_id)


def _build_communities(founder_id: str, conn) -> int:
    rows = conn.execute("SELECT id, name FROM graph_nodes WHERE founder_id = ?", (founder_id,)).fetchall()
    buckets: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        key = str(row["name"][:1] or "x").lower()
        buckets[key].append(row["id"])
    built_at = _now()
    count = 0
    for key, members in buckets.items():
        if not members:
            continue
        cid = f"community_{key}"
        names = [
            row["name"]
            for row in conn.execute(
                "SELECT name FROM graph_nodes WHERE id IN (%s) ORDER BY importance DESC LIMIT 8"
                % ",".join("?" for _ in members),
                members,
            ).fetchall()
        ]
        summary = "Related company-brain entities: " + ", ".join(names)
        conn.execute(
            """
            INSERT INTO graph_communities(community_id, member_node_ids, summary, built_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(community_id) DO UPDATE SET
                member_node_ids = excluded.member_node_ids,
                summary = excluded.summary,
                built_at = excluded.built_at
            """,
            (cid, json.dumps(members), summary, built_at),
        )
        conn.execute(
            "UPDATE graph_nodes SET community_id = ? WHERE id IN (%s)" % ",".join("?" for _ in members),
            (cid, *members),
        )
        count += 1
    return count


def _write_snapshot(founder_id: str, conn) -> None:
    nodes = conn.execute(
        "SELECT name, type, description FROM graph_nodes WHERE founder_id = ? ORDER BY importance DESC LIMIT 12",
        (founder_id,),
    ).fetchall()
    communities = conn.execute(
        "SELECT summary FROM graph_communities ORDER BY built_at DESC LIMIT 4"
    ).fetchall()
    edges = conn.execute(
        "SELECT source, target, relation FROM graph_edges WHERE founder_id = ? ORDER BY weight DESC LIMIT 10",
        (founder_id,),
    ).fetchall()
    lines = ["Company graph snapshot:"]
    if nodes:
        lines.append("Top entities: " + "; ".join(f"{n['name']} ({n['type']})" for n in nodes))
    for community in communities:
        lines.append(community["summary"])
    for edge in edges:
        lines.append(f"{edge['source']} {edge['relation']} {edge['target']}")
    path = context_snapshot_path(founder_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines)[:2_500])
