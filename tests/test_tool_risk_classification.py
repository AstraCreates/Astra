"""Regression coverage for the SafeRun risk-classification pipeline.

Real production bug: Agent.__init__ (backend/core/agent.py:445-452) eagerly
pre-registers every tool into the shared runtime_tool_registry the moment the
FIRST agent holding it is constructed, using register_callable's bare
defaults (mutability="read", toolset="legacy", risk_category=None) — this
runs before backend/runtime/catalog.py's register_agent_tools ever sees the
tool. register_agent_tools used to reuse that stale entry whenever one
already existed, permanently defeating SafeRun gating for any tool not
hand-curated in backend/safety/saferun.py's _RISKY_TOOLS. Confirmed live on
production: file_llc_live (which IS in MUTATING_TOOLS and matches an
EXTERNAL_PREFIXES entry) still came back mutability="read" with no
risk_category.
"""
from backend.config import settings
from backend.core.agent import Agent
from backend.runtime.catalog import register_agent_tools
from backend.runtime.tool_registry import registry
from backend.safety import build_saferun_action


def _dummy_tool(**_kwargs):
    return {"ok": True}


def test_register_agent_tools_recomputes_classification_despite_stale_entry(monkeypatch):
    monkeypatch.setattr(settings, "astra_tool_registry_v2", True)

    # Reproduce the real bug sequence: constructing an Agent with this tool
    # FIRST eagerly registers it with bare defaults, before any specialist-
    # aware classification runs.
    Agent(name="first_holder", role="irrelevant", tools={"printful_create_order": _dummy_tool})
    stale = registry.get("printful_create_order")
    assert stale is not None
    assert stale.mutability == "read"
    assert stale.risk_category is None

    class FakeAgent:
        tools = {"printful_create_order": _dummy_tool}

    register_agent_tools(FakeAgent())

    fixed = registry.get("printful_create_order")
    assert fixed.mutability == "external"
    assert fixed.risk_category == "commerce_fulfillment"


def test_saferun_gates_file_llc_live_via_registry_fallback(monkeypatch):
    monkeypatch.setattr(settings, "astra_tool_registry_v2", True)

    class FakeAgent:
        tools = {"file_llc_live": _dummy_tool}

    register_agent_tools(FakeAgent())

    action = build_saferun_action("file_llc_live", {}, "legal")
    assert action is not None
    assert action["approval_required"] is True


def test_saferun_gates_previously_uncovered_real_action_tools(monkeypatch):
    monkeypatch.setattr(settings, "astra_tool_registry_v2", True)

    class FakeAgent:
        tools = {name: _dummy_tool for name in (
            "printful_create_order", "twilio_send_sms", "twilio_send_bulk_sms",
            "square_create_booking", "square_create_service",
            "ls_create_product", "ls_create_discount",
        )}

    register_agent_tools(FakeAgent())

    for name in FakeAgent.tools:
        action = build_saferun_action(name, {}, "sales")
        assert action is not None, f"{name} still ungated"
        assert action["approval_required"] is True, f"{name} gated but not requiring approval"


def test_saferun_gates_technical_build_tools():
    """MVP builds were the single largest real spend category (5,468 credits /
    11 txns vs ~856 credits / 347 txns for everything else combined) with no
    approval gate before spend started. run_mvp_loop/spawn_parallel_coders/
    run_claude_in_repo must require founder approval before firing."""
    for name in ("run_mvp_loop", "spawn_parallel_coders", "run_claude_in_repo"):
        action = build_saferun_action(name, {}, "technical")
        assert action is not None, f"{name} still ungated"
        assert action["approval_required"] is True, f"{name} gated but not requiring approval"
        assert action["approval_gate"] == "technical_build"
