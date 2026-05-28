import json
from unittest.mock import AsyncMock

import pytest

from backend.core.agent import Agent, AgentContext
from backend.core.orchestrator import Orchestrator


@pytest.mark.asyncio
async def test_legal_agent_done_blocked_until_required_tools_called(mocker):
    calls = {"llm": 0}

    def fake_llm(_messages):
        calls["llm"] += 1
        if calls["llm"] == 1:
            return json.dumps({"action": "done", "output": {"note": "premature"}})
        if calls["llm"] == 2:
            return json.dumps({"action": "tool", "tool": "format_legal_document", "args": {"doc_type": "privacy_policy", "company_name": "Acme", "content": "ctx"}})
        if calls["llm"] == 3:
            return json.dumps({"action": "tool", "tool": "generate_pdf", "args": {"title": "Privacy", "content": "body"}})
        return json.dumps({"action": "done", "output": {"ok": True}})

    agent = Agent(
        name="legal",
        role="legal",
        tools={
            "format_legal_document": lambda **_kwargs: {"doc_type": "privacy_policy", "formatted_text": "body"},
            "generate_pdf": lambda **_kwargs: {"path": "/tmp/privacy.pdf"},
        },
    )
    agent._call_llm = fake_llm
    mocker.patch("backend.core.events.publish", new=AsyncMock())
    result = await agent.run(AgentContext(goal="g", founder_id="f", session_id="s", shared={}))

    assert result.get("ok") is True
    assert calls["llm"] >= 4


@pytest.mark.asyncio
async def test_sales_agent_done_blocked_until_required_output_present(mocker):
    calls = {"llm": 0}

    def fake_llm(_messages):
        calls["llm"] += 1
        if calls["llm"] == 1:
            return json.dumps({"action": "tool", "tool": "find_leads", "args": {"industry": "dental", "location": "phoenix"}})
        if calls["llm"] == 2:
            return json.dumps({"action": "tool", "tool": "build_outreach_sequence", "args": {"lead": {"company": "Acme Dental"}, "offer": "demo"}})
        if calls["llm"] == 3:
            return json.dumps({"action": "done", "output": {"leads": [{"company": "Acme Dental"}]}})
        if calls["llm"] == 4:
            return json.dumps({"action": "tool", "tool": "build_crm_contact", "args": {"company": "Acme Dental", "email": "ops@acme.com"}})
        return json.dumps({"action": "done", "output": {"leads": [{"company": "Acme Dental"}], "sequence": [{"send_day": 1, "subject": "Hi"}], "crm_contacts": [{"company": "Acme Dental", "email": "ops@acme.com"}]}})

    agent = Agent(
        name="sales",
        role="sales",
        tools={
            "find_leads": lambda **_kwargs: {"leads": [{"company": "Acme Dental"}]},
            "build_outreach_sequence": lambda **_kwargs: {"lead": {"company": "Acme Dental"}, "sequence": [{"send_day": 1, "subject": "Hi"}]},
            "build_crm_contact": lambda **_kwargs: {"company": "Acme Dental", "email": "ops@acme.com"},
        },
    )
    agent._call_llm = fake_llm
    mocker.patch("backend.core.events.publish", new=AsyncMock())
    result = await agent.run(AgentContext(goal="g", founder_id="f", session_id="s", shared={}))
    assert result.get("sequence")
    assert calls["llm"] >= 4


@pytest.mark.asyncio
async def test_sales_agent_done_blocked_until_crm_tool_called(mocker):
    calls = {"llm": 0}

    def fake_llm(_messages):
        calls["llm"] += 1
        if calls["llm"] == 1:
            return json.dumps({"action": "tool", "tool": "find_leads", "args": {"industry": "dental", "location": "phoenix"}})
        if calls["llm"] == 2:
            return json.dumps({"action": "tool", "tool": "build_outreach_sequence", "args": {"lead": {"company": "Acme Dental"}, "offer": "demo"}})
        if calls["llm"] == 3:
            return json.dumps({"action": "done", "output": {"leads": [{"company": "Acme Dental"}], "sequence": [{"send_day": 1, "subject": "Hi"}], "crm_contacts": [{"company": "Acme Dental", "email": "ops@acme.com"}]}})
        if calls["llm"] == 4:
            return json.dumps({"action": "tool", "tool": "build_crm_contact", "args": {"company": "Acme Dental", "email": "ops@acme.com"}})
        return json.dumps({"action": "done", "output": {"leads": [{"company": "Acme Dental"}], "sequence": [{"send_day": 1, "subject": "Hi"}], "crm_contacts": [{"company": "Acme Dental", "email": "ops@acme.com"}]}})

    agent = Agent(
        name="sales",
        role="sales",
        tools={
            "find_leads": lambda **_kwargs: {"leads": [{"company": "Acme Dental"}]},
            "build_outreach_sequence": lambda **_kwargs: {"lead": {"company": "Acme Dental"}, "sequence": [{"send_day": 1, "subject": "Hi"}]},
            "build_crm_contact": lambda **_kwargs: {"company": "Acme Dental", "email": "ops@acme.com"},
        },
    )
    agent._call_llm = fake_llm
    mocker.patch("backend.core.events.publish", new=AsyncMock())
    result = await agent.run(AgentContext(goal="g", founder_id="f", session_id="s", shared={}))
    assert result.get("crm_contacts")
    assert calls["llm"] >= 5


@pytest.mark.asyncio
async def test_design_agent_done_blocked_until_logo_brief_tool_called(mocker):
    calls = {"llm": 0}

    def fake_llm(_messages):
        calls["llm"] += 1
        if calls["llm"] == 1:
            return json.dumps({"action": "tool", "tool": "generate_design_spec", "args": {"product_name": "Acme", "product_type": "saas", "target_audience": "founders"}})
        if calls["llm"] == 2:
            return json.dumps({"action": "tool", "tool": "generate_wireframe", "args": {"page_type": "landing", "sections": ["hero"], "style": "minimal"}})
        if calls["llm"] == 3:
            return json.dumps({"action": "done", "output": {"design_spec": {"product": "Acme"}, "wireframes": [{"page_type": "landing"}], "logo_brief": {"direction": "minimal"}}})
        if calls["llm"] == 4:
            return json.dumps({"action": "tool", "tool": "generate_logo_brief", "args": {"company_name": "Acme", "brand_vibe": "minimal"}})
        return json.dumps({"action": "done", "output": {"design_spec": {"product": "Acme"}, "wireframes": [{"page_type": "landing"}], "logo_brief": {"direction": "minimal"}}})

    agent = Agent(
        name="design",
        role="design",
        tools={
            "generate_design_spec": lambda **_kwargs: {"product": "Acme"},
            "generate_wireframe": lambda **_kwargs: {"page_type": "landing"},
            "generate_logo_brief": lambda **_kwargs: {"direction": "minimal"},
        },
    )
    agent._call_llm = fake_llm
    mocker.patch("backend.core.events.publish", new=AsyncMock())
    result = await agent.run(AgentContext(goal="g", founder_id="f", session_id="s", shared={}))
    assert result.get("logo_brief")
    assert calls["llm"] >= 5


@pytest.mark.asyncio
async def test_marketing_agent_done_blocked_until_required_output_present(mocker):
    calls = {"llm": 0}

    def fake_llm(_messages):
        calls["llm"] += 1
        if calls["llm"] == 1:
            return json.dumps({"action": "tool", "tool": "generate_reel_package", "args": {"company_name": "Acme", "headline": "h", "value_prop": "v", "target_audience": "founders"}})
        if calls["llm"] == 2:
            return json.dumps({"action": "tool", "tool": "generate_tiktok_package", "args": {"company_name": "Acme", "hook": "h", "problem": "p", "solution": "s"}})
        if calls["llm"] == 3:
            return json.dumps({"action": "tool", "tool": "generate_meta_ad", "args": {"company_name": "Acme", "headline": "h", "body": "b", "cta": "Start", "target_audience_description": "Founders"}})
        if calls["llm"] == 4:
            return json.dumps({"action": "done", "output": {"reel_package": {"script": "x"}, "tiktok_package": {"script": "y"}, "meta_ad": {"headline": "z"}}})
        if calls["llm"] == 5:
            return json.dumps({"action": "tool", "tool": "generate_ad_image", "args": {"prompt": "A modern SaaS ad", "aspect_ratio": "1:1"}})
        return json.dumps({"action": "done", "output": {"reel_package": {"script": "x"}, "tiktok_package": {"script": "y"}, "meta_ad": {"headline": "z"}}})

    agent = Agent(
        name="marketing",
        role="marketing",
        tools={
            "generate_reel_package": lambda **_kwargs: {"script": "x"},
            "generate_tiktok_package": lambda **_kwargs: {"script": "y"},
            "generate_meta_ad": lambda **_kwargs: {"headline": "z"},
            "generate_ad_image": lambda **_kwargs: {"url": "https://img.example/ad.png", "prompt": "A modern SaaS ad"},
        },
    )
    agent._call_llm = fake_llm
    mocker.patch("backend.core.events.publish", new=AsyncMock())
    result = await agent.run(AgentContext(goal="g", founder_id="f", session_id="s", shared={}))
    assert isinstance(result.get("ad_images"), list) and len(result["ad_images"]) >= 1
    assert calls["llm"] >= 5


class _FakePlanner:
    name = "planner"
    model = "test"

    def _call_llm(self, _messages):
        return '{"tasks":[]}'


class _FakeAgent:
    def __init__(self, name, outputs):
        self.name = name
        self.outputs = list(outputs)
        self.tools = {}
        self.calls = 0

    async def run(self, _ctx):
        self.calls += 1
        return self.outputs[min(self.calls - 1, len(self.outputs) - 1)]


@pytest.mark.asyncio
async def test_orchestrator_retries_web_when_fallback_detected(mocker):
    planner = _FakePlanner()
    research = _FakeAgent("research", [{"summary": "researched"}])
    web = _FakeAgent("web", [
        {"html": "<!DOCTYPE html><!-- astra-fallback-template --><html></html>"},
        {"html": "<!DOCTYPE html><!-- astra-fallback-template --><html></html>"},
        {"html": "<!DOCTYPE html><html><body>custom</body></html>", "url": "https://example.com"},
    ])
    orch = Orchestrator(planner=planner, specialists={"research": research, "web": web})

    mocker.patch("backend.core.events.publish", new=AsyncMock())
    mocker.patch.object(orch, "_expand_goal", new=AsyncMock(return_value="goal"))
    mocker.patch.object(orch, "_initial_plan", new=AsyncMock(return_value=[{"id": "t1", "agent": "research", "instruction": "r", "depends_on": []}]))
    mocker.patch.object(orch, "_replan_with_research", new=AsyncMock(return_value=[{"id": "w1", "agent": "web", "instruction": "w", "depends_on": []}]))
    mocker.patch.object(orch, "_generate_detailed_plan", new=AsyncMock(return_value=[]))
    mocker.patch("backend.tools.obsidian_logger._note_path")
    mocker.patch("backend.tools.obsidian_logger.auto_log_if_missing", return_value=False)
    mocker.patch("backend.tools.obsidian_logger.obsidian_session_index", return_value={"indexed": True})

    await orch.run(goal="g", founder_id="f", session_id="s")
    assert web.calls == 3


@pytest.mark.asyncio
async def test_orchestrator_flags_web_error_when_fallback_persists(mocker):
    planner = _FakePlanner()
    research = _FakeAgent("research", [{"summary": "researched"}])
    web = _FakeAgent("web", [
        {"html": "<!DOCTYPE html><!-- astra-fallback-template --><html></html>"},
        {"html": "<!DOCTYPE html><!-- astra-fallback-template --><html></html>"},
        {"html": "<!DOCTYPE html><!-- astra-fallback-template --><html></html>"},
    ])
    orch = Orchestrator(planner=planner, specialists={"research": research, "web": web})

    published: list[dict] = []

    async def capture_publish(_session_id: str, event: dict):
        published.append(event)

    mocker.patch("backend.core.events.publish", new=capture_publish)
    mocker.patch.object(orch, "_expand_goal", new=AsyncMock(return_value="goal"))
    mocker.patch.object(orch, "_initial_plan", new=AsyncMock(return_value=[{"id": "t1", "agent": "research", "instruction": "r", "depends_on": []}]))
    mocker.patch.object(orch, "_replan_with_research", new=AsyncMock(return_value=[{"id": "w1", "agent": "web", "instruction": "w", "depends_on": []}]))
    mocker.patch.object(orch, "_generate_detailed_plan", new=AsyncMock(return_value=[]))
    mocker.patch("backend.tools.obsidian_logger._note_path")
    mocker.patch("backend.tools.obsidian_logger.auto_log_if_missing", return_value=False)
    mocker.patch("backend.tools.obsidian_logger.obsidian_session_index", return_value={"indexed": True})

    await orch.run(goal="g", founder_id="f", session_id="s")

    goal_done = next(e for e in published if e.get("type") == "goal_done")
    results = goal_done["results"]
    web_result = next(v for v in results.values() if isinstance(v, dict) and "html" in v)
    assert web_result.get("web_quality_error") == "fallback_template_persisted_after_retries"
    assert any(
        e.get("type") == "agent_error"
        and e.get("agent") == "web"
        and "fallback template" in str(e.get("error", "")).lower()
        for e in published
    )


@pytest.mark.asyncio
async def test_orchestrator_detects_fallback_by_style_signature_without_marker(mocker):
    planner = _FakePlanner()
    research = _FakeAgent("research", [{"summary": "researched"}])
    web = _FakeAgent("web", [
        {"html": "<!DOCTYPE html><html><head><style>:root{--bg: #06080f; --bg2: #0d1117;}</style></head><body>Define your goal</body></html>"},
        {"html": "<!DOCTYPE html><html><body>custom</body></html>", "url": "https://example.com"},
    ])
    orch = Orchestrator(planner=planner, specialists={"research": research, "web": web})

    mocker.patch("backend.core.events.publish", new=AsyncMock())
    mocker.patch.object(orch, "_expand_goal", new=AsyncMock(return_value="goal"))
    mocker.patch.object(orch, "_initial_plan", new=AsyncMock(return_value=[{"id": "t1", "agent": "research", "instruction": "r", "depends_on": []}]))
    mocker.patch.object(orch, "_replan_with_research", new=AsyncMock(return_value=[{"id": "w1", "agent": "web", "instruction": "w", "depends_on": []}]))
    mocker.patch.object(orch, "_generate_detailed_plan", new=AsyncMock(return_value=[]))
    mocker.patch("backend.tools.obsidian_logger._note_path")
    mocker.patch("backend.tools.obsidian_logger.auto_log_if_missing", return_value=False)
    mocker.patch("backend.tools.obsidian_logger.obsidian_session_index", return_value={"indexed": True})

    await orch.run(goal="g", founder_id="f", session_id="s")
    assert web.calls == 2


@pytest.mark.asyncio
async def test_orchestrator_initial_plan_emits_only_three_research_lanes(mocker):
    planner = _FakePlanner()
    research = _FakeAgent("research", [{"summary": "researched"}])
    research_comp = _FakeAgent("research_competitors", [{"summary": "competitors"}])
    research_exec = _FakeAgent("research_execution", [{"summary": "execution"}])
    web = _FakeAgent("web", [{"html": "<!DOCTYPE html><html><body>custom</body></html>", "url": "https://example.com"}])
    orch = Orchestrator(
        planner=planner,
        specialists={
            "research": research,
            "research_competitors": research_comp,
            "research_execution": research_exec,
            "web": web,
        },
    )

    published: list[dict] = []

    async def capture_publish(_session_id: str, event: dict):
        published.append(event)

    mocker.patch("backend.core.events.publish", new=capture_publish)
    mocker.patch.object(orch, "_expand_goal", new=AsyncMock(return_value="goal"))
    mocker.patch.object(orch, "_initial_plan", new=AsyncMock(return_value=[{"id": "t1", "agent": "research", "instruction": "r", "depends_on": []}]))
    mocker.patch.object(orch, "_replan_with_research", new=AsyncMock(return_value=[{"id": "w1", "agent": "web", "instruction": "w", "depends_on": []}]))
    mocker.patch.object(orch, "_generate_detailed_plan", new=AsyncMock(return_value=[]))
    mocker.patch("backend.tools.obsidian_logger._note_path")
    mocker.patch("backend.tools.obsidian_logger.auto_log_if_missing", return_value=False)
    mocker.patch("backend.tools.obsidian_logger.obsidian_session_index", return_value={"indexed": True})

    await orch.run(goal="g", founder_id="f", session_id="s")

    first_plan = next(e for e in published if e.get("type") == "plan_done")
    agents = [t.get("agent") for t in first_plan.get("tasks", [])]
    research_agents = [a for a in agents if isinstance(a, str) and a.startswith("research")]
    assert sorted(research_agents) == sorted(["research", "research_competitors", "research_execution"])


@pytest.mark.asyncio
async def test_orchestrator_emits_preview_rich_outputs_for_non_research_agents(mocker):
    planner = _FakePlanner()
    research = _FakeAgent("research", [{"summary": "researched"}])
    web = _FakeAgent("web", [
        {"html": "<!DOCTYPE html><!-- astra-fallback-template --><html></html>"},
        {"html": "<!DOCTYPE html><html><body>custom</body></html>", "url": "https://example.com"},
    ])
    marketing = _FakeAgent("marketing", [{
        "reel_package": {"script": "hook"},
        "ad_images": [{"url": "https://img.example/ad.png", "prompt": "ad"}],
    }])
    technical = _FakeAgent("technical", [{
        "repo_url": "https://github.com/acme/app",
        "deploy_url": "https://acme.vercel.app",
        "files_preview": ["frontend/app/page.tsx", "backend/main.py"],
        "files_in_repo": 24,
    }])
    legal = _FakeAgent("legal", [{
        "documents": [{"doc_type": "privacy_policy", "title": "Privacy Policy", "path": "/tmp/privacy_policy.pdf", "text": "..." }],
    }])
    sales = _FakeAgent("sales", [{
        "leads": [{"company": "Acme Dental"}],
        "sequence": [{"send_day": 1, "subject": "Hi"}],
        "crm_contacts": [{"company": "Acme Dental", "email": "ops@acme.com"}],
    }])
    design = _FakeAgent("design", [{
        "design_spec": {"product": "Acme"},
        "wireframes": [{"page_type": "landing"}],
        "logo_brief": {"direction": "minimal"},
    }])

    specialists = {
        "research": research,
        "web": web,
        "marketing": marketing,
        "technical": technical,
        "legal": legal,
        "sales": sales,
        "design": design,
    }
    orch = Orchestrator(planner=planner, specialists=specialists)

    published: list[dict] = []

    async def capture_publish(_session_id: str, event: dict):
        published.append(event)

    mocker.patch("backend.core.events.publish", new=capture_publish)
    mocker.patch.object(orch, "_expand_goal", new=AsyncMock(return_value="goal"))
    mocker.patch.object(orch, "_initial_plan", new=AsyncMock(return_value=[{"id": "t1", "agent": "research", "instruction": "r", "depends_on": []}]))
    mocker.patch.object(orch, "_replan_with_research", new=AsyncMock(return_value=[
        {"id": "w1", "agent": "web", "instruction": "w", "depends_on": []},
        {"id": "m1", "agent": "marketing", "instruction": "m", "depends_on": []},
        {"id": "t1", "agent": "technical", "instruction": "t", "depends_on": []},
        {"id": "l1", "agent": "legal", "instruction": "l", "depends_on": []},
        {"id": "s1", "agent": "sales", "instruction": "s", "depends_on": []},
        {"id": "d1", "agent": "design", "instruction": "d", "depends_on": []},
    ]))
    mocker.patch.object(orch, "_generate_detailed_plan", new=AsyncMock(return_value=[]))
    mocker.patch("backend.tools.obsidian_logger._note_path")
    mocker.patch("backend.tools.obsidian_logger.auto_log_if_missing", return_value=False)
    mocker.patch("backend.tools.obsidian_logger.obsidian_session_index", return_value={"indexed": True})

    await orch.run(goal="g", founder_id="f", session_id="s")

    goal_done = next(e for e in published if e.get("type") == "goal_done")
    results = goal_done["results"]
    flat = [v for v in results.values() if isinstance(v, dict)]
    assert any(item.get("url", "").startswith("https://") for item in flat)
    assert any((item.get("ad_images") or [{}])[0].get("url", "").startswith("https://") for item in flat if "ad_images" in item)
    assert any(item.get("files_in_repo") == 24 for item in flat)
    assert any(((item.get("documents") or [{}])[0].get("path", "")).endswith(".pdf") for item in flat if "documents" in item)
    assert any(((item.get("crm_contacts") or [{}])[0].get("email")) for item in flat if "crm_contacts" in item)
    assert any(((item.get("wireframes") or [{}])[0].get("page_type") == "landing") for item in flat if "wireframes" in item)
