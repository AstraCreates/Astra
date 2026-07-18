import asyncio

import pytest

from backend.runtime.budget import RunBudget
from backend.runtime.context_compressor import AstraContextCompressor
from backend.runtime.manifests import SpecialistManifest
from backend.runtime.tool_guardrails import ToolCallGuardrailController
from backend.runtime.tool_registry import ToolEntry, ToolRegistry
from backend.runtime.catalog import infer_context_fields, infer_mutability, infer_toolset
from backend.runtime.circuit_breaker import disable, enable
from backend.runtime.rollout import enabled
from backend.core.agent_state import load_agent_state, save_agent_state, relevant_state_snapshot


def test_run_budget_is_atomic_under_concurrency():
    budget = RunBudget(max_iterations=50)

    async def consume():
        return await asyncio.to_thread(budget.consume_iteration)

    async def run_all():
        return await asyncio.gather(*[consume() for _ in range(100)])

    results = asyncio.run(run_all())
    assert sum(results) == 50
    assert budget.snapshot().iterations_used == 50


def test_child_budget_is_bounded_by_parent():
    parent = RunBudget(max_iterations=20, max_cost_usd=10, deadline_seconds=60)
    parent.record_usage(cost_usd=4)
    child = parent.child(max_iterations=5)
    assert child.max_cost_usd == pytest.approx(1.8)
    assert child.deadline_seconds <= 60


def test_guardrail_blocks_identical_failures():
    guard = ToolCallGuardrailController(identical_warn=2, identical_block=4)
    for _ in range(4):
        guard.after_call("web_search", {"query": "x"}, {"error": "no"}, failed=True)
    decision = guard.before_call("web_search", {"query": "x"})
    assert decision.action == "block"
    assert decision.code == "identical_failure"


def test_guardrail_allows_changed_arguments_until_same_tool_limit():
    guard = ToolCallGuardrailController(same_tool_halt=7)
    for index in range(4):
        guard.after_call("web_search", {"query": str(index)}, {"error": "no"}, failed=True)
    assert guard.before_call("web_search", {"query": "new"}).allows_execution


def test_guardrail_blocks_duplicate_successful_mutation():
    guard = ToolCallGuardrailController()
    args = {"repo_name": "astra-test"}
    guard.after_call("github_create_repo", args, {"url": "x"}, failed=False)
    assert guard.before_call("github_create_repo", args).code == "duplicate_mutation"


@pytest.mark.asyncio
async def test_registry_context_injection_and_async_dispatch():
    registry = ToolRegistry()

    async def handler(value, founder_id):
        return {"value": value, "founder_id": founder_id}

    entry = registry.register(ToolEntry(
        name="sample", toolset="research",
        schema={"parameters": {"type": "object"}},
        handler=handler, is_async=True,
        context_fields=frozenset({"founder_id"}),
    ))
    with pytest.raises(TypeError, match="unknown argument"):
        await registry.dispatch(entry, {"value": "ok", "ignored": True}, {"founder_id": "f1"})
    result = await registry.dispatch(entry, {"value": "ok"}, {"founder_id": "f1"})
    assert result == {"value": "ok", "founder_id": "f1"}


def test_registry_rejects_duplicate_registration():
    registry = ToolRegistry()
    entry = ToolEntry("x", "research", {}, lambda: None)
    registry.register(entry)
    with pytest.raises(ValueError):
        registry.register(entry)


def test_registry_availability_check_is_cached():
    calls = 0

    def check():
        nonlocal calls
        calls += 1
        return True

    registry = ToolRegistry(availability_ttl=30)
    entry = ToolEntry("x", "research", {}, lambda: None, check_fn=check)
    registry.register(entry)
    assert registry.is_available(entry)
    assert registry.is_available(entry)
    assert calls == 1


def test_manifest_validates_and_checks_required_output():
    manifest = SpecialistManifest(
        name="demo", role="demo", toolsets=("research",),
        required_tools=frozenset({"web_search"}),
        output_schema={"type": "object", "required": ["summary"]},
    )
    assert manifest.validate({"web_search"}, {"research"}) == []
    assert manifest.missing_output_fields({}) == ["summary"]


def test_context_compressor_preserves_head_tail_and_bounds_history():
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "GOAL: build"},
    ]
    messages.extend({"role": "user", "content": f"Tool result {i}: https://example.com/{i}"} for i in range(30))
    compressor = AstraContextCompressor(token_threshold=1, tail_messages=4)
    compacted, metadata = compressor.compress(messages)
    assert metadata["compressed"] is True
    assert compacted[0]["content"] == "system"
    assert "CONTEXT COMPACTION" in compacted[2]["content"]
    assert compacted[-1] == messages[-1]


def test_context_compressor_default_threshold_leaves_headroom_for_proxy(monkeypatch):
    monkeypatch.delenv("ASTRA_COMPRESSION_THRESHOLD", raising=False)
    compressor = AstraContextCompressor()
    assert compressor.token_threshold == 64000


def test_agent_state_relevant_snapshot_filters_by_query():
    save_agent_state("s", "research", "t", {
        "plan": "find market and competitor evidence",
        "recent_tools": ["web_search: generic", "sonar_research: market sizing"],
        "tool_memory": {
            "web_search": ["web_search: generic", "web_search: competitor pricing"],
            "sonar_research": ["sonar_research: market sizing", "sonar_research: GTM"],
        },
        "artifacts": ["report -> /tmp/report.pdf"],
        "blockers": [],
        "next_steps": ["synthesize findings"],
    })
    snap = relevant_state_snapshot("s", "research", "t", query="sonar_research market", sections=("recent_tools", "artifacts"))
    assert "sonar_research" in " ".join(snap["recent_tools"])
    assert snap["artifacts"] == ["report -> /tmp/report.pdf"]


def test_agent_state_load_includes_tool_memory_default():
    state = load_agent_state("missing", "technical", "task")
    assert "tool_memory" in state


def test_production_metadata_inference():
    def tool(query, founder_id=""):
        return query

    assert infer_toolset("web_search") == "research"
    assert infer_mutability("send_email_campaign") == "external"
    assert infer_context_fields(tool) == frozenset({"founder_id"})


def test_rollout_circuit_breaker(monkeypatch):
    from backend.config import settings
    monkeypatch.setattr(settings, "astra_native_tool_calls", True)
    monkeypatch.setattr(settings, "astra_native_tool_calls_rollout_percent", 100)
    enable("native_tool_calls")
    assert enabled("native_tool_calls", "f1")
    disable("native_tool_calls", "test invariant")
    assert not enabled("native_tool_calls", "f1")
    enable("native_tool_calls")


def test_cost_saving_runtime_features_default_on():
    from backend.config import settings

    assert settings.astra_context_compression_v2 is True
    assert settings.astra_native_tool_calls is True
    assert enabled("context_compression_v2", "founder_cost")
    assert enabled("native_tool_calls", "founder_cost")
