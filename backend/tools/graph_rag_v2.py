"""SQLite-backed GraphRAG v2 store.

This module intentionally keeps no process-global graph or vector index. Every
operation opens SQLite, performs bounded SQL work, and closes the connection.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any


def safe_founder_id(founder_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", founder_id)[:120] or "founder"


def graph_rag_root() -> Path:
    root = Path(".astra/graph_rag")
    root.mkdir(parents=True, exist_ok=True)
    return root


def graph_db_path(founder_id: str) -> Path:
    return graph_rag_root() / f"{safe_founder_id(founder_id)}.db"


def context_snapshot_path(founder_id: str) -> Path:
    directory = graph_rag_root() / safe_founder_id(founder_id)
    return directory / "context_snapshot.txt"


def graph_exists(founder_id: str) -> bool:
    return graph_db_path(founder_id).exists()


def read_context_snapshot(founder_id: str) -> str:
    path = context_snapshot_path(founder_id)
    if not path.exists():
        return ""
    try:
        return path.read_text()[:2_500]
    except Exception:
        return ""


def _connect(founder_id: str) -> sqlite3.Connection:
    conn = sqlite3.connect(graph_db_path(founder_id))
    conn.row_factory = sqlite3.Row
    return conn


def init_graph_store(founder_id: str) -> None:
    path = graph_db_path(founder_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(founder_id) as conn:
        conn.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS graph_nodes (
                id TEXT PRIMARY KEY,
                founder_id TEXT NOT NULL,
                name TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'entity',
                description TEXT NOT NULL DEFAULT '',
                importance REAL NOT NULL DEFAULT 1.0,
                community_id TEXT
            );
            CREATE TABLE IF NOT EXISTS graph_edges (
                id TEXT PRIMARY KEY,
                founder_id TEXT NOT NULL,
                source TEXT NOT NULL,
                target TEXT NOT NULL,
                relation TEXT NOT NULL DEFAULT 'related_to',
                weight REAL NOT NULL DEFAULT 1.0
            );
            CREATE TABLE IF NOT EXISTS graph_chunks (
                id TEXT PRIMARY KEY,
                founder_id TEXT NOT NULL,
                text TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                doc_hash TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS graph_chunks_fts USING fts5(
                text,
                title,
                content='graph_chunks',
                content_rowid='rowid'
            );
            CREATE TABLE IF NOT EXISTS graph_chunk_entities (
                chunk_id TEXT NOT NULL,
                node_id TEXT NOT NULL,
                PRIMARY KEY (chunk_id, node_id)
            );
            CREATE TABLE IF NOT EXISTS graph_communities (
                community_id TEXT PRIMARY KEY,
                member_node_ids TEXT NOT NULL DEFAULT '[]',
                summary TEXT NOT NULL DEFAULT '',
                built_at TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_graph_nodes_founder_name ON graph_nodes(founder_id, name);
            CREATE INDEX IF NOT EXISTS idx_graph_edges_founder_source ON graph_edges(founder_id, source);
            CREATE INDEX IF NOT EXISTS idx_graph_edges_founder_target ON graph_edges(founder_id, target);
            CREATE INDEX IF NOT EXISTS idx_graph_chunks_founder_hash ON graph_chunks(founder_id, doc_hash);
            """
        )


def _fts_query(query: str) -> str:
    terms = [t for t in re.findall(r"[a-zA-Z0-9_]+", query) if len(t) > 1]
    return " OR ".join(terms[:12]) or query.strip()


def graph_rag_search(founder_id: str, query: str, limit: int = 8) -> dict[str, Any]:
    """Search chunks with FTS5, seed entities by name, and expand two hops in SQL."""
    if not graph_exists(founder_id) or not query.strip():
        return {"ok": False, "query": query, "count": 0, "results": [], "formatted": ""}
    try:
        with _connect(founder_id) as conn:
            chunks = conn.execute(
                """
                SELECT c.id, c.text, c.source, c.title, bm25(graph_chunks_fts) AS rank
                FROM graph_chunks_fts
                JOIN graph_chunks c ON c.rowid = graph_chunks_fts.rowid
                WHERE graph_chunks_fts MATCH ? AND c.founder_id = ?
                ORDER BY rank
                LIMIT ?
                """,
                (_fts_query(query), founder_id, max(1, min(limit, 20))),
            ).fetchall()
            like_terms = [f"%{t}%" for t in re.findall(r"[a-zA-Z0-9_-]+", query) if len(t) > 2][:8]
            nodes: list[sqlite3.Row] = []
            if like_terms:
                where = " OR ".join(["lower(name) LIKE lower(?)"] * len(like_terms))
                nodes = conn.execute(
                    f"""
                    SELECT id, name, type, description, importance, community_id
                    FROM graph_nodes
                    WHERE founder_id = ? AND ({where})
                    ORDER BY importance DESC
                    LIMIT 12
                    """,
                    (founder_id, *like_terms),
                ).fetchall()
            chunk_entity_ids = [
                row["node_id"]
                for row in conn.execute(
                    """
                    SELECT DISTINCT ce.node_id
                    FROM graph_chunk_entities ce
                    JOIN graph_chunks c ON c.id = ce.chunk_id
                    WHERE c.founder_id = ? AND c.id IN (%s)
                    LIMIT 24
                    """ % ",".join("?" for _ in chunks),
                    (founder_id, *[c["id"] for c in chunks]),
                ).fetchall()
            ] if chunks else []
            seed_ids = list(dict.fromkeys([*(n["id"] for n in nodes), *chunk_entity_ids]))
            edges: list[sqlite3.Row] = []
            if seed_ids:
                placeholders = ",".join("?" for _ in seed_ids)
                edges = conn.execute(
                    f"""
                    SELECT id, source, target, relation, weight
                    FROM graph_edges
                    WHERE founder_id = ?
                      AND (source IN ({placeholders}) OR target IN ({placeholders}))
                    ORDER BY weight DESC
                    LIMIT 24
                    """,
                    (founder_id, *seed_ids, *seed_ids),
                ).fetchall()
            community_ids = list(dict.fromkeys([n["community_id"] for n in nodes if n["community_id"]]))
            communities: list[sqlite3.Row] = []
            if community_ids:
                communities = conn.execute(
                    "SELECT community_id, summary FROM graph_communities WHERE community_id IN (%s) LIMIT 6"
                    % ",".join("?" for _ in community_ids),
                    community_ids,
                ).fetchall()
    except Exception as exc:
        return {"ok": False, "query": query, "count": 0, "results": [], "formatted": "", "error": str(exc)}

    results = [
        {
            "id": row["id"],
            "source": row["source"],
            "title": row["title"],
            "content": row["text"],
            "snippet": row["text"][:420],
            "score": float(-row["rank"]),
        }
        for row in chunks
    ]
    lines = ["GraphRAG context:"] if results or nodes or communities else ["No graph context matched."]
    for row in chunks:
        lines.append(f"- [{row['source']}] {row['title']}: {row['text'][:360]}")
    for node in nodes[:8]:
        desc = node["description"] or node["type"]
        lines.append(f"- Entity: {node['name']} ({desc[:180]})")
    for edge in edges[:8]:
        lines.append(f"- Relationship: {edge['source']} {edge['relation']} {edge['target']}")
    for community in communities:
        lines.append(f"- Community: {community['summary'][:360]}")
    return {
        "ok": True,
        "query": query,
        "count": len(results),
        "results": results,
        "entities": [dict(row) for row in nodes],
        "relationships": [dict(row) for row in edges],
        "communities": [dict(row) for row in communities],
        "formatted": "\n".join(lines),
    }


def export_graph_visualization(founder_id: str) -> dict[str, Any]:
    if not graph_exists(founder_id):
        return {"ok": True, "founder_id": founder_id, "nodes": [], "edges": []}
    with _connect(founder_id) as conn:
        nodes = [dict(row) for row in conn.execute("SELECT * FROM graph_nodes WHERE founder_id = ? LIMIT 500", (founder_id,))]
        edges = [dict(row) for row in conn.execute("SELECT * FROM graph_edges WHERE founder_id = ? LIMIT 1000", (founder_id,))]
    return {"ok": True, "founder_id": founder_id, "nodes": nodes, "edges": edges}
