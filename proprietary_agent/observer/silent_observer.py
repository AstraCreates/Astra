"""
Silent Observer — System E.

Background agent that monitors competitor activity, regulatory changes,
funding announcements, and industry news. Surfaces proactive alerts.
Runs as an asyncio background task, default 6-hour polling interval.
"""

import asyncio
import hashlib
import logging
import os
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)

_POLL_INTERVAL = int(os.environ.get("OBSERVER_POLL_SECONDS", 21600))  # 6 hours


@dataclass
class ObserverAlert:
    summary: str
    source: str
    url: str | None
    relevance_score: float
    suggested_action: str
    content_hash: str
    timestamp: str


class SilentObserver:
    def __init__(self, founder_id: str, graph=None):
        self.founder_id = founder_id
        self.graph = graph  # DecisionGraph instance — for context + writing external_event nodes
        self._seen_hashes: set[str] = set()
        self._task: asyncio.Task | None = None
        self._pending_alerts: list[ObserverAlert] = []
        self._active_domains: list[str] = []
        self._active_goals: list[str] = []

    # ------------------------------------------------------------------ #
    # Configuration
    # ------------------------------------------------------------------ #

    def configure(self, domains: list[str], goals: list[str]):
        """Update what the observer is watching. Called before each run."""
        self._active_domains = domains
        self._active_goals = goals

    # ------------------------------------------------------------------ #
    # Background loop
    # ------------------------------------------------------------------ #

    def start(self):
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("Silent Observer started for founder %s", self.founder_id)

    def stop(self):
        if self._task:
            self._task.cancel()
            self._task = None

    async def _poll_loop(self):
        while True:
            try:
                await self._poll()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Observer poll error: %s", e)
            await asyncio.sleep(_POLL_INTERVAL)

    async def _poll(self):
        if not self._active_domains:
            return

        queries = self._build_queries()
        for query in queries:
            results = await self._search(query)
            for item in results:
                h = self._hash(item["summary"])
                if h in self._seen_hashes:
                    continue
                self._seen_hashes.add(h)

                score = self._score_relevance(item["summary"])
                if score < 0.3:
                    continue

                alert = ObserverAlert(
                    summary=item["summary"],
                    source=item.get("source", "web"),
                    url=item.get("url"),
                    relevance_score=score,
                    suggested_action=await self._generate_action(item["summary"]),
                    content_hash=h,
                    timestamp=datetime.utcnow().isoformat(),
                )
                self._pending_alerts.append(alert)

                # Write to decision graph
                if self.graph:
                    self.graph.add_external_event(
                        source=alert.source,
                        summary=alert.summary,
                        relevance_score=alert.relevance_score,
                        url=alert.url,
                        content_hash=h,
                    )

                logger.info(
                    "Observer alert (score=%.2f): %s", alert.relevance_score, alert.summary[:80]
                )

    def _build_queries(self) -> list[str]:
        queries = []
        for domain in self._active_domains[:3]:
            queries.append(f"{domain} startup funding news")
            queries.append(f"{domain} competitor launch product")
            queries.append(f"{domain} regulation compliance")
        return queries

    async def _search(self, query: str) -> list[dict]:
        """Use web_search tool. Falls back to empty list on error."""
        try:
            from backend.tools.web_search import web_search
            result = web_search(query)
            if isinstance(result, dict) and "results" in result:
                return [
                    {"summary": r.get("snippet", r.get("title", "")), "url": r.get("url"), "source": "web"}
                    for r in result["results"][:5]
                ]
        except Exception as e:
            logger.debug("Observer search failed (%s): %s", query, e)
        return []

    def _score_relevance(self, text: str) -> float:
        """Simple keyword overlap against active domains + goals."""
        text_lower = text.lower()
        domain_words = set(" ".join(self._active_domains).lower().split())
        goal_words = set(" ".join(self._active_goals).lower().split())
        all_keywords = domain_words | goal_words
        if not all_keywords:
            return 0.0
        text_words = set(text_lower.split())
        return len(all_keywords & text_words) / len(all_keywords)

    async def _generate_action(self, summary: str) -> str:
        try:
            from backend.tools._llm import generate
            prompt = (
                f"Intelligence alert: {summary}\n"
                f"Founder's domains: {', '.join(self._active_domains)}\n"
                f"In one sentence, what specific action should the founder take in response?"
            )
            return generate(prompt, max_tokens=100) or "Review and assess impact on current strategy."
        except Exception:
            return "Review and assess impact on current strategy."

    def _hash(self, text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    # ------------------------------------------------------------------ #
    # Alert access
    # ------------------------------------------------------------------ #

    def pop_alerts(self) -> list[ObserverAlert]:
        """Return and clear pending alerts."""
        alerts = list(self._pending_alerts)
        self._pending_alerts.clear()
        return alerts

    def format_alert_block(self) -> str:
        """Format pending alerts for injection into run context."""
        alerts = self.pop_alerts()
        if not alerts:
            return ""

        lines = ["[Silent Observer — Intelligence Alerts]"]
        for a in alerts:
            lines.append(
                f"• [{a.timestamp[:16]}] {a.summary}\n"
                f"  Source: {a.source} | Relevance: {a.relevance_score:.2f}\n"
                f"  Action: {a.suggested_action}"
                + (f"\n  URL: {a.url}" if a.url else "")
            )
        return "\n".join(lines)

    def stats(self) -> dict:
        return {
            "seen_items": len(self._seen_hashes),
            "pending_alerts": len(self._pending_alerts),
            "domains_watched": self._active_domains,
            "poll_interval_hours": _POLL_INTERVAL // 3600,
        }
