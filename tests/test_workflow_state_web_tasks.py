from backend.workflow_state import build_session_state


def test_workflow_state_surfaces_web_task_lifecycle():
    events = [
        (1, {"type": "agent_start", "agent": "web_navigator"}),
        (2, {"type": "web_task_started", "task_id": "task-1", "service": "vercel", "task_type": "retrieve_deploy_token", "agent": "web_navigator", "goal": "Get token"}),
        (3, {"type": "web_task_state", "task_id": "task-1", "service": "vercel", "task_type": "retrieve_deploy_token", "agent": "web_navigator", "state": "api_keys", "note": "Opened token settings", "url": "https://vercel.com/account/tokens"}),
        (4, {"type": "web_task_needs_user", "task_id": "task-1", "service": "vercel", "task_type": "retrieve_deploy_token", "agent": "web_navigator", "blocker": {"kind": "2fa", "message": "Need a 2FA code", "fields": [{"key": "otp_code", "label": "2FA code", "type": "text"}]}, "result": {"status": "needs_user", "resume_token": "task-1", "evidence": {"final_url": "https://vercel.com/login", "checks_passed": []}, "blocker": {"kind": "2fa", "message": "Need a 2FA code", "fields": [{"key": "otp_code", "label": "2FA code", "type": "text"}]}}}),
    ]

    state = build_session_state("session-web-task", events)

    assert "web_tasks" in state
    assert len(state["web_tasks"]) == 1
    task = state["web_tasks"][0]
    assert task["task_id"] == "task-1"
    assert task["status"] == "needs_user"
    assert task["service"] == "vercel"
    assert task["agent"] == "web_navigator"
    assert task["blocker"]["kind"] == "2fa"
    assert task["evidence"]["final_url"] == "https://vercel.com/login"
