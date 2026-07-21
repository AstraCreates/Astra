import sys
import types


def test_website_requests_route_to_product_technical_with_a_local_preview_plan(monkeypatch):
    from backend.company_os_dispatch import choose_department, specialist_task_plan

    monkeypatch.setattr("backend.company_os_dispatch._extract_work_request_with_model", lambda _intent: {
        "version": 1, "outcome": "Build a website", "deliverables": [], "constraints": [], "entities": [],
        "risk": "internal", "required_capabilities": ["website"], "confidence": 0.9, "requires_triage": False,
    })

    assert choose_department("Make a website for a company that competes with both")[0] == "product_technical"
    assert [item["title"] for item in specialist_task_plan("product_technical", "Make a landing page")] == [
        "Define the local website brief", "Create a local website preview", "Prepare the publication decision", "Publish the website to Vercel",
    ]
    assert all(item["execution_scope"] == "local" for item in specialist_task_plan("product_technical", "Make a landing page")[:3])
    assert specialist_task_plan("product_technical", "Make a landing page")[3]["execution_scope"] == "external"


def test_genuine_ambiguity_triggers_clarification_with_options(monkeypatch):
    from backend.company_os_dispatch import infer_work_request

    monkeypatch.setattr("backend.tools._llm.generate", lambda *_a, **_k: __import__("json").dumps({
        "objective": "Build the MVP", "deliverables": [], "acceptance_criteria": [], "constraints": [], "entities": [],
        "dependencies": [], "primary_capability": "website", "required_capabilities": ["website"], "risk": "internal",
        "clarification_question": "Which platform should the MVP target?",
        "clarification_options": ["iOS", "Android", "Both"],
        "confidence": 0.9,
    }))

    request = infer_work_request("build me an MVP")

    assert request["requires_clarification"] is True
    assert request["clarification_question"] == "Which platform should the MVP target?"
    assert request["clarification_options"] == ["iOS", "Android", "Both"]


def test_no_clarification_question_means_no_clarification(monkeypatch):
    from backend.company_os_dispatch import infer_work_request

    monkeypatch.setattr("backend.tools._llm.generate", lambda *_a, **_k: __import__("json").dumps({
        "objective": "Compare Cofounder and Astra", "deliverables": ["comparison"], "acceptance_criteria": [], "constraints": [],
        "entities": [], "dependencies": [], "primary_capability": "compare", "required_capabilities": ["compare", "research"],
        "risk": "internal", "clarification_question": None, "clarification_options": None, "confidence": 0.95,
    }))

    request = infer_work_request("compare cofounder.co and astracreates.com")

    assert request["requires_clarification"] is False
    assert request["clarification_options"] is None


def test_misspelled_comparison_routes_to_insights_instead_of_triage(monkeypatch):
    from backend.company_os_dispatch import infer_work_request, route_work_request

    monkeypatch.setattr("backend.company_os_dispatch._extract_work_request_with_model", lambda _intent: {
        "version": 1, "outcome": "Compare Cofounder and Astra", "deliverables": ["comparison"], "constraints": [], "entities": ["Cofounder", "Astra"],
        "risk": "internal", "required_capabilities": ["compare", "research"], "confidence": 0.95, "requires_triage": False,
    })
    request = infer_work_request("comparre cofounder.co and astracreates.com")
    route = route_work_request({}, request)

    assert request["requires_triage"] is False
    assert "compare" in request["required_capabilities"]
    assert route["department"] == "research"


def test_multi_capability_request_forms_a_real_handoff_squad(monkeypatch):
    dispatch, store = _dispatch(monkeypatch)
    monkeypatch.setattr(dispatch, "infer_work_request", lambda _intent: {
        "version": 1, "outcome": "Compare products and build a website", "deliverables": [], "constraints": [], "entities": [],
        "risk": "internal", "primary_capability": "website", "required_capabilities": ["compare", "research", "website"], "confidence": 0.95, "requires_triage": False,
    })
    result = dispatch.dispatch_intent("co", "Compare products and build a website")

    assert result["department"] == "product_technical"
    assert [mission["department"] for mission in result["handoff_missions"]] == ["research"]
    assert result["mission"]["depends_on_mission_ids"] == [result["handoff_missions"][0]["id"]]


def test_research_led_comparison_makes_product_delivery_wait_for_evidence(monkeypatch):
    dispatch, _store = _dispatch(monkeypatch)
    monkeypatch.setattr(dispatch, "infer_work_request", lambda _intent: {
        "version": 1, "outcome": "Compare products and build a website", "deliverables": [], "constraints": [], "entities": [],
        "risk": "internal", "primary_capability": "compare", "required_capabilities": ["compare", "research", "website"], "confidence": 0.95, "requires_triage": False,
    })

    result = dispatch.dispatch_intent("co", "Compare products and build a website")

    assert result["department"] == "research"
    product_mission = result["handoff_missions"][0]
    assert product_mission["department"] == "product_technical"
    assert product_mission["depends_on_mission_ids"] == [result["mission"]["id"]]


def test_research_handoff_gets_research_tasks_when_request_also_needs_website(monkeypatch):
    from backend.company_os_dispatch import specialist_task_plan

    request = {
        "required_capabilities": ["compare", "research", "website"],
        "confidence": 0.95,
    }
    tasks = specialist_task_plan("research", "Compare products and build a website", request=request)

    assert [task["title"] for task in tasks] == [
        "Gather validated evidence", "Synthesize findings and uncertainties", "Produce a decision brief",
    ]
    assert tasks[0]["mcp_tool"] == "astra_company_research"


class FakeCompanyOS:
    def __init__(self):
        self.company = {"tasks": [], "task_attempts": [], "events": [], "budget": {"remaining_usd": 5}}
        self.missions = []
        self.task_attempt_updates = []

    def get_company_os(self, **_): return self.company
    def create_initiative(self, **kwargs): return {"id": "initiative", **kwargs}
    def create_squad(self, **kwargs): return {"id": "squad", **kwargs}
    def create_mission(self, **kwargs):
        mission = {"id": f"mission-{len(self.missions)}", **kwargs}
        self.missions.append(mission)
        return mission
    def create_task(self, **kwargs):
        task = {"id": f"task-{len(self.company['tasks'])}", **kwargs}; self.company["tasks"].append(task); return task
    def create_task_attempt(self, **kwargs):
        attempt = {"id": f"attempt-{len(self.company['task_attempts'])}", **kwargs}; self.company["task_attempts"].append(attempt); return attempt
    def create_approval(self, **kwargs): return {"id": "approval", **kwargs}
    def update_mission(self, **kwargs): return kwargs
    def update_task(self, **kwargs): return kwargs
    def update_task_attempt(self, **kwargs):
        self.task_attempt_updates.append(kwargs)
        return kwargs
    def append_event(self, **kwargs): self.company["events"].append(kwargs); return kwargs


def _dispatch(monkeypatch):
    fake = FakeCompanyOS()
    monkeypatch.setitem(sys.modules, "backend.company_os", types.SimpleNamespace(**{
        name: getattr(fake, name) for name in ("get_company_os", "create_initiative", "create_squad", "create_mission", "create_task", "create_task_attempt", "create_approval", "update_mission", "update_task", "update_task_attempt", "append_event")
    }))
    from backend import company_os_dispatch as dispatch
    return dispatch, fake


def test_all_execution_paths_use_the_policy_choke_point(monkeypatch):
    dispatch, store = _dispatch(monkeypatch)
    calls = []
    original = dispatch.enforce_dispatch_policy
    monkeypatch.setattr(dispatch, "enforce_dispatch_policy", lambda *args, **kwargs: (calls.append(args[0]), original(*args, **kwargs))[1])
    task = {"id": "publish", "title": "Publish the launch post", "status": "pending"}
    assert dispatch.execute_task("co", task, lambda _: (_ for _ in ()).throw(AssertionError("must not execute")))["status"] == "awaiting_approval"
    store.company["tasks"] = [{"id": "delete", "title": "Delete customer data", "status": "pending"}]
    assert dispatch.scheduler_tick("co", lambda _: (_ for _ in ()).throw(AssertionError("must not execute")))[0]["status"] == "awaiting_approval"
    assert len(calls) == 2
    assert any(event["event_type"] == "policy.decided" for event in store.company["events"])


def test_execute_task_persists_research_metadata_from_the_executor_result(monkeypatch):
    """_store_artifact() (company_os_runner.py) returns research_metadata/
    evidence_validation as top-level keys, not nested under a "result" key --
    a prior version of this code read result.get("result") first, which
    always resolved to None and silently persisted every research attempt's
    metadata as empty."""
    dispatch, store = _dispatch(monkeypatch)
    task = {"id": "t1", "title": "Gather validated evidence", "status": "pending", "mcp_tool": "astra_company_research",
            "operation": "internal_analysis", "execution_scope": "local"}
    executor_result = {
        "artifact_id": "art1", "source_count": 5,
        "research_metadata": {"model": "deepseek/deepseek-v4-flash", "provider": "deepseek", "search_count": 6},
        "evidence_validation": {"ok": True, "gaps": []},
        "research_status": "validated",
    }

    result = dispatch.execute_task("co", task, lambda _: executor_result)

    assert result["status"] == "completed"
    completed_update = next(u for u in store.task_attempt_updates if u.get("state") == "completed")
    assert completed_update["model"] == "deepseek/deepseek-v4-flash"
    assert completed_update["provider"] == "deepseek"
    assert completed_update["research_metadata"] == executor_result["research_metadata"]
    assert completed_update["evidence_validation"] == executor_result["evidence_validation"]


def test_local_publication_preparation_never_requires_approval():
    from backend.company_os_dispatch import enforce_dispatch_policy

    decision = enforce_dispatch_policy({"title": "Prepare the publication decision", "operation": "internal_review", "execution_scope": "local"})
    assert decision["decision"] == "auto"


def test_restart_duplicate_protection_reads_durable_attempts(monkeypatch):
    dispatch, store = _dispatch(monkeypatch)
    task = {"id": "research-1", "title": "Research competitors"}
    ran = []
    first = dispatch.execute_task("co", task, lambda _: ran.append(True), idempotency_key="durable-key")
    second = dispatch.execute_task("co", task, lambda _: ran.append(True), idempotency_key="durable-key")
    assert first["status"] == "completed"
    assert second["status"] == "duplicate"
    assert ran == [True]
    assert len(store.company["task_attempts"]) == 1
