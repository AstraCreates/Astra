"""Durable workflow state snapshots.

The event stream is the source of truth while a run is active. This module
condenses that stream into a compact state document that can be persisted and
restored after completion or backend restarts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.session_digest import build_session_digest
from backend.workboard import build_session_workboard

_LARGE_STRING_LIMIT = 40_000


def _state_root() -> Path:
    root = Path(".astra/workflows")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _state_path(session_id: str) -> Path:
    safe = "".join(ch for ch in session_id if ch.isalnum() or ch in {"_", "-", "."})[:120] or "session"
    return _state_root() / f"{safe}.json"


def build_session_state(session_id: str, events: list[tuple[int, dict]]) -> dict[str, Any]:
    event_dicts = [event for _, event in events]
    session_meta = _session_meta_snapshot(session_id)
    founder_id = next(
        (str(event.get("founder_id")) for event in event_dicts if event.get("founder_id")),
        str(session_meta.get("founder_id") or ""),
    )
    company_id = next(
        (str(event.get("company_id")) for event in event_dicts if event.get("company_id")),
        str(session_meta.get("company_id") or founder_id),
    )
    company_goal = None
    if founder_id:
        try:
            from backend.missions.company_goal import get_company_goal
            company_goal = get_company_goal(founder_id, company_id)
        except Exception:
            company_goal = None
    stack = next((event.get("stack") for event in event_dicts if event.get("type") == "stack_selected"), None)
    operating_plan = next(
        (event.get("operating_plan") for event in reversed(event_dicts) if event.get("type") == "stack_operating_plan"),
        None,
    )
    manifest = next(
        (event.get("manifest") for event in reversed(event_dicts) if event.get("type") == "stack_manifest"),
        None,
    )
    execution_contract = next(
        (event.get("execution_contract") for event in reversed(event_dicts) if event.get("type") == "stack_execution_contract"),
        None,
    )
    execution_blueprint = next(
        (event.get("execution_blueprint") for event in reversed(event_dicts) if event.get("type") == "stack_execution_blueprint"),
        None,
    )
    genome = next((event.get("genome") for event in reversed(event_dicts) if event.get("type") == "company_genome"), None)
    approval_workflow = _approval_workflow_snapshot(session_id)
    approvals: dict[str, dict[str, Any]] = {}
    artifacts: dict[str, dict[str, Any]] = {}
    artifact_verifications: dict[str, dict[str, Any]] = {}
    lane_status: dict[str, dict[str, Any]] = {}
    outcomes: list[dict[str, Any]] = []
    saferun: dict[str, dict[str, Any]] = {}
    web_tasks: dict[str, dict[str, Any]] = {}
    final_status = "running"
    agent_status: dict[str, str] = {}
    agents: dict[str, dict[str, Any]] = {}
    preview_url = ""
    deployment_checks: list[dict[str, Any]] = []
    pending_agent_question: dict[str, Any] | None = None

    for event in event_dicts:
        event_type = event.get("type")
        _update_agent_snapshot(agents, event)
        if event_type == "goal_start":
            final_status = "running"
        if event_type == "agent_build" and event.get("kind") == "deploy" and event.get("url"):
            preview_url = event["url"]
        elif event_type == "agent_done" and isinstance(event.get("result"), dict):
            _u = event["result"].get("deploy_url") or event["result"].get("url")
            if _u:
                preview_url = _u
        elif event_type == "deployment_check_failed":
            deployment_checks.append({
                "agent": str(event.get("agent") or ""),
                "url": str(event.get("url") or ""),
                "status": str(event.get("status") or ""),
            })
        if event_type == "approval_request" and event.get("request"):
            request = event["request"]
            item = _approval_request_state(request)
            approvals[item.get("key", "")] = item
        elif event_type == "stack_approval_queue":
            for item in event.get("approval_queue", []):
                approvals[item.get("key", "")] = item
        elif event_type == "stack_approval_decision":
            key = event.get("gate_key", "")
            approvals[key] = {**approvals.get(key, {"key": key}), "status": event.get("decision"), "note": event.get("note")}
        elif event_type == "stack_artifact" and event.get("artifact"):
            artifact = event["artifact"]
            artifacts[artifact.get("key", "")] = artifact
        elif event_type == "stack_artifact_verification" and event.get("verification"):
            verification = event["verification"]
            artifact_verifications[verification.get("lane_id") or verification.get("task_id") or verification.get("agent", "")] = verification
        elif event_type == "stack_lane_status":
            lane_id = event.get("lane_id") or event.get("agent") or ""
            lane_status[lane_id] = {**lane_status.get(lane_id, {}), **event}
        elif event_type == "outcome_recorded" and event.get("outcome"):
            outcomes.append(event["outcome"])
        elif event_type == "saferun_action" and event.get("action"):
            action = event["action"]
            saferun[action.get("id", "")] = action
        elif event_type == "saferun_result":
            action_id = event.get("action_id", "")
            saferun[action_id] = {**saferun.get(action_id, {"id": action_id}), **event}
        elif event_type == "web_task_started":
            task_id = str(event.get("task_id") or "")
            if task_id:
                web_tasks[task_id] = {
                    **web_tasks.get(task_id, {"task_id": task_id}),
                    "task_id": task_id,
                    "service": str(event.get("service") or ""),
                    "task_type": str(event.get("task_type") or ""),
                    "agent": str(event.get("agent") or ""),
                    "goal": str(event.get("goal") or ""),
                    "status": "running",
                }
        elif event_type == "web_task_state":
            task_id = str(event.get("task_id") or "")
            if task_id:
                web_tasks[task_id] = {
                    **web_tasks.get(task_id, {"task_id": task_id}),
                    "task_id": task_id,
                    "service": str(event.get("service") or web_tasks.get(task_id, {}).get("service") or ""),
                    "task_type": str(event.get("task_type") or web_tasks.get(task_id, {}).get("task_type") or ""),
                    "agent": str(event.get("agent") or web_tasks.get(task_id, {}).get("agent") or ""),
                    "status": web_tasks.get(task_id, {}).get("status") or "running",
                    "state": str(event.get("state") or ""),
                    "note": str(event.get("note") or ""),
                    "url": str(event.get("url") or ""),
                }
        elif event_type == "web_task_needs_user":
            task_id = str(event.get("task_id") or "")
            result = event.get("result") or {}
            blocker = event.get("blocker") or result.get("blocker") or {}
            if task_id:
                web_tasks[task_id] = {
                    **web_tasks.get(task_id, {"task_id": task_id}),
                    "task_id": task_id,
                    "service": str(event.get("service") or web_tasks.get(task_id, {}).get("service") or ""),
                    "task_type": str(event.get("task_type") or web_tasks.get(task_id, {}).get("task_type") or ""),
                    "agent": str(event.get("agent") or web_tasks.get(task_id, {}).get("agent") or ""),
                    "status": "needs_user",
                    "state": "needs_user",
                    "resume_token": str(result.get("resume_token") or task_id),
                    "blocker": blocker,
                    "evidence": result.get("evidence") or {},
                    "artifacts": result.get("artifacts") or {},
                }
        elif event_type == "web_task_resumed":
            task_id = str(event.get("task_id") or "")
            if task_id:
                web_tasks[task_id] = {
                    **web_tasks.get(task_id, {"task_id": task_id}),
                    "task_id": task_id,
                    "service": str(event.get("service") or web_tasks.get(task_id, {}).get("service") or ""),
                    "task_type": str(event.get("task_type") or web_tasks.get(task_id, {}).get("task_type") or ""),
                    "agent": str(event.get("agent") or web_tasks.get(task_id, {}).get("agent") or ""),
                    "status": "running",
                }
        elif event_type == "web_task_completed":
            task_id = str(event.get("task_id") or "")
            result = event.get("result") or {}
            if task_id:
                web_tasks[task_id] = {
                    **web_tasks.get(task_id, {"task_id": task_id}),
                    "task_id": task_id,
                    "service": str(event.get("service") or web_tasks.get(task_id, {}).get("service") or ""),
                    "task_type": str(event.get("task_type") or web_tasks.get(task_id, {}).get("task_type") or ""),
                    "agent": str(event.get("agent") or web_tasks.get(task_id, {}).get("agent") or ""),
                    "status": "completed",
                    "resume_token": str(result.get("resume_token") or task_id),
                    "evidence": result.get("evidence") or {},
                    "artifacts": result.get("artifacts") or {},
                }
        elif event_type == "web_task_failed":
            task_id = str(event.get("task_id") or "")
            result = event.get("result") or {}
            blocker = result.get("blocker") or {}
            if task_id:
                web_tasks[task_id] = {
                    **web_tasks.get(task_id, {"task_id": task_id}),
                    "task_id": task_id,
                    "service": str(event.get("service") or web_tasks.get(task_id, {}).get("service") or ""),
                    "task_type": str(event.get("task_type") or web_tasks.get(task_id, {}).get("task_type") or ""),
                    "agent": str(event.get("agent") or web_tasks.get(task_id, {}).get("agent") or ""),
                    "status": str(result.get("status") or "failed"),
                    "resume_token": str(result.get("resume_token") or task_id),
                    "blocker": blocker,
                    "evidence": result.get("evidence") or {},
                    "artifacts": result.get("artifacts") or {},
                }
        elif event_type == "agent_start" and event.get("agent"):
            agent_status[str(event.get("agent"))] = "running"
            final_status = "running"
        elif event_type == "agent_done" and event.get("agent"):
            agent_status[str(event.get("agent"))] = "done"
        elif event_type == "agent_error" and event.get("agent"):
            agent_status[str(event.get("agent"))] = "error"
        elif event_type == "agent_question" and event.get("request_id"):
            pending_agent_question = {
                "request_id": str(event.get("request_id") or ""),
                "title": str(event.get("title") or ""),
                "question": str(event.get("question") or ""),
                "options": list(event.get("options") or []),
                "hint": str(event.get("hint") or ""),
                "context": str(event.get("context") or ""),
                "recommendation": str(event.get("recommendation") or ""),
                "severity": str(event.get("severity") or "warning"),
                "option_details": dict(event.get("option_details") or {}),
            }
        elif event_type in {"agent_input_received", "research_direction_decision"}:
            pending_agent_question = None
        elif event_type == "goal_done":
            final_status = "done"
        elif event_type == "goal_error":
            final_status = "error"

    if final_status == "running":
        ledger = _run_ledger_snapshot(session_id)
        if isinstance(ledger, dict) and ledger.get("status") == "stalled":
            final_status = "stalled"
        elif (
            isinstance(ledger, dict)
            and ledger.get("status") == "running"
            and int(ledger.get("event_count") or 0) > len(events)
            and int(ledger.get("running_agents") or 0) > 0
        ):
            final_status = "stalled"
        elif agent_status and "running" not in set(agent_status.values()):
            last_type = event_dicts[-1].get("type") if event_dicts else ""
            if last_type in {"agent_done", "agent_error", "stack_artifact_verification", "stack_lane_status"}:
                final_status = "stalled"

    for request in approval_workflow.get("requests", []) if isinstance(approval_workflow, dict) else []:
        item = _approval_request_state(request)
        key = item.get("key", "")
        approvals[key] = {**approvals.get(key, {}), **item}

    state = {
        "session_id": session_id,
        "founder_id": founder_id,
        "status": final_status,
        "session_meta": {
            "status": session_meta.get("status"),
            "goal": session_meta.get("goal"),
            "company_id": session_meta.get("company_id"),
            "kind": session_meta.get("kind"),
            "created_at": session_meta.get("created_at"),
            "completed_at": session_meta.get("completed_at"),
            "needs_review": bool(session_meta.get("needs_review")),
            "review_reason": session_meta.get("review_reason") or "",
            "deploy_url": session_meta.get("deploy_url") or session_meta.get("preview_url") or "",
        },
        "needs_review": bool(session_meta.get("needs_review")),
        "review_reason": session_meta.get("review_reason") or "",
        "company_goal": company_goal,
        "event_count": len(events),
        "last_event_id": events[-1][0] if events else 0,
        "stack": stack,
        "operating_plan": operating_plan,
        "manifest": manifest,
        "execution_contract": execution_contract,
        "execution_blueprint": execution_blueprint,
        "agents": agents,
        "previewUrl": preview_url,
        "deployment_checks": deployment_checks[-20:],
        "lane_status": list(lane_status.values()),
        "company_genome": genome,
        "digest": build_session_digest(session_id, events) if events else None,
        "workboard": build_session_workboard(session_id, events) if events else None,
        "approval_workflow": approval_workflow,
        "approvals": list(approvals.values()),
        "web_tasks": list(web_tasks.values()),
        "artifacts": list(artifacts.values()),
        "artifact_verifications": list(artifact_verifications.values()),
        "pending_agent_question": pending_agent_question,
        "outcomes": outcomes[-50:],
        "saferun_actions": list(saferun.values())[-50:],
        "run_ledger": _run_ledger_snapshot(session_id),
    }
    try:
        from backend.run_completion_audit import build_run_completion_audit
        state["completion_audit"] = build_run_completion_audit(session_id, state)
        if state["status"] == "done" and state["completion_audit"].get("ok") is False:
            state["status"] = "stalled"
    except Exception as exc:
        state["completion_audit"] = {"ok": False, "status": "error", "summary": str(exc), "checks": [], "failed": []}
    return state


def _agent_snapshot(agents: dict[str, dict[str, Any]], agent: str) -> dict[str, Any]:
    return agents.setdefault(agent, {
        "task_id": "",
        "agent": agent,
        "instruction": "",
        "status": "waiting",
        "currentAction": None,
        "currentTool": None,
        "lastToolAt": None,
        "reasoning": None,
        "model": None,
        "tks": None,
        "result": None,
        "log": [],
        "visitedUrls": [],
        "commits": [],
    })


def _append_agent_log(agent_state: dict[str, Any], log_type: str, text: str, ts: float | None = None) -> None:
    if not text:
        return
    logs = list(agent_state.get("log") or [])
    logs.append({"ts": int((ts or 0) * 1000) if ts else 0, "type": log_type, "text": text[:500]})
    agent_state["log"] = logs[-80:]


def _compact_value(value: Any) -> Any:
    if isinstance(value, str):
        if len(value) > _LARGE_STRING_LIMIT:
            return f"[large-string:{len(value)}chars]"
        return value
    if isinstance(value, list):
        return [_compact_value(item) for item in value[:100]]
    if isinstance(value, dict):
        compact: dict[str, Any] = {}
        for key, item in value.items():
            if isinstance(item, str) and len(item) > 10_000 and key.lower() in {"base64", "image", "image_base64"}:
                compact[key] = f"[base64:{len(item)}chars]"
            else:
                compact[key] = _compact_value(item)
        return compact
    return value


def _compact_result(result: Any) -> Any:
    if not isinstance(result, dict):
        return _compact_value(result)
    return _compact_value(result)


def _merge_live_tool_result(agent_state: dict[str, Any], tool: str | None, result: dict[str, Any]) -> None:
    compact = _compact_result(result)
    live_result = dict(agent_state.get("result") or {}) if isinstance(agent_state.get("result"), dict) else {}

    if tool == "generate_color_palette":
        live_result["color_palette"] = compact
    elif tool == "generate_design_spec":
        live_result["design_spec"] = compact
    elif tool == "generate_wireframe":
        wireframes = list(live_result.get("wireframes") or [])
        wireframes.append(compact)
        live_result["wireframes"] = wireframes[-12:]
    elif tool == "generate_logo":
        slot = "logo_wordmark" if result.get("style") == "wordmark" else "logo_icon"
        live_result[slot] = compact
    elif tool in {"generate_brand_board", "generate_brand_image", "generate_ad_image", "composite_logo_on_image"}:
        brand_images = list(live_result.get("brand_images") or [])
        brand_images.append(compact)
        live_result["brand_images"] = brand_images[-12:]
    elif tool == "generate_logo_brief":
        live_result["logo_brief"] = compact
    elif tool == "run_research_pipeline":
        if result.get("sources") is not None:
            live_result["research_sources"] = _compact_value(result.get("sources"))
        if result.get("combined_formatted") is not None:
            live_result["research_summary"] = _compact_value(result.get("combined_formatted"))
        if result.get("deep_research_result") is not None:
            deep = result.get("deep_research_result") or {}
            live_result["deep_research_used"] = bool(result.get("deep_research_used"))
            live_result["deep_research_queries"] = _compact_value(result.get("deep_research_queries") or [])
            if isinstance(deep, dict):
                if deep.get("sources") is not None:
                    live_result["deep_research_sources"] = _compact_value(deep.get("sources"))
                if deep.get("combined_formatted") is not None:
                    live_result["deep_research_summary"] = _compact_value(deep.get("combined_formatted"))
                if deep.get("results_by_query") is not None:
                    live_result["deep_research_results"] = _compact_value(deep.get("results_by_query"))
    elif tool in {"deep_research", "sonar_research"}:
        live_result["deep_research_used"] = True
        if result.get("sources") is not None:
            live_result["deep_research_sources"] = _compact_value(result.get("sources"))
        if result.get("combined_formatted") is not None:
            live_result["deep_research_summary"] = _compact_value(result.get("combined_formatted"))
        if result.get("results_by_query") is not None:
            live_result["deep_research_results"] = _compact_value(result.get("results_by_query"))
    elif tool == "generate_pdf" and result.get("path"):
        pdfs = list(live_result.get("pdfs") or [])
        pdfs.append(str(result.get("path")))
        live_result["pdfs"] = pdfs[-12:]
    elif tool == "format_legal_document":
        documents = list(live_result.get("documents") or [])
        documents.append(compact)
        live_result["documents"] = documents[-12:]

    if live_result:
        agent_state["result"] = live_result


def _update_agent_snapshot(agents: dict[str, dict[str, Any]], event: dict[str, Any]) -> None:
    event_type = event.get("type")
    agent = event.get("agent")
    if not agent and event_type == "plan_done":
        for task in event.get("tasks") or []:
            task_agent = str(task.get("agent") or "")
            if not task_agent:
                continue
            state = _agent_snapshot(agents, task_agent)
            state["task_id"] = task.get("id") or state.get("task_id") or ""
            state["instruction"] = task.get("instruction") or state.get("instruction") or ""
        return
    if not agent:
        return
    state = _agent_snapshot(agents, str(agent))
    ts = event.get("ts_unix")
    if event_type == "agent_start":
        state["status"] = "running"
        state["task_id"] = event.get("task_id") or state.get("task_id") or ""
        state["instruction"] = event.get("instruction") or state.get("instruction") or ""
        _append_agent_log(state, "info", "Started", ts)
    elif event_type == "agent_action":
        state["currentAction"] = event.get("action")
        state["currentTool"] = event.get("tool")
        state["reasoning"] = event.get("reasoning")
        text = str(event.get("tool") or event.get("action") or "Action")
        args = event.get("args")
        if isinstance(args, dict):
            detail = args.get("query") or args.get("url") or args.get("title") or args.get("company")
            if detail:
                text = f"{text}: {str(detail)[:120]}"
        _append_agent_log(state, "action", text, ts)
    elif event_type == "agent_action_result":
        result = event.get("result")
        ok = not (isinstance(result, dict) and result.get("error"))
        tool = event.get("tool") or "tool"
        text = f"{'Done' if ok else 'Error'}: {tool}"
        if isinstance(result, dict) and result.get("error"):
            text = f"{tool}: {result.get('error')}"
        _append_agent_log(state, "result" if ok else "error", text, ts)
        if ok and isinstance(result, dict):
            _merge_live_tool_result(state, event.get("tool"), result)
            if event.get("tool") in {"generate_ad_image", "generate_brand_image", "generate_brand_board"}:
                images = list(state.get("adImages") or [])
                images.append(_compact_result(result))
                state["adImages"] = images[-12:]
            if isinstance(result.get("files_preview"), list):
                state["filesPreview"] = result["files_preview"]
            if isinstance(result.get("files_in_repo"), int):
                state["filesCount"] = result["files_in_repo"]
    elif event_type == "model_stats":
        state["model"] = event.get("model") or state.get("model")
        state["tks"] = event.get("tks")
    elif event_type == "agent_done":
        result = _compact_result(event.get("result") or {})
        state["status"] = "done"
        state["currentAction"] = None
        state["currentTool"] = None
        # Merge accumulated tool results (pdfs, research_summary, etc.) into the
        # final agent_done result so they aren't lost. agent_done values take precedence.
        accumulated = state.get("result") if isinstance(state.get("result"), dict) else {}
        final_result = result if isinstance(result, dict) else {"output": result}
        for k, v in accumulated.items():
            if k not in final_result or not final_result[k]:
                final_result[k] = v
        state["result"] = final_result
        if isinstance(state["result"], dict):
            preview_url = (
                state["result"].get("deploy_url")
                or state["result"].get("url")
                or state["result"].get("deployment_url")
                or state["result"].get("project_url")
                or state["result"].get("github_url")
            )
            if preview_url:
                state["previewUrl"] = preview_url
            if isinstance(state["result"].get("files_preview"), list):
                state["filesPreview"] = state["result"]["files_preview"]
            if isinstance(state["result"].get("files_in_repo"), int):
                state["filesCount"] = state["result"]["files_in_repo"]
        _append_agent_log(state, "result", "Complete", ts)
    elif event_type == "agent_error":
        state["status"] = "error"
        state["currentAction"] = None
        state["currentTool"] = None
        state["result"] = state.get("result") or {"error": event.get("error") or "Agent error"}
        _append_agent_log(state, "error", str(event.get("error") or "Agent error"), ts)
    elif event_type == "mirror_verdict":
        state["mirrorVerdict"] = event.get("verdict")
        state["mirrorCritique"] = event.get("critique")


def save_session_state(session_id: str, events: list[tuple[int, dict]]) -> dict[str, Any]:
    state = build_session_state(session_id, events)
    _state_path(session_id).write_text(json.dumps(state, indent=2, sort_keys=True))
    try:
        from backend.storage_adapter import mirror_document
        mirror_document("workflow_states", session_id, state)
    except Exception:
        pass
    return state


def load_session_state(session_id: str) -> dict[str, Any] | None:
    path = _state_path(session_id)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    try:
        from backend.storage_adapter import load_document
        return load_document("workflow_states", session_id)
    except Exception:
        return None


def _run_ledger_snapshot(session_id: str) -> dict[str, Any] | None:
    try:
        from backend.run_ledger import get_run
        return get_run(session_id)
    except Exception:
        return None


def _session_meta_snapshot(session_id: str) -> dict[str, Any]:
    try:
        from backend.core.session_store import get_session_meta
        return get_session_meta(session_id) or {}
    except Exception:
        return {}


def _approval_workflow_snapshot(session_id: str) -> dict[str, Any]:
    try:
        from backend.approval_workflows import get_approval_workflow
        return get_approval_workflow(session_id)
    except Exception:
        return {"session_id": session_id, "requests": []}


def _approval_request_state(request: dict[str, Any]) -> dict[str, Any]:
    gate_key = str(request.get("gate_key") or request.get("key") or request.get("id") or "")
    required_before = request.get("required_before") or request.get("tool") or request.get("action_id") or "sensitive action"
    inferred_phase = ""
    inferred_next_phase = ""
    inferred_is_phase_gate = bool(request.get("is_phase_gate"))
    if gate_key.startswith("phase_gate_"):
        inferred_is_phase_gate = True
        inferred_phase = gate_key.removeprefix("phase_gate_")
        _phase_order = ["diagnose", "design", "deploy", "govern", "operate", "complete"]
        if inferred_phase in _phase_order:
            _idx = _phase_order.index(inferred_phase)
            if _idx + 1 < len(_phase_order):
                inferred_next_phase = _phase_order[_idx + 1]
    return {
        "key": gate_key,
        "id": request.get("id") or gate_key,
        "gate_key": gate_key,
        "title": request.get("title") or gate_key.replace("_", " ").title(),
        "trigger": request.get("trigger") or request.get("tool") or request.get("action_id") or "",
        "required_before": required_before,
        "reason": request.get("reason") or f"Approval required before {required_before}.",
        "status": request.get("status") or "pending",
        "triggered_by": request.get("action_id") or None,
        "required_role": request.get("required_role") or "owner",
        "risk_level": request.get("risk_level") or "medium",
        "note": request.get("note") or "",
        "decided_by": request.get("decided_by"),
        "decided_at": request.get("decided_at"),
        "history": request.get("history") or [],
        "is_phase_gate": inferred_is_phase_gate,
        "phase": request.get("phase") or inferred_phase,
        "next_phase": request.get("next_phase") or inferred_next_phase,
        "artifacts": request.get("artifacts") or [],
    }
