"""
Proprietary Engine — Integration point for all four compounding systems.

Usage:
    engine = ProprietaryEngine(founder_id="founder_001")
    pre_context = await engine.pre_run(goal="Build a SaaS for X")
    result = await orchestrator.run(goal=..., shared=pre_context)
    await engine.post_run(session_id=result["session_id"], results=result["results"])
"""

import logging
import time
from datetime import datetime
from typing import Any

from proprietary_agent.graph.decision_graph import DecisionGraph
from proprietary_agent.fingerprint.fingerprinter import Fingerprinter
from proprietary_agent.mirror.founder_mirror import FounderMirror, MirrorResult
from proprietary_agent.observer.silent_observer import SilentObserver

logger = logging.getLogger(__name__)


class ProprietaryEngine:
    def __init__(self, founder_id: str):
        self.founder_id = founder_id
        self.graph = DecisionGraph(founder_id)
        self.fingerprinter = Fingerprinter()
        self.mirror = FounderMirror()
        self.observer = SilentObserver(founder_id, graph=self.graph)
        self._run_start: float = 0.0
        self._agent_timings: dict[str, float] = {}
        self._agent_start_times: dict[str, float] = {}

    # ------------------------------------------------------------------ #
    # Pre-run
    # ------------------------------------------------------------------ #

    async def pre_run(self, goal: str, domains: list[str] | None = None) -> dict[str, Any]:
        """
        Load context from graph + fingerprint + observer alerts.
        Returns shared dict to inject into orchestrator.
        """
        self._run_start = time.monotonic()
        self._agent_timings = {}

        # Infer domains from goal if not provided
        if not domains:
            domains = self._extract_domains(goal)

        # Configure observer
        self.observer.configure(domains=domains, goals=[goal])

        # Gather context blocks
        graph_context = self.graph.format_context_block(goal)
        fingerprint_context = self.fingerprinter.format_match_block(goal, founder_id=self.founder_id)
        observer_context = self.observer.format_alert_block()

        # Compose pre-context block injected into agent system prompts
        blocks = [b for b in [graph_context, fingerprint_context, observer_context] if b]
        pre_context_text = "\n\n".join(blocks) if blocks else ""

        logger.info(
            "Pre-run context loaded for founder=%s | graph=%d nodes | fingerprints=%d",
            self.founder_id,
            self.graph.stats()["total_nodes"],
            self.fingerprinter.stats()["total_fingerprints"],
        )

        return {
            "proprietary_context": pre_context_text,
            "graph": self.graph,
            "fingerprinter": self.fingerprinter,
            "mirror": self.mirror,
            "founder_id": self.founder_id,
            "domains": domains,
        }

    # ------------------------------------------------------------------ #
    # Per-agent hooks
    # ------------------------------------------------------------------ #

    def on_agent_start(self, agent: str):
        self._agent_start_times[agent] = time.monotonic()

    def on_agent_done(self, agent: str, output: str, session_id: str) -> MirrorResult:
        """
        Run Mirror review after each agent.
        Write decision node to graph.
        Track timing.
        Returns MirrorResult — caller handles flag/block logic.
        """
        elapsed = time.monotonic() - self._agent_start_times.get(agent, time.monotonic())
        self._agent_timings[agent] = round(elapsed, 2)

        # Mirror review
        result = self.mirror.review(agent=agent, output=output)

        # Write to graph
        node_id = self.graph.add_decision(
            agent=agent,
            action=f"completed run for session {session_id}",
            reason=f"agent finished with output length={len(output)}",
            outcome=f"mirror={result.verdict}",
            outcome_score={"pass": 1.0, "flag": 0.5, "block": 0.0}.get(result.verdict, 0.5),
            session_id=session_id,
        )
        self.graph.add_mirror_review(
            decision_id=node_id,
            verdict=result.verdict,
            critique=result.critique,
            questions=result.questions,
            revised_recommendation=result.revised_recommendation,
        )

        logger.info(
            "Mirror [%s]: %s | timing=%.1fs",
            agent,
            result.verdict.upper(),
            elapsed,
        )
        return result

    # ------------------------------------------------------------------ #
    # Post-run
    # ------------------------------------------------------------------ #

    async def post_run(
        self,
        session_id: str,
        goal: str,
        results: dict[str, Any],
        success_score: float | None = None,
    ):
        """
        Store execution fingerprint.
        Compute success score if not provided.
        """
        agents_used = list(results.keys())
        tool_outcomes: dict[str, str] = {}

        # Extract tool outcomes from agent results
        for agent, res in results.items():
            if isinstance(res, dict):
                for tool, outcome in res.get("tool_outcomes", {}).items():
                    tool_outcomes[tool] = outcome

        # Default success score: fraction of agents with mirror pass
        if success_score is None:
            pass_count = sum(
                1 for r in results.values()
                if isinstance(r, dict) and r.get("mirror_verdict") == "pass"
            )
            success_score = pass_count / max(len(agents_used), 1)

        total_time = time.monotonic() - self._run_start

        self.fingerprinter.store(
            session_id=session_id,
            founder_id=self.founder_id,
            goal=goal,
            agents_used=agents_used,
            tool_outcomes=tool_outcomes,
            timing={**self._agent_timings, "_total": round(total_time, 2)},
            success_score=success_score,
        )

        logger.info(
            "Post-run fingerprint stored | session=%s | score=%.2f | time=%.1fs",
            session_id,
            success_score,
            total_time,
        )

    # ------------------------------------------------------------------ #
    # Observer control
    # ------------------------------------------------------------------ #

    def start_observer(self):
        self.observer.start()

    def stop_observer(self):
        self.observer.stop()

    # ------------------------------------------------------------------ #
    # Utilities
    # ------------------------------------------------------------------ #

    def _extract_domains(self, goal: str) -> list[str]:
        """Naive keyword extraction for observer domain targeting."""
        stopwords = {"a", "an", "the", "for", "to", "of", "and", "or", "with", "build", "create", "make"}
        words = [w.lower().strip(".,") for w in goal.split() if len(w) > 3]
        return [w for w in words if w not in stopwords][:5]

    def stats(self) -> dict:
        return {
            "founder_id": self.founder_id,
            "graph": self.graph.stats(),
            "fingerprints": self.fingerprinter.stats(),
            "observer": self.observer.stats(),
        }
