import json

import pytest
from httpx import ASGITransport, AsyncClient

from backend import company_os
from backend.config import settings


def test_company_os_lifecycle_and_context_inheritance(tmp_path):
    root = tmp_path / "workspace" / "company"
    company = company_os.create_company_os("acme", "founder", "Acme", root=root)
    initiative = company_os.create_initiative("acme", "Launch", initiative_id="i1", root=root)
    squad = company_os.create_squad("acme", initiative["initiative_id"], "Growth", squad_id="s1", root=root)
    task = company_os.create_task("acme", "i1", "s1", "Email", task_id="t1", root=root)
    company_os.create_task_attempt("acme", task["task_id"], attempt_id="a1", root=root)
    company_os.append_message("acme", "Starting", scope="task", scope_id="t1", root=root)
    company_os.add_context_record("acme", "voice", "calm", root=root)
    company_os.add_context_record("acme", "voice", "direct", scope="initiative", scope_id="i1", root=root,
                                  promoted_revision=True, supersedes="company-voice-v1")
    company_os.add_context_record("acme", "audience", "founders", scope="squad", scope_id="s1", root=root)
    company_os.add_context_record("acme", "channel", "email", scope="task", scope_id="t1", root=root)

    stored = company_os.get_company_os("acme", root=root)
    assert {key: stored[key] for key in ("company_id", "founder_id", "name", "state")} == {
        "company_id": "acme", "founder_id": "founder", "name": "Acme", "state": "active"}
    assert len(stored["task_attempts"]) == 1
    assert company_os.resolve_context("acme", initiative_id="i1", squad_id="s1", task_id="t1", root=root) == {
        "voice": "direct", "audience": "founders", "channel": "email"}
    assert company_os.get_company_os("acme", root=root)["context_records"][0]["value"] == "calm"


def test_events_validate_checksums_and_recover_only_torn_trailing_event(tmp_path):
    root = tmp_path / "company"
    company_os.create_company_os("acme", "founder", "Acme", root=root)
    company_os.create_initiative("acme", "One", root=root)
    event_path = next((root / "acme").glob("events-*.jsonl"))
    with event_path.open("ab") as handle:
        handle.write(b'{"sequence":2')
    events = company_os.replay_events("acme", root=root)
    assert len(events) == 1
    assert event_path.read_bytes().endswith(b"\n")

    company_os.create_initiative("acme", "Two", root=root)
    lines = event_path.read_text(encoding="utf-8").splitlines()
    corrupted = json.loads(lines[0])
    corrupted["payload"]["name"] = "tampered"
    event_path.write_text(json.dumps(corrupted) + "\n" + lines[1] + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="event checksum mismatch"):
        company_os.replay_events("acme", root=root)


def test_snapshot_checksum_rejects_tampering(tmp_path):
    root = tmp_path / "company"
    company_os.create_company_os("acme", "founder", "Acme", root=root)
    snapshot = root / "acme" / "snapshot.json"
    payload = json.loads(snapshot.read_text(encoding="utf-8"))
    payload["state"]["name"] = "Tampered"
    snapshot.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="snapshot.*checksum mismatch"):
        company_os.get_company_os("acme", root=root)


def test_snapshot_compaction_and_scope_validation(tmp_path):
    root = tmp_path / "company"
    company_os.create_company_os("acme", "f1", "Acme", root=root)
    company_os.create_initiative("acme", "One", initiative_id="i1", root=root)
    before = company_os.snapshot("acme", root=root)
    assert before["initiatives"][0]["initiative_id"] == "i1"
    company_os.compact("acme", root=root)
    assert list((root / "acme").glob("events-*.jsonl")) == []
    assert company_os.get_company_os("acme", root=root)["initiatives"][0]["name"] == "One"
    assert [item["company_id"] for item in company_os.list_company_os("f1", root=root)] == ["acme"]
    with pytest.raises(ValueError, match="unknown initiative_id"):
        company_os.create_squad("acme", "missing", "Nope", root=root)


def test_company_operations_is_a_single_standing_initiative(tmp_path):
    root = tmp_path / "company"
    company_os.create_company_os("acme", "f1", "Acme", root=root)
    first = company_os.ensure_company_operations("acme", root=root)
    second = company_os.ensure_company_operations("acme", root=root)
    stored = company_os.get_company_os("acme", root=root)
    assert first["initiative_id"] == second["initiative_id"]
    assert len(stored["initiatives"]) == len(stored["squads"]) == len(stored["missions"]) == 1


def test_canonical_context_requires_a_promoted_revision_to_override(tmp_path):
    root = tmp_path / "company"
    company_os.create_company_os("acme", "f1", "Acme", root=root)
    company_os.create_initiative("acme", "Launch", initiative_id="i1", root=root)
    company_os.add_context_record("acme", "brand", "careful", root=root)
    company_os.add_context_record("acme", "brand", "reckless", scope="initiative", scope_id="i1", root=root)
    assert company_os.resolve_context("acme", initiative_id="i1", root=root)["brand"] == "careful"
    company_os.add_context_record("acme", "brand", "bold", scope="initiative", scope_id="i1", root=root,
                                  promoted_revision=True, supersedes="company-brand-v1")
    assert company_os.resolve_context("acme", initiative_id="i1", root=root)["brand"] == "bold"


def test_initiative_rollup_requires_acceptance_and_keeps_multiple_squads(tmp_path):
    root = tmp_path / "company"
    company_os.create_company_os("acme", "f1", "Acme", root=root)
    initiative = company_os.create_initiative("acme", "Launch", initiative_id="i1", root=root,
                                              success_criteria=["Founder accepts the launch brief"])
    first = company_os.create_squad("acme", initiative["initiative_id"], "Product", squad_id="s1", root=root)
    second = company_os.create_squad("acme", initiative["initiative_id"], "Growth", squad_id="s2", root=root)
    first_mission = company_os.create_mission("acme", "i1", first["squad_id"], "Build", mission_id="m1", root=root, state="done")
    second_mission = company_os.create_mission("acme", "i1", second["squad_id"], "Launch", mission_id="m2", root=root, state="done")
    company_os.create_task("acme", "i1", first["squad_id"], "Preview", mission_id=first_mission["mission_id"], root=root, state="done")
    company_os.create_task("acme", "i1", second["squad_id"], "Review", mission_id=second_mission["mission_id"], root=root, state="done")

    company_os.reconcile_initiatives("acme", root=root)
    state = company_os.get_company_os("acme", root=root)
    assert state["initiatives"][0]["state"] == "planned"
    assert state["initiatives"][0]["progress"] == 100
    assert state["initiatives"][0]["squad_count"] == 2

    company_os.update_initiative("acme", "i1", root=root, acceptance_confirmed=True)
    company_os.reconcile_initiatives("acme", root=root)
    assert company_os.get_company_os("acme", root=root)["initiatives"][0]["state"] == "done"


def test_archived_artifacts_skip_the_library_mirror(tmp_path, monkeypatch):
    # A research mission's raw evidence and mid-pipeline synthesis note are
    # created already-archived (working material, not something a founder
    # asked for) specifically so they don't clutter the Library with 2 extra
    # downloadable files per request. The Library has no archived concept of
    # its own, so this has to be enforced by never mirroring in the first
    # place, not by hiding it after the fact.
    root = tmp_path / "company"
    company_os.create_company_os("acme", "f1", "Acme", root=root)
    calls = []
    monkeypatch.setattr(company_os, "_mirror_artifact_to_library", lambda *a, **k: (calls.append(1), None)[1])

    company_os.create_artifact("acme", "Raw evidence", task_id="t1", state="archived", root=root)
    assert calls == []

    company_os.create_artifact("acme", "Findings", task_id="t2", root=root)
    assert calls == [1]


@pytest.mark.asyncio
async def test_retry_route_unblocks_a_task_and_relaunches_its_mission(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRA_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "astra_require_auth", True)
    monkeypatch.setattr(settings, "astra_trust_auth_headers", True)
    from backend.main import app

    company_os.create_company_os("acme", "founder", "Acme")
    initiative = company_os.create_initiative("acme", "Research", initiative_id="i1")
    squad = company_os.create_squad("acme", "i1", "Insights", squad_id="s1")
    mission = company_os.create_mission("acme", "i1", "s1", "Research mission", mission_id="m1")
    task = company_os.create_task("acme", "i1", "s1", "Gather validated evidence", task_id="t1", mission_id="m1",
                                  state="blocked", blocked_reason="Research evidence did not meet the source-quality gate.")

    relaunched = []
    monkeypatch.setattr("backend.company_os_runner.launch_mission", lambda company_id, mission_id: relaunched.append((company_id, mission_id)))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/companies/acme/os/tasks/t1/retry",
            params={"founder_id": "founder"},
            headers={"x-astra-user-id": "founder"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    updated_task = next(item for item in body["company"]["tasks"] if item["task_id"] == "t1")
    assert updated_task["state"] == "pending"
    assert updated_task.get("blocked_reason") is None
    assert relaunched == [("acme", "m1")]


@pytest.mark.asyncio
async def test_retry_route_rejects_a_task_that_is_not_blocked(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRA_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "astra_require_auth", True)
    monkeypatch.setattr(settings, "astra_trust_auth_headers", True)
    from backend.main import app

    company_os.create_company_os("acme", "founder", "Acme")
    company_os.create_initiative("acme", "Research", initiative_id="i1")
    company_os.create_squad("acme", "i1", "Insights", squad_id="s1")
    company_os.create_task("acme", "i1", "s1", "Gather validated evidence", task_id="t1", state="done")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/companies/acme/os/tasks/t1/retry",
            params={"founder_id": "founder"},
            headers={"x-astra-user-id": "founder"},
        )

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_copilot_route_keeps_the_founder_bubble_clean_but_feeds_attachments_to_the_llm(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRA_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "astra_require_auth", True)
    monkeypatch.setattr(settings, "astra_trust_auth_headers", True)
    from backend.main import app

    company_os.create_company_os("acme", "founder", "Acme")

    seen_messages = []

    async def fake_coordinate_turn(company_id, message, *, proposed_spend=0.0):
        seen_messages.append(message)
        return {"message": "On it.", "dispatch": None}
    monkeypatch.setattr("backend.api.company_os_routes.coordinate_turn", fake_coordinate_turn)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/companies/acme/os/copilot",
            json={
                "founder_id": "founder",
                "message": "Summarize this",
                "attachments": [{"name": "notes.txt", "content": "Q3 revenue is up 12%."}],
            },
            headers={"x-astra-user-id": "founder"},
        )

    assert response.status_code == 200
    # The LLM-facing message carries the attachment content...
    assert "Q3 revenue is up 12%" in seen_messages[0]
    # ...but the durable, founder-visible chat bubble stays exactly what they typed.
    founder_bubble = next(m for m in company_os.get_company_os("acme")["conversation"] if m["author"] == "founder")
    assert founder_bubble["message"] == "Summarize this"


@pytest.mark.asyncio
async def test_edit_message_archives_everything_after_it_and_resubmits(tmp_path, monkeypatch):
    monkeypatch.setenv("ASTRA_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "astra_require_auth", True)
    monkeypatch.setattr(settings, "astra_trust_auth_headers", True)
    from backend.main import app

    company_os.create_company_os("acme", "founder", "Acme")
    company_os.append_message("acme", "what is Blackstone", author="founder", role="user", message_id="m1")
    company_os.append_message("acme", "Blackstone is an asset manager.", author="copilot", role="assistant", kind="chat", message_id="m2")
    company_os.append_message("acme", "and how do they make money", author="founder", role="user", message_id="m3")
    company_os.append_message("acme", "Management fees and carried interest.", author="copilot", role="assistant", kind="chat", message_id="m4")

    seen_messages = []

    async def fake_coordinate_turn(company_id, message, *, proposed_spend=0.0):
        seen_messages.append(message)
        return {"message": "Looking into Apple instead.", "dispatch": None}
    monkeypatch.setattr("backend.api.company_os_routes.coordinate_turn", fake_coordinate_turn)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch(
            "/companies/acme/os/messages/m1",
            json={"founder_id": "founder", "message": "what is Apple"},
            headers={"x-astra-user-id": "founder"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["message"] == "Looking into Apple instead."
    # The edited message's own new text is what gets resubmitted, not the old one.
    assert seen_messages == ["what is Apple"]

    state = company_os.get_company_os("acme")
    edited = next(m for m in state["conversation"] if m["message_id"] == "m1")
    assert edited["message"] == "what is Apple"
    assert not edited.get("archived")
    for stale_id in ("m2", "m3", "m4"):
        stale = next(m for m in state["conversation"] if m["message_id"] == stale_id)
        assert stale.get("archived") is True
