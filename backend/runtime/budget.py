"""Thread-safe per-agent resource budgets.

Iteration accounting is adapted from NousResearch/hermes-agent
(`agent/iteration_budget.py`), licensed under the MIT License.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class BudgetSnapshot:
    max_iterations: int
    iterations_used: int
    tool_calls_used: int
    max_tool_calls: int | None
    cost_usd: float
    max_cost_usd: float | None
    tokens: int
    credits: float
    elapsed_seconds: float
    deadline_seconds: float | None
    exhausted_reason: str | None


class RunBudget:
    """Atomic iteration, tool-call, cost, and deadline accounting."""

    def __init__(
        self,
        max_iterations: int,
        max_tool_calls: int | None = None,
        max_cost_usd: float | None = None,
        deadline_seconds: float | None = None,
    ):
        self.max_iterations = max(1, int(max_iterations))
        self.max_tool_calls = None if max_tool_calls is None else max(0, int(max_tool_calls))
        self.max_cost_usd = None if max_cost_usd is None else max(0.0, float(max_cost_usd))
        self.deadline_seconds = None if deadline_seconds is None else max(0.0, float(deadline_seconds))
        self._started = time.monotonic()
        self._iterations = 0
        self._tool_calls = 0
        self._cost_usd = 0.0
        self._tokens = 0
        self._credits = 0.0
        self._exhausted_reason: str | None = None
        self._lock = threading.Lock()

    def _deadline_exhausted(self) -> bool:
        return self.deadline_seconds is not None and time.monotonic() - self._started >= self.deadline_seconds

    def consume_iteration(self) -> bool:
        with self._lock:
            if self._deadline_exhausted():
                self._exhausted_reason = "deadline"
                return False
            if self.max_cost_usd is not None and self._cost_usd >= self.max_cost_usd:
                self._exhausted_reason = "cost"
                return False
            if self._iterations >= self.max_iterations:
                self._exhausted_reason = "iterations"
                return False
            self._iterations += 1
            return True

    def consume_tool_call(self) -> bool:
        with self._lock:
            if self._deadline_exhausted():
                self._exhausted_reason = "deadline"
                return False
            if self.max_tool_calls is not None and self._tool_calls >= self.max_tool_calls:
                self._exhausted_reason = "tool_calls"
                return False
            self._tool_calls += 1
            return True

    def record_usage(self, *, tokens: int = 0, credits: float = 0.0, cost_usd: float = 0.0) -> None:
        with self._lock:
            self._tokens += max(0, int(tokens))
            self._credits += max(0.0, float(credits))
            self._cost_usd += max(0.0, float(cost_usd))
            if self.max_cost_usd is not None and self._cost_usd >= self.max_cost_usd:
                self._exhausted_reason = "cost"

    def child(self, *, max_iterations: int, cost_fraction: float = 0.3) -> "RunBudget":
        snap = self.snapshot()
        remaining_cost = None
        if snap.max_cost_usd is not None:
            remaining_cost = max(0.0, snap.max_cost_usd - snap.cost_usd) * max(0.0, min(cost_fraction, 1.0))
        remaining_deadline = None
        if snap.deadline_seconds is not None:
            remaining_deadline = max(0.0, snap.deadline_seconds - snap.elapsed_seconds)
        return RunBudget(
            max_iterations=max_iterations,
            max_cost_usd=remaining_cost,
            deadline_seconds=remaining_deadline,
        )

    def snapshot(self) -> BudgetSnapshot:
        with self._lock:
            reason = self._exhausted_reason
            if reason is None and self._deadline_exhausted():
                reason = "deadline"
            return BudgetSnapshot(
                max_iterations=self.max_iterations,
                iterations_used=self._iterations,
                tool_calls_used=self._tool_calls,
                max_tool_calls=self.max_tool_calls,
                cost_usd=self._cost_usd,
                max_cost_usd=self.max_cost_usd,
                tokens=self._tokens,
                credits=self._credits,
                elapsed_seconds=round(time.monotonic() - self._started, 3),
                deadline_seconds=self.deadline_seconds,
                exhausted_reason=reason,
            )

    @property
    def exhausted_reason(self) -> str | None:
        return self.snapshot().exhausted_reason
