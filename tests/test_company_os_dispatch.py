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
        "Clarify audience, offer, and constraints", "Create a local website preview", "Review the preview and prepare a publish approval",
    ]


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


class FakeCompanyOS:
    def __init__(self):
        self.company = {"tasks": [], "task_attempts": [], "events": [], "budget": {"remaining_usd": 5}}

    def get_company_os(self, **_): return self.company
    def create_initiative(self, **kwargs): return {"id": "initiative", **kwargs}
    def create_squad(self, **kwargs): return {"id": "squad", **kwargs}
    def create_mission(self, **kwargs): return {"id": "mission", **kwargs}
    def create_task(self, **kwargs):
        task = {"id": f"task-{len(self.company['tasks'])}", **kwargs}; self.company["tasks"].append(task); return task
    def create_task_attempt(self, **kwargs):
        attempt = {"id": f"attempt-{len(self.company['task_attempts'])}", **kwargs}; self.company["task_attempts"].append(attempt); return attempt
    def create_approval(self, **kwargs): return {"id": "approval", **kwargs}
    def update_task(self, **kwargs): return kwargs
    def update_task_attempt(self, **kwargs): return kwargs
    def append_event(self, **kwargs): self.company["events"].append(kwargs); return kwargs


def _dispatch(monkeypatch):
    fake = FakeCompanyOS()
    monkeypatch.setitem(sys.modules, "backend.company_os", types.SimpleNamespace(**{
        name: getattr(fake, name) for name in ("get_company_os", "create_initiative", "create_squad", "create_mission", "create_task", "create_task_attempt", "create_approval", "update_task", "update_task_attempt", "append_event")
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
