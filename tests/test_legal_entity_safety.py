"""Regression coverage: the autonomous agent path must never drive the real
LLC filer.

Real bug found via audit: _file_entity_agent_safe used to call the REAL
file_llc_live (a Playwright browser automation against a real third-party
filing service, potentially with a real card) whenever Playwright happened
to be importable, using no-op send_message/wait_input callbacks — meaning an
agent could submit toward a real filing with completely empty founder
fields, with no human ever seeing the required prompts. Confirmed Playwright
IS installed on production. Fixed to always return the safe pending-ticket
stub; the real filer only runs through the founder-supervised
/ws/llc-filing WebSocket flow (backend/api/routes.py).

Also: backend/specialists/legal.py used to expose the RAW file_llc_live
directly as a tool (not even the safe wrapper) — removed entirely, since
that agent's own documented workflow never uses it.
"""
import pytest

from backend.specialists.legal_entity import _file_entity_agent_safe


@pytest.mark.asyncio
async def test_file_entity_agent_safe_never_calls_real_filer(monkeypatch):
    called = {"hit": False}

    async def _fake_real_filer(*args, **kwargs):
        called["hit"] = True
        return {"status": "submitted", "confirmation_url": "https://real-filing-happened"}

    monkeypatch.setattr("backend.tools.llc_filing.file_llc_live", _fake_real_filer)

    result = await _file_entity_agent_safe(company_name="Acme Inc", state="Delaware", entity_type="c_corp")

    assert called["hit"] is False
    assert result["status"] == "pending"
    assert result["confirmation_number"].startswith("PENDING-")
    assert "confirmation_url" not in result


@pytest.mark.asyncio
async def test_file_entity_agent_safe_ignores_playwright_availability(monkeypatch):
    """Even with Playwright genuinely importable (the real condition on
    production), the wrapper must stay on the safe stub path — Playwright
    availability is no longer part of the branch at all."""
    import sys
    import types

    fake_playwright_module = types.ModuleType("playwright.async_api")
    fake_playwright_module.async_playwright = lambda: None
    monkeypatch.setitem(sys.modules, "playwright.async_api", fake_playwright_module)

    result = await _file_entity_agent_safe(company_name="Acme Inc", state="Delaware", entity_type="llc")

    assert result["status"] == "pending"
    assert result["confirmation_number"].startswith("PENDING-")


def test_legal_agent_no_longer_exposes_raw_filer():
    from backend.specialists.legal import build_legal_agent

    agent = build_legal_agent()
    assert "file_llc_live" not in agent.tools


def test_legal_entity_agent_exposes_only_the_safe_wrapper():
    from backend.specialists.legal_entity import build_legal_entity_agent, _file_entity_agent_safe

    agent = build_legal_entity_agent()
    assert agent.tools["file_llc_live"] is _file_entity_agent_safe
