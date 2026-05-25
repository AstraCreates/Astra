"""
Causal Decision Graph — System A.

Persistent NetworkX directed graph tracking every agent decision,
its causes, and outcomes. Stored as JSON per founder on disk.
"""

import json
import logging
import os
import uuid
from datetime import datetime
from typing import Any

import networkx as nx

logger = logging.getLogger(__name__)

_STORE_DIR = os.environ.get("ASTRA_GRAPH_DIR", os.path.expanduser("~/agent-workspace/graphs"))


class DecisionGraph:
    NODE_TYPES = {"decision", "entity", "outcome", "agent_action", "external_event"}
    EDGE_TYPES = {"triggered_by", "led_to", "contradicts", "supports", "invalidates"}

    def __init__(self, founder_id: str):
        self.founder_id = founder_id
        self._path = os.path.join(_STORE_DIR, f"{founder_id}.json")
        self.G: nx.DiGraph = nx.DiGraph()
        self._load()

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #

    def _load(self):
        os.makedirs(_STORE_DIR, exist_ok=True)
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path) as f:
                data = json.load(f)
            self.G = nx.node_link_graph(data, directed=True, multigraph=False)
        except Exception as e:
            logger.warning("Graph load failed (%s) — starting fresh", e)

    def save(self):
        try:
            data = nx.node_link_data(self.G)
            with open(self._path, "w") as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            logger.error("Graph save failed: %s", e)

    # ------------------------------------------------------------------ #
    # Write
    # ------------------------------------------------------------------ #

    def add_decision(
        self,
        *,
        agent: str,
        action: str,
        reason: str,
        outcome: str | None = None,
        outcome_score: float | None = None,
        session_id: str | None = None,
        parent_ids: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> str:
        node_id = str(uuid.uuid4())
        self.G.add_node(
            node_id,
            type="decision",
            agent=agent,
            action=action,
            reason=reason,
            outcome=outcome,
            outcome_score=outcome_score,
            session_id=session_id,
            tags=tags or [],
            timestamp=datetime.utcnow().isoformat(),
        )
        for pid in parent_ids or []:
            if self.G.has_node(pid):
                self.G.add_edge(pid, node_id, type="led_to")
        self.save()
        return node_id

    def add_external_event(
        self,
        *,
        source: str,
        summary: str,
        relevance_score: float,
        url: str | None = None,
        content_hash: str | None = None,
    ) -> str:
        node_id = str(uuid.uuid4())
        self.G.add_node(
            node_id,
            type="external_event",
            source=source,
            summary=summary,
            relevance_score=relevance_score,
            url=url,
            content_hash=content_hash,
            timestamp=datetime.utcnow().isoformat(),
        )
        self.save()
        return node_id

    def add_mirror_review(
        self,
        *,
        decision_id: str,
        verdict: str,
        critique: str,
        questions: list[str],
        revised_recommendation: str | None = None,
    ) -> str:
        node_id = str(uuid.uuid4())
        self.G.add_node(
            node_id,
            type="agent_action",
            subtype="mirror_review",
            verdict=verdict,
            critique=critique,
            questions=questions,
            revised_recommendation=revised_recommendation,
            timestamp=datetime.utcnow().isoformat(),
        )
        if self.G.has_node(decision_id):
            self.G.add_edge(decision_id, node_id, type="mirror_review")
        self.save()
        return node_id

    def update_outcome(self, node_id: str, outcome: str, score: float):
        if self.G.has_node(node_id):
            self.G.nodes[node_id]["outcome"] = outcome
            self.G.nodes[node_id]["outcome_score"] = score
            self.save()

    # ------------------------------------------------------------------ #
    # Query
    # ------------------------------------------------------------------ #

    def query_relevant(self, context: str, agent: str | None = None, limit: int = 5) -> list[dict]:
        """Return up to `limit` nodes most relevant to `context` (keyword overlap)."""
        context_words = set(context.lower().split())
        scored: list[tuple[float, dict]] = []

        for nid, data in self.G.nodes(data=True):
            if data.get("type") not in ("decision", "external_event"):
                continue
            if agent and data.get("agent") and data["agent"] != agent:
                continue

            node_text = " ".join(
                str(v) for k, v in data.items()
                if k in ("action", "reason", "outcome", "summary") and v
            ).lower()
            node_words = set(node_text.split())
            overlap = len(context_words & node_words) / max(len(context_words), 1)
            if overlap > 0:
                scored.append((overlap, {**data, "_id": nid}))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [d for _, d in scored[:limit]]

    def format_context_block(self, context: str, agent: str | None = None) -> str:
        """Return a human-readable block of relevant prior decisions for agent prompts."""
        nodes = self.query_relevant(context, agent=agent)
        if not nodes:
            return ""

        lines = ["[Decision Graph — Prior Context]"]
        for n in nodes:
            ts = n.get("timestamp", "")[:10]
            if n.get("type") == "decision":
                lines.append(
                    f"• [{ts}] {n.get('agent','?')} decided: {n.get('action','')}"
                    f"\n  Reason: {n.get('reason','')}"
                    + (f"\n  Outcome: {n.get('outcome')} (score {n.get('outcome_score')})" if n.get("outcome") else "")
                )
            elif n.get("type") == "external_event":
                lines.append(
                    f"• [{ts}] External signal ({n.get('source','?')}): {n.get('summary','')}"
                    f"\n  Relevance: {n.get('relevance_score', 0):.2f}"
                )
        return "\n".join(lines)

    def get_decisions_by_agent(self, agent: str) -> list[dict]:
        return [
            {**d, "_id": nid}
            for nid, d in self.G.nodes(data=True)
            if d.get("type") == "decision" and d.get("agent") == agent
        ]

    def stats(self) -> dict:
        return {
            "total_nodes": self.G.number_of_nodes(),
            "total_edges": self.G.number_of_edges(),
            "decisions": sum(1 for _, d in self.G.nodes(data=True) if d.get("type") == "decision"),
            "external_events": sum(1 for _, d in self.G.nodes(data=True) if d.get("type") == "external_event"),
        }
