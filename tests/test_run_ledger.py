from backend.run_ledger import get_run, ledger_metrics, list_runs, normalize_run_row, record_run_event


def test_run_ledger_tracks_run_lifecycle(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("backend.run_ledger._root", lambda: tmp_path / ".astra" / "run_ledger")
    session_id = "ledger_session"

    record_run_event(session_id, 1, {
        "type": "goal_start",
        "goal": "Build a sales stack",
        "founder_id": "founder_ledger",
        "ts_iso": "2026-05-01T00:00:00Z",
        "ts_unix": 1777593600,
    })
    record_run_event(session_id, 2, {
        "type": "stack_selected",
        "stack": {"stack_id": "sales_stack", "name": "Sales Stack"},
        "ts_iso": "2026-05-01T00:00:01Z",
        "ts_unix": 1777593601,
    })
    record_run_event(session_id, 3, {
        "type": "agent_start",
        "agent": "sales",
        "task_id": "t_sales",
        "ts_iso": "2026-05-01T00:00:02Z",
        "ts_unix": 1777593602,
    })
    record_run_event(session_id, 4, {
        "type": "stack_artifact",
        "artifact": {"key": "lead_list"},
        "ts_iso": "2026-05-01T00:00:03Z",
        "ts_unix": 1777593603,
    })
    record_run_event(session_id, 5, {
        "type": "agent_done",
        "agent": "sales",
        "task_id": "t_sales",
        "ts_iso": "2026-05-01T00:00:04Z",
        "ts_unix": 1777593604,
    })
    record_run_event(session_id, 6, {
        "type": "goal_done",
        "ts_iso": "2026-05-01T00:00:05Z",
        "ts_unix": 1777593605,
    })

    row = get_run(session_id)
    assert row is not None
    assert row["status"] == "done"
    assert row["founder_id"] == "founder_ledger"
    assert row["stack_id"] == "sales_stack"
    assert row["done_agents"] == 1
    assert row["artifact_count"] == 1
    assert row["duration_seconds"] == 5

    metrics = ledger_metrics()
    assert metrics["runs_total"] == 1
    assert metrics["runs_done"] == 1
    assert metrics["artifact_count"] == 1


def test_run_ledger_tracks_errors_and_filters(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("backend.run_ledger._root", lambda: tmp_path / ".astra" / "run_ledger")
    record_run_event("ok_run", 1, {"type": "goal_start", "founder_id": "f1", "goal": "ok", "ts_iso": "2026-05-01T00:00:00Z"})
    record_run_event("error_run", 1, {"type": "goal_start", "founder_id": "f2", "goal": "bad", "ts_iso": "2026-05-01T00:00:00Z"})
    record_run_event("error_run", 2, {"type": "agent_error", "agent": "web", "error": "deploy failed", "ts_iso": "2026-05-01T00:00:01Z"})
    record_run_event("error_run", 3, {"type": "goal_error", "error": "run failed", "ts_iso": "2026-05-01T00:00:02Z"})

    metrics = ledger_metrics()
    assert metrics["runs_total"] == 2
    assert metrics["runs_error"] == 1

    filtered = list_runs(founder_id="f2", status="error")
    assert len(filtered) == 1
    assert filtered[0]["session_id"] == "error_run"
    assert filtered[0]["errors"][0]["message"] == "run failed"


def test_run_ledger_normalizes_terminal_agent_without_goal_done_as_stalled():
    row = {
        "session_id": "s",
        "status": "running",
        "last_event_type": "agent_done",
        "agents": {
            "research": {"agent": "research", "status": "done"},
        },
        "running_agents": 0,
    }

    normalized = normalize_run_row(row)

    assert normalized["status"] == "stalled"
    assert "never emitted goal_done" in normalized["stalled_reason"]


def test_run_ledger_keeps_active_running_session_running():
    row = {
        "session_id": "s",
        "status": "running",
        "last_event_type": "agent_action",
        "agents": {
            "research": {"agent": "research", "status": "running"},
        },
        "running_agents": 1,
    }

    normalized = normalize_run_row(row)

    assert normalized["status"] == "running"


def test_run_ledger_normalizes_done_session_with_running_agents_as_stalled():
    row = {
        "session_id": "s",
        "status": "done",
        "last_event_type": "goal_done",
        "agents": {
            "research": {"agent": "research", "status": "done"},
            "design": {"agent": "design", "status": "running"},
        },
        "running_agents": 1,
    }

    normalized = normalize_run_row(row)

    assert normalized["status"] == "stalled"
    assert "goal_done" in normalized["stalled_reason"]
