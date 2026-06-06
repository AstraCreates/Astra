"""Offline GraphRAG v2 ingestion from Company Brain JSON records."""
from __future__ import annotations

import hashlib
import itertools
import json
import re
import time
from collections import Counter, defaultdict
from typing import Any

from backend.tools.graph_rag_v2 import _connect, context_snapshot_path, init_graph_store


ENTITY_STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "company", "brain",
    "record", "records", "decision", "source", "truth", "session", "founder",
}


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


def _extract_entities(title: str, text: str, limit: int = 12) -> list[dict[str, str]]:
    candidates: Counter[str] = Counter()
    combined = f"{title}\n{text}"
    for match in re.findall(r"\b[A-Z][A-Za-z0-9&_.-]*(?:\s+[A-Z][A-Za-z0-9&_.-]*){0,3}\b", combined):
        name = match.strip(" .,:;")
        if len(name) > 2 and name.lower() not in ENTITY_STOPWORDS:
            candidates[name] += 3
    for word in re.findall(r"\b[a-zA-Z][a-zA-Z0-9_-]{3,}\b", combined.lower()):
        if word not in ENTITY_STOPWORDS:
            candidates[word] += 1
    entities = []
    for name, _count in candidates.most_common(limit):
        entity_type = "concept"
        if any(ch.isupper() for ch in name[1:]) or " " in name:
            entity_type = "proper_noun"
        entities.append({"name": name, "type": entity_type, "description": f"Mentioned in {title}"})
    return entities


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
