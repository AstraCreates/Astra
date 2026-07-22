import sys
import types


def test_website_requests_route_to_product_technical_with_a_local_preview_plan(monkeypatch):
    from backend.company_os_dispatch import choose_department, specialist_task_plan

    monkeypatch.setattr("backend.company_os_dispatch._extract_work_request_with_model", lambda _intent: {
        "version": 1, "outcome": "Build a website", "deliverables": [], "constraints": [], "entities": [],
        "risk": "internal", "required_capabilities": ["website"], "confidence": 0.9, "requires_triage": False,
    })

    assert choose_department("Make a website for a company that competes with both")[0] == "product_technical"
    plan = specialist_task_plan("product_technical", "Make a landing page")
    assert any(item["title"] == "Create a local website preview" for item in plan)
    assert any(item["title"] == "Design the technical architecture" for item in plan)
    assert all(item["execution_scope"] == "local" for item in plan[:-1])
    assert plan[-1]["execution_scope"] == "external"


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


def test_multi_capability_request_forms_a_role_aware_squad_dag(monkeypatch):
    dispatch, store = _dispatch(monkeypatch)
    monkeypatch.setattr(dispatch, "infer_work_request", lambda _intent: {
        "version": 1, "outcome": "Compare products and build a website", "deliverables": [], "constraints": [], "entities": [],
        "risk": "internal", "primary_capability": "website", "required_capabilities": ["compare", "research", "website"], "confidence": 0.95, "requires_triage": False,
    })
    result = dispatch.dispatch_intent("co", "Compare products and build a website")

    assert result["department"] == "product_technical"
    assert result["squad_profile"]["role_keys"] == ["technical_lead", "frontend_engineer", "architect"]
    assert [mission["department"] for mission in result["handoff_missions"]] == ["research"]
    tasks = {task["role_key"]: task for task in result["tasks"]}
    assert tasks["technical_lead"]["role_id"]
    product_build = next(task for task in result["tasks"] if task["name"].startswith("Create a local website preview"))
    assert product_build["depends_on_task_ids"]


def test_research_led_comparison_keeps_product_delivery_in_the_same_squad(monkeypatch):
    dispatch, _store = _dispatch(monkeypatch)
    monkeypatch.setattr(dispatch, "infer_work_request", lambda _intent: {
        "version": 1, "outcome": "Compare products and build a website", "deliverables": [], "constraints": [], "entities": [],
        "risk": "internal", "primary_capability": "compare", "required_capabilities": ["compare", "research", "website"], "confidence": 0.95, "requires_triage": False,
    })

    result = dispatch.dispatch_intent("co", "Compare products and build a website")

    assert result["department"] == "research"
    assert result["squad_profile"]["role_keys"] == ["research_lead", "market_analyst", "scientific_analyst"]
    assert [mission["department"] for mission in result["handoff_missions"]] == ["product_technical"]


def test_research_handoff_gets_research_tasks_when_request_also_needs_website(monkeypatch):
    from backend.company_os_dispatch import specialist_task_plan

    request = {
        "required_capabilities": ["compare", "research", "website"],
        "confidence": 0.95,
    }
    tasks = specialist_task_plan("research", "Compare products and build a website", request=request)

    assert [task["task_key"] for task in tasks] == ["research-market_analyst", "research-scientific_analyst", "research-review", "research-brief"]
    assert all(task["mcp_tool"] == "astra_company_research" for task in tasks[:2])
    assert tasks[2]["dependencies"] == ["research-market_analyst", "research-scientific_analyst"]


def test_research_tasks_are_per_subject_when_planner_extracts_entities():
    """Real bug: research tasks used to render as three identical
    'Gather / Synthesize / Produce a decision brief' rows with the user's
    goal pasted after each via f"{title}. Outcome: {intent}". With named
    entities the titles must actually mention the subject so the squad
    panel shows distinct work, and the descriptions must not echo the
    same intent back at the user twice in a row.
    """
    from backend.company_os_dispatch import specialist_task_plan

    request = {
        "required_capabilities": ["research"],
        "confidence": 0.95,
        "entities": ["Northrop Grumman"],
        "objective": "What is Northrop Grumman and how do they make money",
        "outcome": "What is Northrop Grumman and how do they make money",
        "deliverables": ["company profile", "revenue mix"],
    }
    intent = "what is Northrop Grumman and how do they make money"
    tasks = specialist_task_plan("research", intent, request=request)

    titles = [task["title"] for task in tasks]
    descriptions = [task["description"] for task in tasks]
    # Every row must name the subject -- no row is just "Gather validated evidence" alone.
    assert all("Northrop Grumman" in title for title in titles), titles
    # Titles must be distinct -- the bug was that all three were structurally identical.
    assert len(set(titles)) == 4, titles
    # The redundant "Outcome: <intent>" suffix must be gone.
    for description in descriptions:
        assert "Outcome:" not in description, description
        assert intent not in description, description
    # MCP contract preserved.
    assert tasks[0]["mcp_tool"] == "astra_company_research"
    assert tasks[0]["operation"] == "internal_analysis"
    assert tasks[1]["operation"] == "internal_analysis"
    assert tasks[2]["operation"] == "internal_review"
    assert tasks[3]["operation"] == "draft"


def test_research_tasks_fall_back_to_generics_when_no_signal_extracted():
    """When the planner extracted nothing (empty entities/deliverables/objective),
    titles stay generic instead of smearing the long raw intent into every row."""
    from backend.company_os_dispatch import specialist_task_plan

    request = {
        "required_capabilities": ["research"],
        "confidence": 0.95,
        "entities": [],
        "objective": "",
        "deliverables": [],
    }
    tasks = specialist_task_plan("research", "vague broad topic with no specifics", request=request)

    titles = [task["title"] for task in tasks]
    # No length-noisy "... with no specifics" smearing in the titles.
    assert titles == [
        "Market Analyst: gather validated evidence",
        "Scientific Analyst: gather validated evidence",
        "Review evidence and resolve conflicts",
        "Produce a decision brief",
    ]
    # No Outcome: suffix even in the fallback case.
    assert all("Outcome:" not in task["description"] for task in tasks)


def test_website_tasks_are_per_subject_when_planner_extracts_entities():
    """The website branch also gains entity-specific titles -- previously
    'Define the local website brief' / 'Create a local website preview' /
    'Prepare the publication decision' / 'Publish the website to Vercel'
    with the intent appended at the end of each."""
    from backend.company_os_dispatch import specialist_task_plan

    request = {
        "required_capabilities": ["website", "landing page"],
        "confidence": 0.95,
        "entities": ["Acme"],
        "deliverables": ["landing page"],
        "objective": "Launch a landing page for Acme",
    }
    tasks = specialist_task_plan("product_technical", "build a landing page for acme", request=request)

    titles = " | ".join(task["title"] for task in tasks)
    assert "Acme" in titles, titles
    # The deploy step stays last and stays external.
    assert tasks[-1]["operation"] == "external_deploy"
    assert tasks[-1]["mcp_tool"] == "vercel_deploy"
    assert tasks[-1]["execution_scope"] == "external"
    # No description echoes the raw intent.
    assert all("Outcome:" not in task["description"] for task in tasks)



class FakeCompanyOS:
    def __init__(self):
        self.company = {"tasks": [], "task_attempts": [], "events": [], "squad_roles": [], "squad_meetings": [], "budget": {"remaining_usd": 5}}
        self.missions = []
        self.squads = []
        self.task_attempt_updates = []

    def get_company_os(self, **_): return self.company
    def create_initiative(self, **kwargs): return {"id": "initiative", **kwargs}
    def create_squad(self, **kwargs):
        squad = {"id": f"squad-{len(self.squads)}", **kwargs}; self.squads.append(squad); return squad
    def create_squad_role(self, **kwargs):
        role = {"id": f"role-{len(self.company['squad_roles'])}", **kwargs}; self.company["squad_roles"].append(role); return role
    def create_squad_meeting(self, **kwargs):
        meeting = {"id": f"meeting-{len(self.company['squad_meetings'])}", **kwargs}; self.company["squad_meetings"].append(meeting); return meeting
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
        name: getattr(fake, name) for name in ("get_company_os", "create_initiative", "create_squad", "create_squad_role", "create_squad_meeting", "create_mission", "create_task", "create_task_attempt", "create_approval", "update_mission", "update_task", "update_task_attempt", "append_event")
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


def test_role_profile_selects_relevant_specialists_and_caps_squad_size():
    from backend.company_os_dispatch import select_squad_profile

    profile = select_squad_profile({
        "objective": "Compare a regulated market using scientific evidence",
        "deliverables": ["competitive comparison", "evidence brief", "regulatory analysis"],
        "required_capabilities": ["compare", "evidence research", "competitive analysis"],
        "risk": "internal",
    }, "research")

    assert profile["version"] == 1
    assert profile["role_keys"][0] == "research_lead"
    assert len(profile["role_keys"]) == 4
    assert {"market_analyst", "scientific_analyst", "customer_regulatory_analyst"}.issubset(profile["role_keys"])


def test_dispatch_persists_charter_role_records_and_task_contract(monkeypatch):
    dispatch, store = _dispatch(monkeypatch)
    request = {
        "version": 1, "outcome": "Compare options and build a website", "deliverables": ["website"],
        "acceptance_criteria": ["Cited evidence", "Working local preview"], "constraints": ["Use public sources"],
        "dependencies": ["Brand context"], "entities": ["Acme"], "risk": "internal",
        "primary_capability": "website", "required_capabilities": ["website", "research", "compare"],
        "confidence": 0.95, "requires_clarification": False,
    }
    result = dispatch.dispatch_intent("co", "Compare options and build a website", work_request=request)

    assert len(store.company["squad_meetings"]) == 2
    assert store.company["squad_meetings"][0]["meeting_type"] == "charter"
    assert [role["role_key"] for role in store.company["squad_roles"]] == ["technical_lead", "frontend_engineer", "architect", "research_lead", "market_analyst", "scientific_analyst"]
    for task in result["tasks"]:
        assert task["role_id"]
        assert task["purpose"] and task["deliverable"]
        assert isinstance(task["inputs"], list)
        assert isinstance(task["expected_outputs"], list)
        assert isinstance(task["acceptance_criteria"], list)
        assert isinstance(task["depends_on_task_ids"], list)
        assert "dependencies" not in task and "dependency_task_ids" not in task
        assert task["parallel_group"]
        assert isinstance(task["handoffs"], list)
    assert next(task for task in store.company["tasks"] if task["mcp_tool"] == "astra_company_research")["role_key"] == "market_analyst"


def test_same_subject_product_followup_reuses_research_initiative(tmp_path, monkeypatch):
    from backend import company_os
    import backend.company_os_dispatch as dispatch

    monkeypatch.setenv("ASTRA_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.chdir(tmp_path)
    company_os.create_company_os("acme", "founder", "Acme")
    research_request = {
        "version": 1, "outcome": "Compare BlackRock and Blackstone", "deliverables": ["comparison"],
        "constraints": [], "entities": ["BlackRock", "Blackstone"], "risk": "internal",
        "primary_capability": "research", "required_capabilities": ["research", "compare", "evidence research"],
        "confidence": 0.95, "requires_clarification": False,
    }
    research = dispatch.dispatch_intent("acme", "what is the difference between BlackRock and Blackstone", work_request=research_request)
    product_request = {
        "version": 1, "outcome": "Build a website comparing BlackRock and Blackstone", "deliverables": ["local website"],
        "constraints": [], "entities": ["BlackRock", "Blackstone"], "risk": "internal",
        "primary_capability": "website", "required_capabilities": ["website", "local preview"],
        "confidence": 0.95, "requires_clarification": False,
    }

    product = dispatch.dispatch_intent("acme", "build a website comparing BlackRock and Blackstone",
                                       forced_initiative_id=research["initiative"]["initiative_id"], work_request=product_request)

    assert product["initiative"]["initiative_id"] == research["initiative"]["initiative_id"]
    state = company_os.get_company_os("acme")
    assert {squad["department"] for squad in state["squads"]} == {"research", "product_technical"}


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
