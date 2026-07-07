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

import networkx as nx

from backend.tools.graph_rag_v2 import _connect, context_snapshot_path, init_graph_store

logger = logging.getLogger(__name__)


# Zero-LLM-call relation typing (same approach as GBrain's edge extraction):
# scan the sentence containing both entity names for a connective keyword,
# and use that in place of the generic "co_mentions" label. Order matters —
# first keyword hit wins, so more specific relations are listed before
# generic ones that could also match the same sentence.
_RELATION_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("founded", ("co-founded", "founded", "started")),
    ("acquired", ("acquired", "bought out")),
    ("invested_in", ("invested in", "backed by", "funded by")),
    ("advises", ("advises", "advisor to", "mentors")),
    ("works_at", ("works at", "works for", "employed by", "joined")),
    ("partners_with", ("partners with", "partnered with", "partnership with")),
    ("competes_with", ("competitor of", "competes with", "rival to")),
    ("customer_of", ("customer of", "subscribed to", "purchased from")),
    ("decided", ("decided to", "decision to", "agreed to")),
]


def _infer_relation(name_a: str, name_b: str, text: str) -> str:
    """Best-effort relation label for a co-occurring entity pair, inferred from
    the sentence(s) that actually mention both — falls back to 'co_mentions'
    when no connective keyword is found. No LLM call."""
    low_a, low_b = name_a.lower(), name_b.lower()
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        low_sentence = sentence.lower()
        if low_a not in low_sentence or low_b not in low_sentence:
            continue
        for relation, keywords in _RELATION_PATTERNS:
            if any(kw in low_sentence for kw in keywords):
                return relation
    return "co_mentions"


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


def _is_value_fragment(name: str) -> bool:
    """True for raw metric/data literals leaked from doc text as nodes — hex
    color codes from a brand palette, dollar ranges and percent ranges from a
    pricing/metrics sheet. These are data POINTS, not named entities, and the
    other filters let them through because they're multi-word or digit-bearing."""
    n = name.strip()
    if n.startswith("#") or n.startswith("$"):
        return True
    if n[:1].isdigit() and "%" in n:
        return True
    return False


# Astra's own build-loop writes run-digest records with embedded telemetry
# JSON (elapsed_seconds, deadline_seconds, cost_usd, budget_exhausted) — the
# LLM extractor sometimes humanizes those field names into fake "concepts"
# once the underscore is gone, which slips past _is_internal_token's
# snake_case check. Not an exhaustive list; extend here if more show up.
_TELEMETRY_UNIT_WORDS = {"seconds", "usd", "ms", "minutes", "tokens", "rounds", "count"}
_TELEMETRY_PHRASES = {"budget exhausted", "tool rounds", "token count"}


def _is_telemetry_field(name: str) -> bool:
    low = name.strip().lower()
    if low in _TELEMETRY_PHRASES:
        return True
    words = low.split()
    return len(words) == 2 and words[1] in _TELEMETRY_UNIT_WORDS


def _is_generic_single(name: str) -> bool:
    """True for a bare single-token generic/stopword, or a machine identifier
    (the node-spam class)."""
    n = name.strip()
    if _is_internal_token(n) or _is_value_fragment(n) or _is_telemetry_field(n):
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
    if n.lower() in ENTITY_STOPWORDS or _is_value_fragment(n) or _is_telemetry_field(n):
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
        "'their', 'system', 'feature', 'data', 'users'. Do NOT return raw values "
        "like hex color codes ('#0EA5E9'), dollar ranges ('$10-50k'), or percent "
        "ranges ('15-20% churn') — name the METRIC itself instead (e.g. 'churn rate', "
        "'brand accent color'), not its value. "
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
    edge_relations: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    node_payloads: dict[str, dict[str, str]] = {}
    now = _now()

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
            record_updated_at = str(rec.get("updated_at") or now)
            combined = f"{title}\n{text}"
            entities = _extract_entities(title, text)
            node_ids = []
            names_by_id: dict[str, str] = {}
            for ent in entities:
                nid = _node_id(founder_id, ent["name"])
                node_ids.append(nid)
                names_by_id[nid] = ent["name"]
                node_mentions[nid] += 1
                node_payloads[nid] = ent
                conn.execute(
                    """
                    INSERT INTO graph_nodes(id, founder_id, name, type, description, importance, mentions, first_seen, last_seen)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        description = excluded.description,
                        mentions = graph_nodes.mentions + 1,
                        importance = graph_nodes.mentions + 1,
                        last_seen = excluded.last_seen
                    """,
                    (nid, founder_id, ent["name"], ent["type"], ent["description"], 1.0, 1.0, now, now),
                )
            for a, b in itertools.combinations(sorted(set(node_ids)), 2):
                edge_weights[(a, b)] += 1
                edge_relations[(a, b)][_infer_relation(names_by_id[a], names_by_id[b], combined)] += 1
            for idx, chunk in enumerate(_chunk_text(f"{title}\n{text}")):
                cid = _chunk_id(founder_id, doc_hash, idx)
                conn.execute(
                    """
                    INSERT OR IGNORE INTO graph_chunks(id, founder_id, text, source, title, doc_hash, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (cid, founder_id, chunk, source, title, doc_hash, record_updated_at),
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
            counts = edge_relations[(source, target)]
            specific = {k: v for k, v in counts.items() if k != "co_mentions"}
            relation = max(specific, key=specific.get) if specific else "co_mentions"
            conn.execute(
                """
                INSERT INTO graph_edges(id, founder_id, source, target, relation, weight, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    weight = graph_edges.weight + excluded.weight,
                    relation = excluded.relation,
                    last_seen = excluded.last_seen
                """,
                (eid, founder_id, source, target, relation, float(weight), now, now),
            )
        _update_importance(founder_id, conn)
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


def _load_graph(founder_id: str, conn) -> "nx.Graph":
    graph = nx.Graph()
    for row in conn.execute("SELECT id FROM graph_nodes WHERE founder_id = ?", (founder_id,)):
        graph.add_node(row["id"])
    for row in conn.execute(
        "SELECT source, target, weight FROM graph_edges WHERE founder_id = ?", (founder_id,)
    ):
        graph.add_edge(row["source"], row["target"], weight=float(row["weight"]))
    return graph


def _update_importance(founder_id: str, conn) -> None:
    """Real graph centrality (PageRank) blended with raw mention count, so a
    color hex code repeated across 3 brand docs no longer outranks a single
    real mention of the company name. Always derived fresh from the stable
    `mentions` counter (never from the previous importance value) — otherwise
    re-running this every sync would compound the same <=1.0 factor and decay
    every node's importance toward zero over time."""
    graph = _load_graph(founder_id, conn)
    if graph.number_of_edges() == 0:
        return
    scores = nx.pagerank(graph, weight="weight")
    if not scores:
        return
    peak = max(scores.values()) or 1.0
    for node_id, score in scores.items():
        conn.execute(
            "UPDATE graph_nodes SET importance = mentions * (0.5 + 0.5 * ?) WHERE id = ? AND founder_id = ?",
            (score / peak, node_id, founder_id),
        )


def _build_communities(founder_id: str, conn) -> int:
    graph = _load_graph(founder_id, conn)
    # Clear stale assignments first — an isolated node dropped from every
    # cluster this run must not keep pointing at a community_id from a
    # previous (possibly alphabet-bucket-era) run.
    conn.execute("UPDATE graph_nodes SET community_id = NULL WHERE founder_id = ?", (founder_id,))
    buckets: dict[str, list[str]] = defaultdict(list)
    if graph.number_of_edges() > 0:
        # Real modularity-based clustering (Louvain) — connected/related entities
        # end up in the same community instead of whatever shares a first letter.
        partition = nx.community.louvain_communities(graph, weight="weight", seed=0)
        for index, members in enumerate(partition):
            if members:
                buckets[f"cluster{index}"] = list(members)
    else:
        buckets = defaultdict(list)
    # Nodes with no edges yet (fresh single-mention entities) get no community —
    # a community of one isn't a cluster, and forcing one back into an
    # alphabet bucket is the exact bug this replaces.
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
