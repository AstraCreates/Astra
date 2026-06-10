import io
import zipfile

import pytest
from httpx import ASGITransport, AsyncClient

from backend.config import settings
from backend.core import session_store, workspace_store
from backend.main import app
from backend.missions.company_goal import (
    get_company_goal,
    reset_for_new_launch,
    start_goal,
)
from backend.missions.store import create_mission, list_missions
from backend.tools.company_brain import (
    add_company_brain_record,
    get_company_brain,
    get_company_brain_graph,
    rebuild_company_brain_graph,
    search_company_brain,
)


def test_company_store_and_session_metadata_are_backward_compatible():
    company = workspace_store.create_workspace(
        founder_id="founder_company_spine",
        name="Acme",
        goal="Launch Acme",
    )
    company_id = company["company_id"]

    assert company_id == company["workspace_id"]
    assert workspace_store.get_workspace(company_id)["company_id"] == company_id
    assert workspace_store.list_workspaces("founder_company_spine")[0]["company_id"] == company_id

    session_store.register_session(
        session_id="session_company_spine",
        founder_id="founder_company_spine",
        goal="Launch",
        workspace_id=company_id,
    )
    meta = session_store.get_session_meta("session_company_spine")
    assert meta["company_id"] == company_id
    assert session_store.list_sessions(company_id=company_id)[0]["session_id"] == "session_company_spine"


def test_duplicate_archive_and_export_company():
    company = workspace_store.create_workspace(
        founder_id="founder_company_lifecycle",
        name="Original",
        goal="Build the business",
    )
    company_id = company["company_id"]
    workspace_store.create_chapter(company_id, "session_export")

    duplicate = workspace_store.duplicate_workspace(company_id, name="Second company")
    assert duplicate["company_id"] != company_id
    assert duplicate["duplicated_from_company_id"] == company_id
    assert duplicate["chapter_ids"] == []

    archived = workspace_store.archive_workspace(company_id)
    assert archived["status"] == "archived"
    assert archived["archived_at"]

    payload = workspace_store.export_workspace_zip(company_id)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert set(archive.namelist()) == {
            "company.json",
            "chapters.json",
            "sessions.json",
            "vault.json",
        }


def test_company_id_is_written_to_goals_and_brain_records(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    goal = reset_for_new_launch(
        "founder_company_records",
        "session_company_records",
        "Reach customers",
        "Operate the company",
        company_id="ws_company_records",
    )
    assert goal["company_id"] == "ws_company_records"
    assert get_company_goal(
        "founder_company_records",
        "ws_company_records",
    )["company_id"] == "ws_company_records"

    record = add_company_brain_record(
        founder_id="founder_company_records",
        source="astra",
        title="Company fact",
        content="The company serves first-time founders.",
        metadata={"company_id": "ws_company_records"},
    )
    assert record["record"]["company_id"] == "ws_company_records"


def test_goals_and_brain_are_isolated_between_companies(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    founder_id = "founder_multi_company"
    first_company = "ws_first_company"
    second_company = "ws_second_company"

    for company_id, goal_title, brain_fact in (
        (first_company, "Launch analytics", "The product is an analytics platform."),
        (second_company, "Launch payroll", "The product is a payroll platform."),
    ):
        reset_for_new_launch(
            founder_id,
            f"session_{company_id}",
            goal_title,
            goal_title,
            company_id=company_id,
        )
        start_goal(
            founder_id,
            goal_title,
            [{"title": goal_title, "owner_agents": ["ops"]}],
            company_id=company_id,
        )
        add_company_brain_record(
            founder_id=founder_id,
            source="manual",
            title=goal_title,
            content=brain_fact,
            company_id=company_id,
        )

    first_goal = get_company_goal(founder_id, first_company)
    second_goal = get_company_goal(founder_id, second_company)
    assert first_goal["north_star"] == "Launch analytics"
    assert second_goal["north_star"] == "Launch payroll"
    assert first_goal["current_goal_id"] != second_goal["current_goal_id"]

    first_brain = get_company_brain(founder_id, company_id=first_company)
    second_brain = get_company_brain(founder_id, company_id=second_company)
    assert [record["title"] for record in first_brain["records"]] == ["Launch analytics"]
    assert [record["title"] for record in second_brain["records"]] == ["Launch payroll"]
    assert search_company_brain(
        founder_id,
        "payroll",
        company_id=first_company,
    )["count"] == 0
    assert search_company_brain(
        founder_id,
        "payroll",
        company_id=second_company,
    )["count"] == 1


def test_recurring_missions_and_graph_are_company_scoped(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OBSIDIAN_VAULT", str(tmp_path))
    founder_id = "founder_company_missions"
    first_company = "ws_company_alpha"
    second_company = "ws_company_beta"

    for company_id, name in (
        (first_company, "Alpha sales"),
        (second_company, "Beta sales"),
    ):
        create_mission(
            founder_id=founder_id,
            department="sales",
            name=name,
            goal=f"Grow {name}",
            primary_metric="revenue",
            objectives=[],
            budget={"max_runs_per_day": 1, "max_cost_usd_per_run": 1.0},
            approval_policy="require_approval",
            company_id=company_id,
        )

    assert [mission["name"] for mission in list_missions(founder_id, first_company)] == ["Alpha sales"]
    assert [mission["name"] for mission in list_missions(founder_id, second_company)] == ["Beta sales"]

    add_company_brain_record(
        founder_id,
        "manual",
        "Alpha positioning",
        "Alpha serves startup finance teams.",
        company_id=first_company,
    )
    add_company_brain_record(
        founder_id,
        "notion",
        "Alpha buyer",
        "Alpha finance teams need weekly reports.",
        company_id=first_company,
    )
    rebuilt = rebuild_company_brain_graph(founder_id, first_company)
    first_graph = get_company_brain_graph(founder_id, first_company)
    second_graph = get_company_brain_graph(founder_id, second_company)

    assert rebuilt["node_count"] == 2
    assert len(first_graph["nodes"]) == 2
    assert second_graph["nodes"] == []


@pytest.mark.asyncio
async def test_company_api_enforces_tenant_ownership(monkeypatch):
    monkeypatch.setattr(settings, "astra_require_auth", True)
    monkeypatch.setattr(settings, "astra_trust_auth_headers", True)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/companies",
            headers={"x-astra-user-id": "founder_company_api"},
            json={
                "founder_id": "founder_company_api",
                "name": "API Company",
                "goal": "Test company isolation",
            },
        )
        assert created.status_code == 200
        company_id = created.json()["company_id"]

        denied = await client.get(
            f"/companies/{company_id}",
            headers={"x-astra-user-id": "different_founder"},
        )
        assert denied.status_code == 403

        renamed = await client.patch(
            f"/companies/{company_id}",
            headers={"x-astra-user-id": "founder_company_api"},
            json={"name": "Renamed Company"},
        )
        assert renamed.status_code == 200
        assert renamed.json()["name"] == "Renamed Company"


@pytest.mark.asyncio
async def test_company_scoped_brain_api_does_not_cross_company_boundaries():
    founder_id = "founder_company_brain_api"
    first = workspace_store.create_workspace(founder_id, "First", "First goal")
    second = workspace_store.create_workspace(founder_id, "Second", "Second goal")
    add_company_brain_record(
        founder_id,
        "manual",
        "First secret",
        "Only the first company should see this.",
        company_id=first["company_id"],
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first_response = await client.get(
            f"/brain/{founder_id}?company_id={first['company_id']}",
        )
        second_response = await client.get(
            f"/brain/{founder_id}?company_id={second['company_id']}",
        )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert [record["title"] for record in first_response.json()["records"]] == ["First secret"]
    assert second_response.json()["records"] == []


@pytest.mark.asyncio
async def test_direct_mission_routes_enforce_company_owner(monkeypatch):
    monkeypatch.setattr(settings, "astra_require_auth", True)
    monkeypatch.setattr(settings, "astra_trust_auth_headers", True)
    founder_id = "founder_mission_owner"
    company = workspace_store.create_workspace(founder_id, "Owner company", "Operate")
    mission = create_mission(
        founder_id=founder_id,
        department="ops",
        name="Private operating mission",
        goal="Keep the company moving.",
        primary_metric="tempo",
        objectives=[],
        budget={"max_runs_per_day": 1, "max_cost_usd_per_run": 1.0},
        approval_policy="require_approval",
        company_id=company["company_id"],
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        denied = await client.get(
            f"/api/missions/{mission['id']}",
            headers={"x-astra-user-id": "different_founder"},
        )
        allowed = await client.get(
            f"/api/missions/{mission['id']}",
            headers={"x-astra-user-id": founder_id},
        )

    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json()["company_id"] == company["company_id"]
