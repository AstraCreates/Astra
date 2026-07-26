"""Durable background execution for policy-approved Company OS missions."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import html
import logging
import re
from datetime import datetime, timezone
from typing import Any, Mapping

from backend.company_os import (
    append_message,
    company_recovery_lock,
    create_artifact,
    create_task,
    get_company_os,
    list_company_os,
    reconcile_initiatives,
    update_mission,
    update_task,
    update_task_attempt,
    update_artifact,
    update_squad,
)
from backend.company_os_dispatch import execute_task
from backend.company_os_mcp import invoke as invoke_mcp
from backend.tools.research_evidence import validate_deep_research

logger = logging.getLogger(__name__)
_ACTIVE_MISSIONS: dict[str, "asyncio.Task[None] | asyncio.Future[None]"] = {}
_MAX_ARTIFACT_CONTENT = 80_000
# Captured once at FastAPI startup (see backend/main.py) so launch_mission
# can still schedule work when called from a worker thread, e.g. approval
# side-effects and the startup resync both run via asyncio.to_thread(...).
_main_loop: asyncio.AbstractEventLoop | None = None


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _main_loop
    _main_loop = loop


def launch_mission(company_id: str, mission_id: str) -> bool:
    """Schedule one mission once per process; durable attempts prevent replay duplicates."""
    key = f"{company_id}:{mission_id}"
    active = _ACTIVE_MISSIONS.get(key)
    if active and not active.done():
        return False
    coro = run_mission(company_id, mission_id)
    try:
        job: "asyncio.Task[None] | asyncio.Future[None]" = asyncio.create_task(coro, name=f"company-os:{key}")
    except RuntimeError:
        # No event loop running in THIS thread -- we're inside
        # asyncio.to_thread (approval side-effects, startup resync). Schedule
        # onto the loop captured at startup instead of losing the launch;
        # asyncio.Task and concurrent.futures.Future both support
        # .done()/.add_done_callback(), so the rest of this function doesn't
        # need to know which one it got.
        if _main_loop is None:
            raise
        job = asyncio.run_coroutine_threadsafe(coro, _main_loop)
    _ACTIVE_MISSIONS[key] = job
    job.add_done_callback(lambda _: _ACTIVE_MISSIONS.pop(key, None))
    return True


async def run_mission(company_id: str, mission_id: str) -> None:
    """Execute a mission's durable task graph in bounded dependency-ready rounds.

    Every call here that touches Company OS state (get_company_os,
    append_message, update_mission/_squad, reconcile_initiatives, _meeting)
    parses and checksums the FULL snapshot on every invocation (confirmed via
    live profiling: a busy company's snapshot was 11MB) -- previously called
    directly, unwrapped, this ran on the same asyncio event loop thread
    serving every other request that worker process handles. One mission's
    bookkeeping call could freeze that worker's ENTIRE event loop for the
    duration of a full snapshot parse, stalling unrelated GET /os polls and
    other missions on the same worker along with it. asyncio.to_thread here
    matches the pattern _run_task already used correctly for execute_task
    below, and the pattern the GET /os route itself uses.
    """
    company = await asyncio.to_thread(get_company_os, company_id)
    if not company:
        return
    mission = _find(company.get("missions", []), "mission_id", mission_id)
    if not mission:
        return
    squad = _find(company.get("squads", []), "squad_id", mission["squad_id"])
    dependencies = _mission_dependencies(mission)
    completed = {item.get("mission_id") for item in company.get("missions", []) if item.get("state") == "done"}
    if not dependencies.issubset(completed):
        dependency_missions = [item for item in company.get("missions", []) if item.get("mission_id") in dependencies]
        blocked_dependencies = [
            item for item in dependency_missions
            if item.get("state") in {"blocked", "review", "waiting", "archived"}
        ]
        if blocked_dependencies:
            names = ", ".join(str(item.get("name") or item.get("mission_id")) for item in blocked_dependencies[:3])
            reason = f"Waiting on upstream mission review before this work can continue: {names}"
            await asyncio.to_thread(update_mission, company_id, mission_id, state="review", blocked_reason=reason)
            if squad:
                await asyncio.to_thread(update_squad, company_id, squad["squad_id"], state="review", lifecycle="review")
            await asyncio.to_thread(append_message, company_id, f"{mission['name']} is blocked until upstream work is resolved: {names}", author="copilot", scope="initiative", scope_id=mission["initiative_id"], kind="status")
            await asyncio.to_thread(reconcile_initiatives, company_id)
        # This is a dependency wait, not a failure or an approval. The
        # prerequisite's completion resumes the mission automatically.
        return
    if squad:
        await asyncio.to_thread(update_squad, company_id, squad["squad_id"], state="working", lifecycle="working")
    await asyncio.to_thread(update_mission, company_id, mission_id, state="working")
    await asyncio.to_thread(append_message, company_id, f"{mission['name']}: the {mission.get('department', 'operations').replace('_', ' ').title()} Lead started the squad work.", author="copilot", scope="initiative", scope_id=mission["initiative_id"], kind="status")

    await asyncio.to_thread(_meeting, company_id, mission, phase="kickoff")
    blocked: list[Exception] = []
    waiting = False
    while True:
        tasks = await asyncio.to_thread(_mission_tasks, company_id, mission_id)
        ready = _ready_tasks(tasks)
        if not ready:
            break
        # Old missions have no graph metadata. Keep their historical serial
        # order so rollout does not accidentally synthesize before evidence.
        if not _has_task_graph(tasks):
            ready = ready[:1]
        limit = max(1, min(int((squad or {}).get("max_parallel_tasks") or 3), len(ready)))
        for offset in range(0, len(ready), limit):
            batch = ready[offset:offset + limit]
            results = await asyncio.gather(
                *[_run_task(company_id, mission, task) for task in batch], return_exceptions=True,
            )
            for task, result in zip(batch, results):
                if isinstance(result, Exception):
                    blocked.append(result)
                    await asyncio.to_thread(_meeting, company_id, mission, phase="checkpoint", task=task, blockers=[str(result)])
                    continue
                if result.get("status") == "awaiting_approval":
                    waiting = True
        if blocked or waiting:
            break

    if blocked:
        detail = "; ".join(str(item) for item in blocked[:3])
        await asyncio.to_thread(update_mission, company_id, mission_id, state="review", blocked_reason=detail)
        if squad:
            await asyncio.to_thread(update_squad, company_id, squad["squad_id"], state="review", lifecycle="review")
        await asyncio.to_thread(_meeting, company_id, mission, phase="closeout", blockers=[detail])
        await asyncio.to_thread(append_message, company_id, f"{mission['name']} needs review before continuing: {detail}", author="copilot", scope="initiative", scope_id=mission["initiative_id"], kind="status")
        await asyncio.to_thread(reconcile_initiatives, company_id)
        return
    if waiting:
        await asyncio.to_thread(update_mission, company_id, mission_id, state="waiting")
        if squad:
            await asyncio.to_thread(update_squad, company_id, squad["squad_id"], state="waiting", lifecycle="review")
        await asyncio.to_thread(_meeting, company_id, mission, phase="checkpoint", blockers=["Approval required"])
        await asyncio.to_thread(append_message, company_id, f"{mission['name']} is waiting for approval before the next action.", author="copilot", scope="initiative", scope_id=mission["initiative_id"], kind="status")
        await asyncio.to_thread(reconcile_initiatives, company_id)
        return

    final_state: str | None = None
    remaining = await asyncio.to_thread(_mission_tasks, company_id, mission_id)
    if _all_terminal(remaining):
        await asyncio.to_thread(_meeting, company_id, mission, phase="review")
        final_state = "done" if all(task.get("state") == "done" for task in remaining) else "waiting"
        await asyncio.to_thread(update_mission, company_id, mission_id, state=final_state)
        if squad:
            await asyncio.to_thread(update_squad, company_id, squad["squad_id"], state=final_state, lifecycle="done" if final_state == "done" else "review")
        if final_state == "done":
            reply = await asyncio.to_thread(_completion_reply, company_id, mission)
        else:
            reply = f"{mission['name']} is waiting on your approval before the last step. Check Approvals in the sidebar."
        await asyncio.to_thread(append_message, company_id, reply, author="copilot", scope="initiative", scope_id=mission["initiative_id"], kind="chat")
        await asyncio.to_thread(_meeting, company_id, mission, phase="closeout")
    await asyncio.to_thread(reconcile_initiatives, company_id)
    if final_state == "done":
        await asyncio.to_thread(_resume_ready_dependents, company_id, mission_id)
        if str(mission.get("department") or "") == "research":
            await asyncio.to_thread(_queue_research_handoff_revisions, company_id, mission_id)


async def _run_task(company_id: str, mission: Mapping[str, Any], task: Mapping[str, Any]) -> dict[str, Any]:
    """Execute one role-owned task and leave a concise founder-visible status."""
    await asyncio.to_thread(_meeting, company_id, mission, phase="task_start", task=task)
    await asyncio.to_thread(append_message, company_id, f"Working on: {task['name']}.", author="copilot", scope="task", scope_id=task["task_id"], kind="status")
    try:
        return await asyncio.to_thread(
            execute_task, company_id, task, lambda current: _execute_internal_work(company_id, mission, current)
        )
    except Exception as exc:
        logger.exception("Company OS task failed: company=%s task=%s", company_id, task.get("task_id"))
        raise exc


def _mission_dependencies(mission: Mapping[str, Any]) -> set[str]:
    """Every mission this one must wait for before its own tasks can start.

    handoff_for records which mission a handoff came FROM (see
    company_os_dispatch.py) but was previously provenance-only -- nothing
    actually gated a handoff mission's task graph on its origin mission
    reaching "done". Its first task's depends_on_task_ids was empty, so a
    handoff mission (e.g. "build a website about X") ran its squad fully in
    parallel with the origin mission (e.g. "research X"), reaching a real
    publish approval using placeholder content before the research it was
    supposed to be built on ever produced a finding. Folding handoff_for in
    here reuses the exact depends_on_mission_ids gate/resume mechanism
    below unchanged, rather than inventing a second one.
    """
    dependencies = set(mission.get("depends_on_mission_ids") or [])
    handoff_for = mission.get("handoff_for")
    if handoff_for:
        dependencies.add(str(handoff_for))
    return dependencies


def _has_task_graph(tasks: list[Mapping[str, Any]]) -> bool:
    return any(task.get("role_id") or task.get("depends_on_task_ids") or task.get("parallel_group") for task in tasks)


def _ready_tasks(tasks: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    complete = {str(task.get("task_id")) for task in tasks if task.get("state") == "done"}
    executable = {"pending", "scheduled", "ready", "planned"}
    ready = [task for task in tasks if task.get("state") in executable and set(task.get("depends_on_task_ids") or []).issubset(complete)]
    return [dict(task) for task in ready]


def _all_terminal(tasks: list[Mapping[str, Any]]) -> bool:
    return bool(tasks) and all(task.get("state") in {"done", "awaiting_approval", "blocked"} for task in tasks)


def _meeting(company_id: str, mission: Mapping[str, Any], *, phase: str, task: Mapping[str, Any] | None = None,
             blockers: list[str] | None = None) -> None:
    """Meetings are optional during the staged rollout; execution never blocks on one."""
    try:
        from backend.company_os_meetings import hold_meeting
        hold_meeting(company_id, mission, phase=phase, task=task, blockers=blockers or [])
    except Exception:
        logger.debug("Company OS meeting fallback: company=%s mission=%s phase=%s", company_id, mission.get("mission_id"), phase, exc_info=True)


async def recover_pending_missions() -> int:
    """Resume policy-approved work after a process restart from local Company OS state.

    A process can die after persisting ``working`` but before its in-memory
    asyncio task finishes. Those records used to remain working forever,
    because recovery only considered pending tasks. Reset only records older
    than the bounded stale threshold so a genuinely active deep-research pass
    is not duplicated.
    """
    from backend.config import settings

    def is_stale(task: Mapping[str, Any]) -> bool:
        if task.get("state") != "working":
            return False
        timestamp = str(task.get("updated_at") or task.get("started_at") or "")
        try:
            updated = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            return True
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - updated).total_seconds() >= max(60, int(settings.company_os_stale_task_seconds))

    recovered = 0
    for company in await asyncio.to_thread(list_company_os):
        for mission in company.get("missions", []):
            squad = _find(company.get("squads", []), "squad_id", mission.get("squad_id"))
            initiative = _find(company.get("initiatives", []), "initiative_id", mission.get("initiative_id"))
            if (mission.get("state") in {"archived", "cancelled"}
                    or (squad and squad.get("state") in {"archived", "cancelled"})
                    or (initiative and initiative.get("state") in {"archived", "cancelled"})):
                continue
            mission_tasks = [task for task in company.get("tasks", []) if task.get("mission_id") == mission.get("mission_id")]
            approved_waiting = mission.get("state") == "waiting" and any(
                task.get("state") in {"pending", "scheduled"} and task.get("approval_decision") == "approved"
                for task in mission_tasks
            )
            if mission.get("state") not in {"active", "working", "review"} and not approved_waiting:
                continue
            # A task sitting "pending" behind another task that is genuinely
            # still working -- not stale -- is completely normal (every
            # multi-task mission looks like this while its current step
            # runs); it is not evidence of an interrupted process. Without
            # this guard, "pending_tasks" alone fired a redundant run_mission
            # for a mission that was simply still in progress, which then
            # skipped the (not-yet-stale) working task and ran the NEXT task
            # for real with no evidence from the one still actually running.
            if any(task.get("state") == "working" and not is_stale(task) for task in mission_tasks):
                continue
            stale_tasks = [task for task in mission_tasks if is_stale(task)]
            pending_tasks = [task for task in mission_tasks if task.get("state") in {"pending", "scheduled"}]
            if stale_tasks or pending_tasks:
                # Startup runs once per web worker. Re-read under a shared
                # company lock so only one worker can claim and execute an
                # orphaned or previously re-queued task; the other workers
                # observe the fresh state.
                with company_recovery_lock(company["company_id"]):
                    current = get_company_os(company["company_id"]) or {}
                    current_mission = _find(current.get("missions", []), "mission_id", mission["mission_id"])
                    current_tasks = [task for task in current.get("tasks", []) if task.get("mission_id") == mission["mission_id"]]
                    current_approved_waiting = current_mission and current_mission.get("state") == "waiting" and any(
                        task.get("state") in {"pending", "scheduled"} and task.get("approval_decision") == "approved"
                        for task in current_tasks
                    )
                    if any(task.get("state") == "working" and not is_stale(task) for task in current_tasks):
                        continue
                    current_stale = [task for task in current_tasks if is_stale(task)]
                    current_pending = [task for task in current_tasks if task.get("state") in {"pending", "scheduled"}]
                    if not current_mission or (not current_stale and not current_pending) or (
                        current_mission.get("state") == "waiting" and not current_approved_waiting
                    ):
                        continue
                    for task in [*current_stale, *current_pending]:
                        for attempt in current.get("task_attempts", []):
                            if attempt.get("task_id") != task.get("task_id") or attempt.get("state") != "running":
                                continue
                            update_task_attempt(company["company_id"], attempt["attempt_id"], state="failed",
                                                error="orphaned_after_process_restart", transient=True,
                                                finished_at=datetime.now(timezone.utc).isoformat())
                    for task in current_stale:
                        update_task(company["company_id"], task["task_id"], state="pending", blocked_reason=None,
                                    recovery_reason="stale_working_task_after_process_restart")
                        append_message(company["company_id"], f"Recovered stalled work: {task.get('name', 'task')} is being retried.",
                                       author="copilot", scope="task", scope_id=task["task_id"], kind="status")
                    if current_approved_waiting:
                        update_mission(company["company_id"], mission["mission_id"], state="active", blocked_reason=None)
                    # Await instead of using fire-and-forget startup work so
                    # the claim and first attempt cannot be lost.
                    await run_mission(company["company_id"], mission["mission_id"])
                    recovered += 1
    return recovered


def _mission_tasks(company_id: str, mission_id: str) -> list[dict[str, Any]]:
    company = get_company_os(company_id) or {}
    return [task for task in company.get("tasks", []) if task.get("mission_id") == mission_id]


def _queue_research_handoff_revisions(company_id: str, research_mission_id: str) -> None:
    """Repair legacy mixed missions that built before their research handoff.

    New dispatches gate Product Delivery behind Research. Older dispatches could
    do the inverse, so a completed research handoff must turn the existing site
    into an incremental revision rather than leaving the provisional build as
    the final output. The revision gets its own review and approval gate.
    """
    company = get_company_os(company_id) or {}
    research = _find(company.get("missions", []), "mission_id", research_mission_id)
    if not research:
        return
    for product in company.get("missions", []):
        if product.get("department") != "product_technical" or product.get("state") in {"archived", "cancelled"}:
            continue
        # In the old ordering, the research mission points back to the already
        # completed Product Delivery mission through handoff_for.
        if str(research.get("handoff_for") or "") != str(product.get("mission_id") or ""):
            continue
        tasks = [task for task in company.get("tasks", []) if task.get("mission_id") == product.get("mission_id")]
        if any(str(task.get("task_key") or "").startswith("research_revision") for task in tasks):
            continue
        build = next((task for task in tasks if task.get("operation") in {"local_preview", "local_build"}), None)
        if not build:
            continue
        review_role = next((task.get("role_id") for task in tasks if task.get("task_key") == "product-review"), build.get("role_id"))
        publish_role = next((task.get("role_id") for task in tasks if task.get("task_key") == "product-publish"), review_role)
        base = {"inputs": ["validated research artifact", "existing website workspace"],
                "expected_outputs": ["updated website preview"], "acceptance_criteria": ["research findings are visibly represented", "existing build still passes"],
                "parallel_group": "research_revision", "handoffs": []}
        revision = create_task(company_id, str(product.get("initiative_id")), str(product.get("squad_id")),
                               f"Revise the website with the completed research for {product.get('name', 'this initiative')}",
                               state="pending", role_id=build.get("role_id"), role_key="frontend_engineer", department="product_technical",
                               task_key=f"research_revision_build_{research_mission_id}", operation="local_preview", mcp_tool=None,
                               deliverable="Updated local website preview", description="Apply the completed research evidence to the existing website; preserve useful work and improve the information architecture.", purpose="Revise the existing website using the completed research handoff.", **base)
        review = create_task(company_id, str(product.get("initiative_id")), str(product.get("squad_id")),
                             "Review the research-informed website revision", state="pending", role_id=review_role, department="product_technical",
                             role_key="product_lead", task_key=f"research_revision_review_{research_mission_id}", operation="internal_analysis", purpose="Validate the revised website against the research handoff.",
                             depends_on_task_ids=[revision.get("task_id")], deliverable="Approved revision decision", description="Verify the website reflects the research and remains coherent.", **{**base, "expected_outputs": ["revision review"]})
        create_task(company_id, str(product.get("initiative_id")), str(product.get("squad_id")),
                    "Publish the research-informed website revision", state="pending", role_id=publish_role, department="product_technical",
                    role_key="product_lead", task_key=f"research_revision_publish_{research_mission_id}", operation="external_deploy", mcp_tool="vercel_deploy", purpose="Make the reviewed revision available externally after approval.",
                    depends_on_task_ids=[review.get("task_id")], deliverable="Published website revision", description="Publish only after the founder approves the revised preview.", **{**base, "purpose": "Make the reviewed revision available externally after approval.", "expected_outputs": ["public website URL"], "acceptance_criteria": ["founder approval is recorded"]})
        update_mission(company_id, str(product.get("mission_id")), state="active", blocked_reason=None)
        update_squad(company_id, str(product.get("squad_id")), state="active", lifecycle="working")
        launch_mission(company_id, str(product.get("mission_id")))


def _execute_internal_work(company_id: str, mission: Mapping[str, Any], task: Mapping[str, Any]) -> dict[str, Any]:
    """Perform only internal work; policy gating happens before this executor is called."""
    company = get_company_os(company_id) or {}
    squad = _find(company.get("squads", []), "squad_id", mission.get("squad_id"))
    initiative = _find(company.get("initiatives", []), "initiative_id", mission.get("initiative_id"))
    if (mission.get("state") in {"archived", "cancelled"} or task.get("state") in {"archived", "cancelled"}
            or (squad and squad.get("state") in {"archived", "cancelled"})
            or (initiative and initiative.get("state") in {"archived", "cancelled"})):
        raise RuntimeError("Company OS work was deleted before execution; refusing to recreate artifacts.")
    if str(task.get("mcp_tool") or "") == "astra_company_research" and str(mission.get("department") or "") == "operations":
        raise RuntimeError("Research task is attached to Company Operations; retry after routing repair.")
    mission_name = str(mission.get("name") or "this research")
    if task.get("operation") == "external_deploy":
        company = get_company_os(company_id) or {}
        artifact = next((item for item in reversed(company.get("artifacts", []))
                         if item.get("task_id") and item.get("initiative_id") == mission.get("initiative_id")
                         and (str(item.get("name") or "").lower().startswith("website build")
                              or str(item.get("name") or "").lower().startswith("website preview"))
                         and item.get("state") != "archived"), None)
        if not artifact or not str(artifact.get("content") or "").strip():
            raise RuntimeError("The website preview artifact is missing; nothing was published.")
        build_metadata = artifact.get("build_metadata") or {}
        # The coding agent's server preview is already a real, reviewable build.
        # Do not send its markdown status summary to the HTML deploy endpoint.
        # If no Vercel-connected repository exists, approval promotes this
        # server-hosted preview instead of pretending a document was published.
        preview_url = artifact.get("url")
        if preview_url and (artifact.get("hosting") == "local_preview" or build_metadata.get("local_preview")):
            update_artifact(company_id, str(artifact["artifact_id"]),
                            hosting="server", hosting_status="deployed")
            return {"deployed": True, "url": preview_url, "hosting": "server",
                    "artifact_id": artifact["artifact_id"]}
        domain, _brand = _website_identity(mission_name)
        project_slug = re.sub(r"[^a-z0-9-]+", "-", domain.split(".", 1)[0].lower()).strip("-") or "astra-site"
        result = invoke_mcp(
            company_id,
            str(task.get("mcp_tool") or "vercel_deploy"),
            {"project_slug": project_slug, "html": str(artifact["content"])},
            task_id=str(task.get("task_id") or ""), mission_id=str(mission.get("mission_id") or ""), approved=True,
        )
        if not result.get("deployed") or not result.get("url"):
            raise RuntimeError(str(result.get("error") or result.get("note") or "Vercel deployment did not return a public URL."))
        update_artifact(company_id, str(artifact["artifact_id"]), url=result["url"],
                        hosting=str(result.get("hosting") or "vercel"), hosting_project=project_slug,
                        hosting_status="deployed")
        return {"deployed": True, "url": result["url"], "artifact_id": artifact["artifact_id"]}
    if mission.get("department") == "research" and task.get("operation") == "internal_analysis":
        evidence = invoke_mcp(
            company_id,
            str(task.get("mcp_tool") or "astra_company_research"),
            {"subject": _research_subject(mission_name), "focus": "market"},
            task_id=str(task.get("task_id") or ""), mission_id=str(mission.get("mission_id") or ""),
            squad_id=str(mission.get("squad_id") or ""), initiative_id=str(mission.get("initiative_id") or ""),
        )
        sources = [source for source in evidence.get("sources", []) if isinstance(source, Mapping) and source.get("url")]
        validation = evidence.get("evidence_validation") or validate_deep_research(evidence)
        if evidence.get("error") or evidence.get("research_status") != "validated" or not validation.get("ok"):
            reason = "; ".join(([str(evidence.get("error"))] if evidence.get("error") else [])
                                + (validation.get("gaps") or ["deep research evidence gate failed"]))
            raise RuntimeError(f"Deep research blocked by evidence gate: {reason}")
        evidence["sources"] = sources
        evidence["evidence_validation"] = validation
        # Raw evidence and the mid-pipeline synthesis note are working
        # material, not something a founder asked for -- every research
        # mission was dropping 3 separate documents into the Library for
        # what reads as "one request, one answer". Kept (archived, not
        # deleted) so the later steps and citations still have them, just
        # not surfaced as top-level artifacts.
        return _store_artifact(company_id, task, f"Research evidence — {_short_title(mission_name)}", evidence, source="web research", internal=True)

    if mission.get("department") == "product_technical" and _is_website_request(mission_name):
        task_key = str(task.get("task_key") or "")
        website_context = _website_generation_context(company_id, mission, task)
        if task_key == "product-frontend_engineer" or "local website preview" in str(task.get("name") or "").lower():
            sources = _initiative_evidence(company_id, mission.get("initiative_id"))
            build = _run_coding_website_agent(company_id, mission, task, website_context, sources)
            if build.get("url"):
                result = _store_artifact(company_id, task, f"Website build — {_short_title(mission_name)}", {
                    "content": build["summary"], "sources": sources, "url": build["url"],
                    "hosting": "local_preview", "hosting_status": "ready", "build_metadata": build,
                }, source="technical coding agent", internal=False)
                # Replace the mid-build dev-preview URL (if any) with the
                # final one now that the real build finished.
                update_task(company_id, str(task.get("task_id") or ""), preview_url=build["url"])
                append_message(company_id, build["summary"], author="copilot", scope="task",
                               scope_id=str(task.get("task_id") or ""), kind="chat",
                               thread_id=_thread_id_for_initiative(company_id, mission.get("initiative_id")),
                               preview_url=build["url"])
                return result
            raise RuntimeError(f"Technical coding agent failed: {build.get('error') or 'no reviewable preview was produced'}")
        if task_key == "product-architecture":
            # Planning is squad context, not a founder-facing Library artifact.
            # The preview task consumes the durable task/meeting state directly.
            return {"status": "planned", "content": _website_architecture(mission_name, website_context)}
        if task_key == "product-review" or "publication decision" in str(task.get("name") or "").lower() or "publish approval" in str(task.get("name") or "").lower():
            # specialist_task_plan always queues a Vercel publish task directly
            # after this one (company_os_dispatch.py:359-360) -- it is never a
            # separate, not-yet-requested follow-up. Claiming "no publication
            # or deployment has been requested" was flatly contradicted by the
            # very next task in the same mission, which immediately does
            # request one (real incident: the founder saw this text and, in
            # the same breath, a "waiting on your approval" status for that
            # exact publish request).
            return {"status": "reviewed", "content": "Local preview reviewed; publication remains approval-gated."}
        return {"status": "briefed", "content": _website_brief(mission_name, website_context)}

    evidence = _latest_research_artifact(company_id, mission.get("mission_id"))
    if mission.get("department") == "research" and task.get("task_key") == "research-review":
        title, content = _synthesis(mission_name, evidence)
        return _store_artifact(company_id, task, title, {"content": content, "sources": evidence.get("source_references") or evidence.get("sources", []), "evidence_ledger": evidence.get("evidence_ledger")}, source="internal analysis", internal=True)
    if mission.get("department") not in {"research", "product_technical"}:
        department = str(mission.get("department") or "unknown")
        tool = str(task.get("mcp_tool") or "")
        if not tool:
            raise RuntimeError(f"No Company OS tool contract is registered for the {department} department.")
        args = _department_tool_arguments(department, mission_name, company_id)
        result = invoke_mcp(company_id, tool, args, task_id=str(task.get("task_id") or ""),
                            mission_id=str(mission.get("mission_id") or ""),
                            squad_id=str(mission.get("squad_id") or ""),
                            initiative_id=str(mission.get("initiative_id") or ""))
        if not isinstance(result, Mapping) or result.get("error"):
            raise RuntimeError(f"{department.title()} specialist tool failed: {result.get('error') if isinstance(result, Mapping) else result}")
        content = result.get("content") or result.get("formatted") or result.get("html") or result.get("report") or result
        return _store_artifact(company_id, task, f"{department.title()} deliverable — {_short_title(mission_name)}",
                               {"content": content, "sources": result.get("sources", []) if isinstance(result, Mapping) else []},
                               source=f"{department} specialist tool")
    if task.get("name", "").lower().startswith("synthesize"):
        title, content = _synthesis(mission_name, evidence)
        return _store_artifact(company_id, task, title, {"content": content, "sources": evidence.get("source_references") or evidence.get("sources", []), "evidence_ledger": evidence.get("evidence_ledger")}, source="internal analysis", internal=True)
    title, content = _decision_brief(mission_name, evidence)
    return _store_artifact(company_id, task, title, {"content": content, "sources": evidence.get("source_references") or evidence.get("sources", []), "evidence_ledger": evidence.get("evidence_ledger")}, source="internal analysis")


def _department_tool_arguments(department: str, objective: str, company_id: str) -> dict[str, Any]:
    """Build bounded, domain-specific MCP inputs for non-research squads."""
    company = get_company_os(company_id) or {}
    founder_id = str(company.get("founder_id") or "")
    if department == "design":
        return {"product_name": _short_title(objective), "brand_name": _short_title(objective),
                "product_type": "website", "target_audience": "the audience described in the initiative",
                "brand_vibe": "distinctive and editorial", "key_screens": ["homepage", "detail view", "contact"]}
    if department == "marketing":
        return {"subject": _short_title(objective), "body_paragraphs": [f"Campaign brief: {objective}",
                "Use the initiative objective as the source of truth; do not invent proof points."],
                "cta_text": "Learn more", "cta_url": "#", "sender_name": "Astra"}
    if department == "sales":
        return {"title": f"Sales execution brief: {_short_title(objective)}", "filename": "sales-execution-brief.md",
                "sections": [{"heading": "Objective", "body": objective},
                             {"heading": "Qualification plan", "body": "Define target accounts, buying triggers, qualification questions, and next actions from the initiative context."}],
                "founder_id": founder_id, "company_name": _short_title(objective)}
    if department == "finance":
        return {"title": f"Financial planning brief: {_short_title(objective)}", "filename": "financial-planning-brief.md",
                "sections": [{"heading": "Objective", "body": objective},
                             {"heading": "Model requirements", "body": "Specify assumptions, revenue drivers, costs, scenarios, cash needs, and decision thresholds. Unknown values must remain explicit assumptions."}],
                "founder_id": founder_id, "company_name": _short_title(objective)}
    if department == "legal":
        return {"doc_type": "legal_review", "company_name": _short_title(objective),
                "content": f"Request: {objective}\n\nIdentify applicable obligations, risks, missing facts, and required approvals. This is not legal advice."}
    if department == "operations":
        return {"founder_id": founder_id}
    return {}


def _thread_id_for_initiative(company_id: str, initiative_id: object) -> str:
    """Tasks/missions carry no thread_id of their own -- only the founder's
    live conversation turns do. Without this, a background task's follow-up
    chat message (e.g. the "website build ready" summary) always falls back
    to the default thread's append_message default, so a founder working in
    any other thread would never see it land in the chat they're actually
    looking at. The copilot's own "plan" reply for this initiative (posted
    synchronously, with the real thread_id, in company_os_copilot.py) is the
    one durable record of which thread this work started in."""
    company = get_company_os(company_id) or {}
    plan_message = next((m for m in company.get("conversation", [])
                         if m.get("scope") == "initiative" and m.get("scope_id") == initiative_id and m.get("kind") == "plan"), None)
    return str((plan_message or {}).get("thread_id") or "default")


def _store_artifact(company_id: str, task: Mapping[str, Any], title: str, result: Mapping[str, Any], *, source: str, internal: bool = False) -> dict[str, Any]:
    # Research pipelines expose the human-readable evidence under
    # combined_formatted. Falling through to str(result) leaked raw tool JSON.
    content = str(result.get("content") or result.get("report") or result.get("combined_formatted") or result.get("formatted") or result)
    artifact = create_artifact(company_id, title, task_id=task["task_id"], source=source,
                               content=content[:_MAX_ARTIFACT_CONTENT], source_references=result.get("sources", []),
                               evidence_ledger=result.get("evidence_ledger"),
                               research_status=result.get("research_status"), research_metadata=result.get("research_metadata"),
                               evidence_validation=result.get("evidence_validation"),
                               deep_research_supervisor=bool(result.get("deep_research_supervisor")),
                               url=result.get("url"), hosting=result.get("hosting"),
                               hosting_status=result.get("hosting_status"), build_metadata=result.get("build_metadata"),
                               state="archived" if internal else "active")
    return {"artifact_id": artifact["artifact_id"], "source_count": len(result.get("sources", [])),
            "research_metadata": result.get("research_metadata"),
            "evidence_validation": result.get("evidence_validation"),
            "research_status": result.get("research_status")}


def _latest_research_artifact(company_id: str, mission_id: object) -> Mapping[str, Any]:
    company = get_company_os(company_id) or {}
    task_ids = {task.get("task_id") for task in company.get("tasks", []) if task.get("mission_id") == mission_id}
    artifacts = [artifact for artifact in company.get("artifacts", []) if artifact.get("task_id") in task_ids]
    return artifacts[0] if artifacts else {}


def _run_coding_website_agent(company_id: str, mission: Mapping[str, Any], task: Mapping[str, Any],
                              context: Mapping[str, Any], sources: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Use the persistent coding-agent loop for real Product Delivery builds."""
    try:
        from backend.tools.git_tools import run_mvp_loop
        company = get_company_os(company_id) or {}
        founder_id = str(company.get("founder_id") or company_id)
        objective = str(context.get("objective") or mission.get("name") or "Build the requested website")
        session_id = str(task.get("task_id") or mission.get("mission_id") or "company-os-website")
        try:
            from backend.core.session_store import register_session
            register_session(session_id, founder_id, objective, company_name=str(company.get("name") or "Company"),
                             company_id=company_id, workspace_id=company_id, kind="company_os_build", visible=False)
        except Exception:
            logger.debug("Could not register Company OS coding session", exc_info=True)
        # Keep the authenticated PTY identity on the Company OS task. The
        # Company Home workbench uses this field to expose the terminal inline.
        update_task(company_id, str(task.get("task_id") or ""),
                    terminal_session_id=session_id, build_session_id=session_id,
                    execution_profile="technical_agent", terminal_state="starting",
                    workspace_state="preparing", preview_state="starting",
                    progress_text="Preparing the shared coding terminal and local preview.")
        last_progress = {"text": ""}

        def progress(text: str, **extra: Any) -> None:
            preview_url = extra.get("preview_url")
            if text == last_progress["text"] and not preview_url:
                return
            last_progress["text"] = text
            fields: dict[str, Any] = {"terminal_session_id": session_id, "build_session_id": session_id,
                                       "progress_text": text, "activity": text,
                                       # A progress callback proves the original PTY is alive. Do not
                                       # leave the UI in its provisional "starting" state until the
                                       # whole coding pass happens to finish.
                                       "terminal_state": "live", "workspace_state": "ready",
                                       "last_progress_at": datetime.now(timezone.utc).isoformat()}
            # The live dev-mode preview (backend/tools/local_preview.py's
            # start_local_preview(..., dev=True), called from run_mvp_loop
            # before the first coding pass) reports its URL through this same
            # progress channel -- surface it on the task so the chat UI can
            # show the site updating in real time, not just once the whole
            # build finishes.
            if preview_url:
                fields["preview_url"] = preview_url
                fields["preview_state"] = "ready"
            update_task(company_id, str(task.get("task_id") or ""), state="working", **fields)

        handoffs = "\n\n".join(f"### {item.get('name')}\n{item.get('content')}" for item in context.get("handoffs") or [])
        source_lines = "\n".join(f"- {item.get('title') or 'Source'}: {item.get('url')}" for item in sources[:12])
        build_context = f"""Company OS website brief:\n{objective}\n\nEntities: {context.get('entities') or []}\nDeliverables: {context.get('deliverables') or []}\nAcceptance criteria: {context.get('acceptance_criteria') or []}\n\nResearch handoffs:\n{handoffs[:24000] or '(none)'}\n\nVerified source URLs:\n{source_lines or '(none)'}"""
        result = run_mvp_loop(
            goal=(f"Build a complete, original, responsive website for this request: {objective}. "
                  "Use the research handoffs as the content source. Do not make a generic SaaS template. "
                  "Visibly present the researched facts, relevant sections, and source links. "
                  "This is a reviewable local build; do not publish externally."),
            session_id=session_id,
            context=build_context,
            required_files=["package.json", "app/page.tsx", "app/layout.tsx", "README.md"],
            founder_id=founder_id,
            agent="web",
            progress_callback=progress,
        ) or {}
        if result.get("error"):
            update_task(company_id, str(task.get("task_id") or ""), terminal_state="failed",
                        workspace_state="failed", preview_state="failed",
                        progress_text=f"Build failed: {result['error']}")
            return {"ok": False, "error": result["error"], "result": result}
        if result.get("build_passes") is False:
            update_task(company_id, str(task.get("task_id") or ""), terminal_state="failed",
                        workspace_state="failed", preview_state="failed",
                        progress_text="Build failed verification.")
            return {"ok": False, "error": "The coding agent did not produce a passing build.", "result": result}
        url = result.get("deploy_url") or result.get("preview_url")
        if not url:
            update_task(company_id, str(task.get("task_id") or ""), terminal_state="failed",
                        workspace_state="failed", preview_state="failed",
                        progress_text="Build finished without a reviewable preview.")
            return {"ok": False, "error": result.get("error") or "Coding agent did not produce a reviewable preview.", "result": result}
        # `run_mvp_loop` runs synchronously inside the task attempt. Persist its
        # terminal/preview completion before returning control to execute_task(),
        # which then atomically marks the task done. Without this handoff a build
        # could pass and start `next`, yet remain visibly "working/starting" and
        # prevent the dependent review and approval tasks from ever becoming ready.
        update_task(company_id, str(task.get("task_id") or ""),
                    terminal_session_id=session_id, build_session_id=session_id,
                    terminal_state="completed", workspace_state="ready",
                    preview_state="ready", preview_url=url,
                    progress_text=f"Build passed — {result.get('files_in_repo', 0)} files written",
                    activity=f"Build passed — {result.get('files_in_repo', 0)} files written")
        summary = (f"## Website build ready\n\nThe persistent coding agent created a real project and started a reviewable preview.\n\n"
                   f"- **Preview:** {url}\n- **Files:** {result.get('files_in_repo', 0)}\n"
                   f"- **Build:** {'passed' if result.get('build_passes') else 'needs review'}\n")
        return {"ok": True, "url": url, "summary": summary, "files_in_repo": result.get("files_in_repo"),
                "build_passes": result.get("build_passes"), "result": result}
    except Exception as exc:
        logger.exception("Company OS coding website agent failed: company=%s mission=%s", company_id, mission.get("mission_id"))
        # Preserve a visible diagnostic state even though execute_task() will
        # subsequently mark the task blocked. This prevents a dead terminal
        # from continuing to present itself as "starting" after a failure.
        try:
            update_task(company_id, str(task.get("task_id") or ""), terminal_state="failed",
                        workspace_state="failed", preview_state="failed", progress_text=f"Build failed: {exc}")
        except Exception:
            logger.debug("Could not persist technical build failure state", exc_info=True)
        return {"ok": False, "error": str(exc)}


def _initiative_evidence(company_id: str, initiative_id: object) -> list[Mapping[str, Any]]:
    company = get_company_os(company_id) or {}
    task_ids = {task.get("task_id") for task in company.get("tasks", []) if task.get("initiative_id") == initiative_id}
    sources: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for artifact in company.get("artifacts", []):
        if artifact.get("task_id") not in task_ids:
            continue
        for source in artifact.get("source_references") or []:
            if not isinstance(source, Mapping) or not source.get("url") or source["url"] in seen:
                continue
            seen.add(source["url"])
            sources.append(source)
    return sources[:8]


def _resume_ready_dependents(company_id: str, completed_mission_id: str) -> None:
    company = get_company_os(company_id) or {}
    completed = {item.get("mission_id") for item in company.get("missions", []) if item.get("state") == "done"}
    for mission in company.get("missions", []):
        dependencies = _mission_dependencies(mission)
        if completed_mission_id in dependencies and mission.get("state") in {"active", "working"} and dependencies.issubset(completed):
            launch_mission(company_id, mission["mission_id"])


def _completion_reply(company_id: str, mission: Mapping[str, Any]) -> str:
    """Answer in the founder's terms instead of pointing at a log line -- the
    chat thread is a conversation, not a task tracker (the sidebar already
    covers per-task status). The mission's LAST artifact is always its final
    output regardless of department (each department's 3-step plan ends on
    its "produce the output" step), so pick by recency rather than matching
    an artifact-name prefix that a synthesized title might not contain."""
    company = get_company_os(company_id) or {}
    task_ids = {task.get("task_id") for task in company.get("tasks", []) if task.get("mission_id") == mission.get("mission_id")}
    mission_artifacts = [a for a in company.get("artifacts", []) if a.get("task_id") in task_ids]
    brief = mission_artifacts[-1] if mission_artifacts else None
    if not brief or not brief.get("content"):
        return f"{mission['name']} is done. I didn't produce anything usable for it -- check the squad's artifacts for what was gathered."
    return _synthesize_chat_reply(str(mission.get("name") or ""), brief)


def _synthesize_chat_reply(mission_name: str, brief: Mapping[str, Any]) -> str:
    """Answer like an assistant that actually read the document, not a
    regex-excerpt of it. Founders were seeing raw web-search sub-query
    headers pasted verbatim into chat, plus the exact same generic
    disclaimer paragraph on every single research reply regardless of what
    was actually asked."""
    content = str(brief.get("content") or "")
    doc_name = str(brief.get("name") or "the document")
    try:
        from backend.tools._llm import generate
        prompt = f"""You are Astra Copilot telling a founder you finished researching something for them.

Their question: "{mission_name}"

The document you produced ("{doc_name}"):
{content[:6000]}

Write a concise, polished markdown update that actually answers their question using the real findings above. Use this exact shape:
- One direct opening sentence.
- 2-4 short bullet points with the most decision-relevant facts, numbers, or caveats.
- One final sentence linking them to "{doc_name}" for the full write-up.

Never repeat the document's headings or raw research queries. Do not make generic disclaimers unless the evidence genuinely warrants that caveat. Every sentence must end cleanly; do not stop mid-thought.

Respond with ONLY the reply text, nothing else, no quotes around it."""
        reply = generate(prompt, model="fast", max_tokens=700, temperature=0.35).strip().strip('"')
        if _complete_chat_reply(reply):
            return reply
    except Exception:
        logger.warning("Chat-reply synthesis failed for mission=%r", mission_name, exc_info=True)
    summary = _fallback_summary(content)
    return f"I finished looking into {mission_name.lower()}.\n\n{summary}\n\nFull write-up: **{doc_name}**."


def _complete_chat_reply(reply: str) -> bool:
    """Never surface a provider response that stopped in the middle of a thought."""
    compact = " ".join(reply.split())
    return len(compact) >= 80 and compact[-1:] in {".", "!", "?"} and len(compact) <= 3_000


def _fallback_summary(content: str) -> str:
    """Keep a provider hiccup useful without dumping arbitrary raw text into chat."""
    blocks = [block.strip() for block in content.split("\n\n") if block.strip() and not block.strip().startswith("#")]
    first = next((block for block in blocks if len(block) >= 40), "The completed brief contains the available findings and caveats.")
    sentence = first.split(". ", 1)[0].rstrip(".") + "."
    return f"- {sentence}"


def _synthesis(mission_name: str, evidence: Mapping[str, Any]) -> tuple[str, str]:
    if not evidence.get("source_references"):
        raise RuntimeError("Cannot synthesize uncited research evidence.")
    return _synthesize_document(mission_name, evidence, purpose="synthesizing raw research into a clear internal note",
                                fallback_title=f"Research notes — {_short_title(mission_name)}")


def _decision_brief(mission_name: str, evidence: Mapping[str, Any]) -> tuple[str, str]:
    if not evidence.get("source_references"):
        raise RuntimeError("Cannot produce a decision brief without cited evidence.")
    if evidence.get("deep_research_supervisor"):
        # The Open Deep Research supervisor already wrote a fully cited,
        # multi-section report -- re-summarizing it through _synthesize_document
        # would throw its citations and structure away for a generic 400-900
        # word note. Use it as-is; only fall through if it came back thin.
        report = str(evidence.get("content") or "").strip()
        if len(report) > 500:
            return _report_title(report, fallback_title=f"Findings — {_short_title(mission_name)}"), report
    if _has_comparison_evidence(evidence):
        return _synthesize_comparison_document(mission_name, evidence)
    return _synthesize_document(mission_name, evidence, purpose="writing a decision-ready brief",
                                fallback_title=f"Findings — {_short_title(mission_name)}")


def _report_title(report: str, *, fallback_title: str) -> str:
    match = re.match(r"^#\s+(.+)$", report.split("\n", 1)[0].strip())
    return _short_title(match.group(1)) if match else fallback_title


def _synthesize_comparison_document(mission_name: str, evidence: Mapping[str, Any]) -> tuple[str, str]:
    """LLM-write a real comparison report (executive summary, a dimension
    table, thematic deep-dive sections, pros/cons per subject, a bottom
    line) grounded only in fetched evidence -- the mechanical table-only
    _comparison_document() below was never actually reachable for a real
    "compare X and Y" request until this function replaced it as the
    primary path (it's now only the safety-net fallback on LLM failure).
    Preserves the original safety property: never invent a winner beyond
    what the evidence supports, and say so plainly when coverage is thin."""
    ledger = evidence.get("evidence_ledger") or {}
    subjects = list(ledger)
    if len(subjects) != 2:
        return _comparison_document(mission_name, evidence)
    left, right = subjects
    coverage = evidence.get("coverage") or {}
    ready = bool(coverage.get("ready"))
    raw = str(evidence.get("combined_formatted") or "").strip()
    if not raw:
        return _comparison_document(mission_name, evidence)

    evidence_by_subject = []
    for subject in subjects:
        lines = [f"### {subject}"]
        for dimension, claims in (ledger.get(subject) or {}).items():
            for claim in claims[:4]:
                if isinstance(claim, Mapping) and claim.get("excerpt"):
                    lines.append(f"- [{dimension}] {claim['excerpt']} (Source: {claim.get('title') or 'Source'}, {claim.get('url') or ''})")
        evidence_by_subject.append("\n".join(lines))

    prompt = f"""You are a sharp analyst writing a comparison report for a founder deciding between two products/companies: "{left}" and "{right}".

Fetched evidence, organized by subject and dimension (each line is one claim grounded in a real fetched page, with its source):
{chr(10).join(evidence_by_subject)}

Raw combined research text (for additional context and phrasing, may overlap the evidence above):
{raw[:14000]}

Evidence coverage is {"sufficient across both subjects" if ready else "THIN for at least one subject/dimension -- be explicit about which claims are unverified rather than guessing"}.

Write a genuinely useful, comprehensive markdown comparison report. Requirements:
- Open with "## Executive summary": 2-3 paragraphs giving the direct, specific comparison and where each subject is stronger, using only what the evidence above actually supports.
- "## Comparison overview": a markdown table with rows for the dimensions the evidence actually covers (e.g. business model, pricing, target customers, team/leadership visibility, technology/documentation, evidence and credibility, legal terms) and one column per subject, plus an "Analytical take" column. Write "Not verified from available public evidence" for any cell the evidence doesn't support -- never invent a value.
- 2-4 more "##" deep-dive sections grouping related dimensions into a coherent narrative (e.g. "Business model and pricing", "Team and technology", "Evidence, reputation, and legal terms") -- do not just repeat the table as prose; synthesize and explain what the differences mean for a founder's decision.
- A "### {left} pros and cons" and "### {right} pros and cons" section, each a two-column markdown table (Pros | Cons), grounded in the evidence.
- End with "## Bottom line": a direct, specific recommendation of which subject fits which kind of founder/use case, {"including a clear recommendation since the evidence is sufficient" if ready else "explicitly declining to declare an overall winner given the evidence gaps, while still summarizing the clearest differences"}.
- Pull real facts, names, and numbers from the evidence above. Never invent specifics, comparisons, or claims the evidence doesn't support.
- Aim for 900-1600 words of real substance -- this is a comprehensive report, not a summary.
- Do not mention Astra, tools, AI systems, or how this research was conducted -- focus entirely on the two subjects and the evidence.

Respond with ONLY this JSON object, no prose, no markdown fence:
{{"title": "<a specific 4-9 word title, e.g. '{left} and {right} Compared'>", "content": "<the full markdown document>"}}"""
    try:
        from backend.tools._llm import generate, parse_json_response
        raw_response = generate(prompt, model="large", json_mode=True, max_tokens=4000, temperature=0.5)
        parsed = parse_json_response(raw_response)
        title, content = str(parsed.get("title") or "").strip(), str(parsed.get("content") or "").strip()
        if title and content:
            return title, content
    except Exception:
        logger.warning("Comparison document synthesis failed for mission=%r, falling back to the evidence table", mission_name, exc_info=True)
    return _comparison_document(mission_name, evidence)


def _comparison_document(mission_name: str, evidence: Mapping[str, Any]) -> tuple[str, str]:
    ledger = evidence.get("evidence_ledger") or {}
    subjects = list(ledger)
    if len(subjects) != 2:
        return "Comparison evidence incomplete", "## Evidence incomplete\n\nThe requested products could not be identified reliably. No recommendation was made."
    left, right = subjects
    dimensions = (("Product and target user", "product"), ("Core workflow", "workflow"), ("Pricing and packaging", "pricing"), ("Privacy and compliance", "privacy"), ("Evidence and maturity", "evidence_maturity"))
    rows = []
    gaps = []
    for label, key in dimensions:
        values = []
        for subject in subjects:
            claims = ledger.get(subject, {}).get(key) or []
            if claims:
                values.append("; ".join(
                    f"[{item.get('title') or 'Source'}]({item.get('url')}) ({item.get('source_classification') or item.get('source_type') or 'source'})"
                    for item in claims[:2]
                ))
            else:
                values.append("Not verified from available public evidence")
                gaps.append(f"{subject}: {label}")
        rows.append(f"| {label} | {values[0]} | {values[1]} |")
    title = f"{_short_title(left)} and {_short_title(right)} comparison"
    ready = bool((evidence.get("coverage") or {}).get("ready")) and not gaps
    direct_answer = "The comparison gate passed; the ledger below is ready for a founder decision, without automatically declaring a winner." if ready else "A recommendation is withheld because Astra only compares products when both sides have verified evidence for every core dimension."
    body = ["## Direct answer", direct_answer, "", "## Verified evidence", f"| Dimension | {left} | {right} |", "| --- | --- | --- |", *rows, "", "## Evidence gaps"]
    body.extend(f"- {gap}" for gap in gaps) if gaps else body.extend(["- Both products met the balanced evidence gate."])
    body.extend(["", "## Bottom line", "No winner is declared until the evidence gaps above are filled with direct, publicly verifiable sources." if not ready else "Use the cited fetched evidence to weigh the founder's specific priorities; Astra does not infer a winner from source counts alone."])
    return title, "\n".join(body)


def _is_website_request(value: str) -> bool:
    return any(term in value.lower() for term in ("website", "web site", "landing page", "web app", "frontend"))


def _website_generation_context(company_id: str, mission: Mapping[str, Any], task: Mapping[str, Any]) -> dict[str, Any]:
    """Carry the planner's intent and completed handoffs into page generation."""
    company = get_company_os(company_id) or {}
    initiative = _find(company.get("initiatives", []), "initiative_id", mission.get("initiative_id")) or {}
    squad = _find(company.get("squads", []), "squad_id", mission.get("squad_id")) or {}
    by_id = {str(item.get("task_id")): item for item in company.get("tasks", [])}
    required: set[str] = set()
    pending = list(task.get("depends_on_task_ids") or [])
    while pending:
        task_id = str(pending.pop())
        if task_id in required:
            continue
        required.add(task_id)
        pending.extend(by_id.get(task_id, {}).get("depends_on_task_ids") or [])
    handoff_ids = {str(item.get("task_id")) for item in company.get("tasks", []) if str(item.get("task_id")) in required}
    handoffs = []
    for artifact in company.get("artifacts", []):
        if str(artifact.get("task_id")) in handoff_ids and str(artifact.get("content") or "").strip():
            handoffs.append({"name": artifact.get("name"), "content": str(artifact.get("content"))[:5_000]})
    request = initiative.get("work_request") if isinstance(initiative.get("work_request"), Mapping) else {}
    return {
        "objective": request.get("outcome") or initiative.get("objective") or mission.get("name"),
        "deliverables": request.get("deliverables") or [], "constraints": request.get("constraints") or [],
        "entities": request.get("entities") or [], "acceptance_criteria": task.get("acceptance_criteria") or initiative.get("success_criteria") or [],
        "squad_charter": squad.get("squad_charter") or squad.get("charter") or "",
        "handoffs": handoffs,
    }


def _website_brief(request: str, context: Mapping[str, Any] | None = None) -> str:
    domain, brand = _website_identity(request)
    context = context or {}
    deliverables = ", ".join(str(item) for item in context.get("deliverables") or []) or "A reviewable website preview"
    criteria = "; ".join(str(item) for item in context.get("acceptance_criteria") or []) or "Clear, request-specific structure and copy"
    return f"## {brand} website brief\n\n- **Destination:** `{domain}`\n- **Outcome:** {context.get('objective') or request}\n- **Deliverables:** {deliverables}\n- **Acceptance:** {criteria}\n- **Scope:** a local, reviewable website concept before any external publication\n"


def _website_architecture(request: str, context: Mapping[str, Any]) -> str:
    domain, brand = _website_identity(request)
    entities = ", ".join(str(item) for item in context.get("entities") or []) or brand
    return f"## {brand} website architecture\n\n- **Information architecture:** narrative hero, subject-specific proof, focused offer, and one clear call to action.\n- **Primary subject:** {entities}\n- **Design constraint:** create a distinct visual direction from the initiative brief, not a generic product dashboard.\n- **Handoffs considered:** {len(context.get('handoffs') or [])} completed upstream artifact(s).\n- **Responsive contract:** usable at 320px and desktop widths, with no external side effects.\n"


_GENERIC_WEBSITE_COPY = {
    "eyebrow": "A calmer way to build momentum",
    "headline_plain": "Make the next move", "headline_emphasis": "obvious.",
    "lede": "{brand} turns scattered company work into a focused, visible path from question to decision to execution.",
    "section2_heading": "One place to understand the work. One clear next step.",
    "section2_body": "This concept combines the strongest category-level expectations for founder software: a durable company context, clear ownership, and reviewable output. Specific competitor claims are deliberately withheld until the comparison evidence is complete.",
    "cards": [
        {"label": "01 / Orient", "title": "Bring the whole company into view.", "description": "Goals, evidence, decisions, and unfinished work stay connected."},
        {"label": "02 / Decide", "title": "Turn uncertainty into a practical plan.", "description": "Work is scoped, owned, and made easy to review before anything external happens."},
        {"label": "03 / Move", "title": "Ship with context, not chaos.", "description": "Specialist work happens in coordinated squads, with approvals where they matter."},
    ],
}


def _website_copy(request: str, brand: str, sources: list[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """LLM-write copy specific to what was actually asked for, instead of the
    same generic "bring the whole company into view" boilerplate every local
    website preview used to ship with verbatim -- confirmed live, every
    preview a founder generated was textually identical except for the brand
    name. Falls back to that same generic copy (still usable, just not
    differentiated) if the call fails, same defensive pattern as every other
    LLM step in this file."""
    try:
        from backend.tools._llm import generate, parse_json_response
        source_lines = "\n".join(f"- {s.get('title') or 'Source'}: {s.get('url') or ''}" for s in (sources or [])[:8] if isinstance(s, Mapping))
        prompt = f"""Write landing-page copy for a local website preview.

What the founder asked for: "{request}"
Site name: "{brand}"
Cited research sources available (may be empty):
{source_lines or "(none)"}

Write copy that is SPECIFIC to what was actually asked for -- name the real subject (a company, product, or comparison) instead of generic SaaS platitudes. If this is a comparison site, the copy should be about comparing those specific things. If sources are empty, do not invent specific facts/numbers -- keep claims general but still on-topic for the actual subject.

Respond with ONLY this JSON object, no prose, no markdown fence:
{{"eyebrow": "<3-6 word kicker line>", "headline_plain": "<short headline start, 2-5 words>", "headline_emphasis": "<the final emphasized word/phrase of the headline, ending in a period>", "lede": "<one sentence, specific to the subject>", "section2_heading": "<5-10 word heading>", "section2_body": "<2-3 sentences, specific to the subject>", "cards": [{{"label": "01 / <one word>", "title": "<short bold line>", "description": "<one sentence>"}}, {{"label": "02 / <one word>", "title": "<short bold line>", "description": "<one sentence>"}}, {{"label": "03 / <one word>", "title": "<short bold line>", "description": "<one sentence>"}}]}}"""
        raw = generate(prompt, model="fast", json_mode=True, max_tokens=700, temperature=0.6)
        parsed = parse_json_response(raw)
        cards = parsed.get("cards")
        if (isinstance(cards, list) and len(cards) == 3
                and all(isinstance(c, Mapping) and c.get("label") and c.get("title") and c.get("description") for c in cards)
                and parsed.get("headline_plain") and parsed.get("headline_emphasis") and parsed.get("lede")
                and parsed.get("section2_heading") and parsed.get("section2_body") and parsed.get("eyebrow")):
            return parsed
    except Exception:
        logger.warning("Website copy synthesis failed for request=%r, falling back to generic copy", request, exc_info=True)
    generic = copy.deepcopy(_GENERIC_WEBSITE_COPY)
    generic["lede"] = generic["lede"].format(brand=brand)
    return generic


def _website_preview(request: str, sources: list[Mapping[str, Any]] | None = None,
                     context: Mapping[str, Any] | None = None) -> str:
    domain, brand = _website_identity(request)
    generated = _generated_website_html(request, brand, domain, sources, context or {})
    if generated:
        return generated
    try:
        copy_data = _website_copy(request, brand, sources)
        if copy_data != _GENERIC_WEBSITE_COPY and copy_data.get("headline_plain"):
            return _request_specific_website(request, brand, domain, sources, context or {}, copy_data)
    except Exception:
        logger.warning("Request-specific website copy failed; using subject renderer", exc_info=True)
    # A provider failure must not turn a bespoke request into the old Astra
    # shell. Keep the preview useful and visibly tied to the founder's subject
    # even when the design model is unavailable.
    return _request_specific_website(request, brand, domain, sources, context or {})


def _request_specific_website(request: str, brand: str, domain: str,
                              sources: list[Mapping[str, Any]] | None,
                              context: Mapping[str, Any],
                              copy_data: Mapping[str, Any] | None = None) -> str:
    subject = str(context.get("objective") or request).strip()
    subject = re.sub(r"^(?:build\s+(?:a\s+)?website\s+(?:for|about|comparing)|compare)\s*", "", subject, flags=re.IGNORECASE).strip() or subject
    subject = re.sub(r"\s+and\s+create\s+a\s+website.*$", "", subject, flags=re.IGNORECASE).strip() or subject
    entities = [str(item) for item in context.get("entities") or [] if str(item).strip()]
    source_cards = [item for item in (sources or [])[:6] if isinstance(item, Mapping) and item.get("url")]
    handoff_text = " ".join(str(item.get("content") or "") for item in context.get("handoffs") or [])
    # Keep source-backed text short and safe; this is a resilient renderer, not
    # a second synthesis pass that could invent claims.
    evidence_note = (f"Informed by {len(source_cards)} cited research source{'s' if len(source_cards) != 1 else ''} attached to this initiative."
                     if source_cards else "This concept is awaiting verified source material before factual claims are published.")
    copy_data = copy_data or {}
    title = html.escape(brand)
    headline = html.escape(str(copy_data.get("headline_plain") or brand))
    emphasis = html.escape(str(copy_data.get("headline_emphasis") or "has a point of view."))
    lede = html.escape(str(copy_data.get("lede") or subject))
    supporting_copy = html.escape(str(copy_data.get("section2_body") or "The page keeps the requested subject, supporting evidence, and next action in one clear narrative."))
    entity_line = html.escape(" · ".join(entities) if entities else subject[:120])
    cards = []
    for index, source in enumerate(source_cards, 1):
        source_title = html.escape(str(source.get("title") or source.get("url") or "Source"))
        source_url = html.escape(str(source.get("url")), quote=True)
        cards.append(f'<article><span>0{index}</span><h3>{source_title}</h3><a href="{source_url}">Open source</a></article>')
    if not cards:
        cards = [
            '<article><span>01</span><h3>Clarify the decision</h3><p>Turn the request into a focused, reviewable outcome.</p></article>',
            '<article><span>02</span><h3>Show the evidence</h3><p>Keep the important inputs visible instead of hiding them in a generic template.</p></article>',
            '<article><span>03</span><h3>Make the next move</h3><p>Give visitors one clear action that matches the subject of this site.</p></article>',
        ]
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} | {html.escape(subject[:72])}</title>
<style>
:root{{--ink:#17202a;--paper:#f4efe6;--hot:#d64b2f;--line:#c9bdaa}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font-family:Georgia,serif}}header,main,footer{{max-width:1180px;margin:auto;padding:28px clamp(22px,5vw,72px)}}header{{display:flex;justify-content:space-between;border-bottom:1px solid var(--line);font:700 12px/1.2 system-ui;letter-spacing:.12em;text-transform:uppercase}}.kicker{{color:var(--hot);font:700 13px system-ui;letter-spacing:.16em;text-transform:uppercase;margin-top:110px}}h1{{font-size:clamp(52px,9vw,126px);line-height:.9;max-width:950px;margin:18px 0 28px;letter-spacing:-.07em}}.lede{{font-size:clamp(20px,2.5vw,32px);line-height:1.25;max-width:720px}}.subject{{margin:70px 0 0;padding:18px 0;border-top:3px solid var(--ink);font:600 14px system-ui}}section{{padding:90px 0;border-top:1px solid var(--line);display:grid;grid-template-columns:1fr 2fr;gap:50px}}h2{{font-size:clamp(34px,5vw,68px);line-height:.95;margin:0;letter-spacing:-.05em}}.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}}article{{border:1px solid var(--line);padding:22px;min-height:180px;background:#fffaf2}}article span{{color:var(--hot);font:700 13px system-ui}}h3{{font-size:22px;line-height:1.05}}p{{font:16px/1.5 system-ui;color:#56616b}}a{{color:var(--hot);font:700 13px system-ui}}.note{{font:15px/1.6 system-ui;max-width:620px}}footer{{border-top:1px solid var(--line);display:flex;justify-content:space-between;font:600 11px system-ui;letter-spacing:.1em;text-transform:uppercase}}@media(max-width:700px){{header,footer{{display:block}}header span,footer span{{display:block;margin-bottom:8px}}.kicker{{margin-top:70px}}section{{display:block}}.grid{{grid-template-columns:1fr}}}}
</style></head><body><header><strong>{title}</strong><span>{html.escape(domain)} / original concept</span></header><main><div class="kicker">A site built for this request</div><h1>{headline}<br><i>{emphasis}</i></h1><p class="lede">{lede}</p><div class="subject">{entity_line}</div><section><h2>{html.escape(str(copy_data.get("section2_heading") or "What this page is here to show."))}</h2><div><p class="note">{supporting_copy} {html.escape(evidence_note)} The composition, language, and content are specific to the requested subject and are ready for review before publication.</p><div class="grid">{"".join(cards)}</div></div></section></main><footer><span>{title}</span><span>Local preview / subject-specific build</span></footer></body></html>'''
    evidence_count = len(sources or [])
    source_note = f"Informed by {evidence_count} cited research source{'s' if evidence_count != 1 else ''} gathered for this initiative." if evidence_count else "Built as a local concept; product claims remain pending verified comparison evidence."
    copy_data = _website_copy(request, brand, sources)
    cards_html = "".join(
        f'<article class="card"><span class="number">{html.escape(str(c["label"]))}</span><b>{html.escape(str(c["title"]))}</b><span>{html.escape(str(c["description"]))}</span></article>'
        for c in copy_data["cards"]
    )
    variant = int(hashlib.sha256(request.encode("utf-8")).hexdigest()[:2], 16) % 3
    themes = (
        ("#10211e", "#f4f0e8", "#d8ff52", "#16342d", "#0d201c", "#fbf9f4"),
        ("#101827", "#f3f7fc", "#6ee7ff", "#14213d", "#273a68", "#ffffff"),
        ("#341b18", "#fff6eb", "#ff9d66", "#7c3026", "#3b1716", "#fffdfa"),
    )
    ink, canvas, accent, hero_start, hero_end, card = themes[variant]
    return f"""<!doctype html>
<html><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>{html.escape(brand)} | Preview</title><link rel=\"preconnect\" href=\"https://fonts.googleapis.com\"><link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin><link href=\"https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Manrope:wght@400;500;600;700;800&family=Playfair+Display:ital,wght@0,600;0,700;1,600&display=swap\" rel=\"stylesheet\"><style>:root{{--ink:{ink};--canvas:{canvas};--accent:{accent};--card:{card}}}*{{box-sizing:border-box}}body{{margin:0;background:var(--canvas);color:var(--ink);font-family:Manrope,sans-serif}}.hero{{min-height:680px;padding:28px clamp(24px,6vw,88px);background:radial-gradient(circle at 85% 16%,var(--accent) 0 9%,transparent 30%),linear-gradient(124deg,{hero_start},{hero_end} 60%,{hero_start});color:#f8f5ed;overflow:hidden}}nav{{display:flex;justify-content:space-between;align-items:center;font-weight:800}}.mark{{display:flex;gap:9px;align-items:center;font-size:20px}}.dot{{width:13px;height:13px;border-radius:50%;background:var(--accent);box-shadow:0 0 0 6px color-mix(in srgb,var(--accent) 20%,transparent)}}.navlink,.eyebrow,.caption,.number,footer{{font:500 11px 'DM Mono';letter-spacing:.1em;text-transform:uppercase}}.navlink{{color:#d7e6dc}}.hero-copy{{max-width:870px;margin:120px 0 64px}}.eyebrow{{color:var(--accent);letter-spacing:.13em}}h1{{font:600 clamp(52px,8vw,112px)/.96 'Playfair Display',serif;letter-spacing:-.06em;margin:18px 0 28px}}h1 em{{color:var(--accent)}}.lede{{font-size:clamp(18px,2vw,24px);line-height:1.5;max-width:640px;color:#d8e5de}}.actions{{display:flex;gap:14px;align-items:center;margin-top:38px}}button{{border:0;border-radius:999px;padding:15px 22px;background:var(--accent);color:var(--ink);font:800 14px Manrope}}.caption{{color:#b8cbc1;letter-spacing:0;text-transform:none}}section{{padding:88px clamp(24px,6vw,88px)}}.split{{display:grid;grid-template-columns:1.1fr 1fr;gap:64px;align-items:start}}h2{{font:600 clamp(36px,5vw,60px)/1 'Playfair Display',serif;letter-spacing:-.05em;margin:0}}.body{{font-size:18px;line-height:1.65;color:color-mix(in srgb,var(--ink) 70%,white)}}.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:46px}}.card{{min-height:210px;padding:24px;border:1px solid color-mix(in srgb,var(--ink) 15%,transparent);border-radius:{12 + variant * 8}px;background:var(--card)}}.card b{{display:block;margin:40px 0 8px;font-size:18px}}.number{{color:color-mix(in srgb,var(--ink) 55%,white)}}.evidence{{padding:24px 28px;border-radius:14px;background:color-mix(in srgb,var(--accent) 20%,var(--canvas));font:500 13px/1.6 'DM Mono';color:var(--ink)}}footer{{padding:28px clamp(24px,6vw,88px);display:flex;justify-content:space-between;border-top:1px solid color-mix(in srgb,var(--ink) 15%,transparent);color:color-mix(in srgb,var(--ink) 62%,white)}}@media(max-width:700px){{.hero{{min-height:560px}}.hero-copy{{margin-top:82px}}.split,.cards{{grid-template-columns:1fr}}section{{padding-top:60px;padding-bottom:60px}}}}</style></head><body><header class=\"hero\"><nav><div class=\"mark\"><span class=\"dot\"></span>{html.escape(brand)}</div><span class=\"navlink\">{html.escape(domain)} / local concept</span></nav><div class=\"hero-copy\"><div class=\"eyebrow\">{html.escape(str(copy_data["eyebrow"]))}</div><h1>{html.escape(str(copy_data["headline_plain"]))} <em>{html.escape(str(copy_data["headline_emphasis"]))}</em></h1><p class=\"lede\">{html.escape(str(copy_data["lede"]))}</p><div class=\"actions\"><button>Explore the idea</button><span class=\"caption\">Local preview</span></div></div></header><main><section class=\"split\"><h2>{html.escape(str(copy_data["section2_heading"]))}</h2><div class=\"body\">{html.escape(str(copy_data["section2_body"]))}</div></section><section><div class=\"eyebrow\" style=\"color:var(--ink)\">What it makes possible</div><div class=\"cards\">{cards_html}</div></section><section><div class=\"evidence\">RESEARCH STATUS / {html.escape(source_note)}</div></section></main><footer><span>{html.escape(brand)} / {html.escape(domain)}</span><span>LOCAL WEBSITE PREVIEW</span></footer></body></html>"""


def _generated_website_html(request: str, brand: str, domain: str, sources: list[Mapping[str, Any]] | None,
                            context: Mapping[str, Any]) -> str | None:
    """Generate an original, safe-to-host static page rather than filling one shell."""
    try:
        from backend.tools._llm import generate, parse_json_response
        evidence = "\n".join(
            f"- {item.get('title') or 'Source'}: {item.get('url') or ''}"
            for item in (sources or [])[:8] if isinstance(item, Mapping)
        ) or "No verified research sources were attached."
        handoffs = "\n\n".join(f"### {item.get('name')}\n{item.get('content')}" for item in context.get("handoffs") or []) or "No upstream artifacts yet."
        prompt = f"""You are the lead designer and frontend engineer for a bespoke website concept.

Founder request: {request!r}
Brand: {brand!r}
Destination: {domain!r}
Verified source references: {evidence}
Initiative objective: {context.get('objective') or request}
Deliverables: {context.get('deliverables') or []}
Constraints: {context.get('constraints') or []}
Acceptance criteria: {context.get('acceptance_criteria') or []}
Squad charter: {context.get('squad_charter') or '(not recorded)'}
Completed squad handoffs:
{handoffs[:10_000]}

Create an ORIGINAL, self-contained single-page website for this exact request. Do not reuse a generic SaaS dashboard layout, a prior visual direction, or generic phrases such as "bring the whole company into view." Pick one distinct art direction that fits the request, then make the typography, color system, composition, sections, and copy serve that direction. Use real, request-specific copy. Do not invent factual claims unsupported by the source references. This is a static reviewable preview: no JavaScript, forms, iframes, analytics, external images, or external links. You may use CSS only, including inline SVG shapes.

Return ONLY JSON: {{"html":"<!doctype html>..."}}. The HTML must include responsive CSS and be between 2,000 and 55,000 characters."""
        parsed = parse_json_response(generate(prompt, model="large", json_mode=True, max_tokens=6000, temperature=0.85))
        candidate = str(parsed.get("html") or "").strip()
        blocked = ("<script", "<iframe", "<form", "javascript:", " onerror=", " onclick=")
        if (candidate.lower().startswith("<!doctype html") and 2_000 <= len(candidate) <= 55_000
                and all(token not in candidate.lower() for token in blocked)):
            return candidate
    except Exception:
        logger.warning("Bespoke website generation failed; using request-specific renderer", exc_info=True)
    return None


def _website_identity(request: str) -> tuple[str, str]:
    match = re.search(r"\b(?:for|at)\s+([a-z0-9-]+\.[a-z]{2,})\b", request.lower())
    domains = re.findall(r"\b[a-z0-9-]+\.[a-z]{2,}\b", request.lower())
    domain = (match.group(1) if match else (domains[-1] if domains else "newco.local")).strip(".")
    return domain, domain.split(".", 1)[0].replace("-", " ").title()


def _synthesize_document(mission_name: str, evidence: Mapping[str, Any], *, purpose: str, fallback_title: str) -> tuple[str, str]:
    """LLM-synthesize a real document from raw research evidence instead of
    truncate-and-glue with a fixed generic ending. The old version appended
    the identical "Treat this as a hypothesis..." paragraph to every single
    research task's output verbatim, and forced a market-sizing structure
    onto every question including plain "what is X" lookups. Falls back to a
    plain excerpt (uglier, but honest and still usable) if the LLM call
    fails, so a model hiccup never blocks the mission."""
    raw = str(evidence.get("content") or evidence.get("combined_formatted") or "").strip() or "No evidence content was captured."
    source_refs = evidence.get("source_references") or evidence.get("sources") or []
    source_lines = [f"- {source.get('title') or 'Source'}: {source.get('url') or ''}" for source in source_refs[:12] if isinstance(source, Mapping)]
    comparison = _has_comparison_evidence(evidence)
    comparison_requirements = """\n- This is a comparison. Include a compact markdown table with these rows: Product and target user, Core workflow, Pricing and packaging, Evidence and maturity, Privacy/compliance signals, and Key uncertainty. Use the two products as columns.
- Directly answer which option is better for the founder's stated goal, and why. If the evidence does not establish a fact, write "Not verified from available public evidence" rather than guessing.\n""" if comparison else ""
    prompt = f"""You are a sharp research analyst {purpose}.

The founder's actual question: "{mission_name}"

Raw research evidence (pulled from several web sub-queries; some may be generic or tangential -- use only what actually answers the founder's question and ignore the rest):
{raw[:12000]}

Cited sources:
{chr(10).join(source_lines) or "(none captured)"}

Write a genuinely useful markdown document that answers the founder's actual question. Requirements:
- Open with a direct, specific answer to the question -- no throat-clearing, no "based on the research provided".
- Organize with ## headings that fit what was ACTUALLY asked. Do not force structure, frameworks, or metrics that the evidence does not support. Only use TAM/SAM/CAGR analysis if the evidence you found directly addresses market size and the founder's question is about market viability.
- Pull real facts, numbers, and names from the evidence above. Skip anything the evidence doesn't actually support -- don't invent specifics, don't invent analysis, don't invent frameworks.
- Never repeat the raw sub-query headers verbatim or paste sub-query blocks one after another -- synthesize across all of them into one coherent piece of writing.
- Aim for 400-900 words of real substance -- long enough to be genuinely useful, never padded with filler.
- End with a "## Bottom line" section: one specific, actionable takeaway grounded in what was actually found here. Only include caveats or uncertainty that the evidence genuinely supports.
- Do not mention Astra, tools, AI systems, or how this research was conducted -- focus entirely on the founder's question and the evidence.
{comparison_requirements}

Respond with ONLY this JSON object, no prose, no markdown fence:
{{"title": "<a specific, concrete 4-9 word document title -- never generic labels like \\"Decision brief\\" or \\"Research synthesis\\">", "content": "<the full markdown document>"}}"""
    try:
        from backend.tools._llm import generate, parse_json_response
        raw_response = generate(prompt, model="large", json_mode=True, max_tokens=2600, temperature=0.5)
        parsed = parse_json_response(raw_response)
        title, content = str(parsed.get("title") or "").strip(), str(parsed.get("content") or "").strip()
        if title and content:
            return title, content
    except Exception:
        logger.warning("Document synthesis failed for mission=%r, falling back to raw excerpt", mission_name, exc_info=True)
    return fallback_title, f"## {fallback_title}\n\n{raw[:8000]}"


def _has_comparison_evidence(evidence: Mapping[str, Any]) -> bool:
    """Was this actually researched as a two-subject comparison?

    Previously guessed from the mission's name text via a "compare" in
    lowered substring check -- which also matched "compared"/"comparison"/
    etc. in a plain, non-comparison question ("...so smart and efficient
    compared to other models"), and unlike the same bug already fixed in
    astra_mcp.py's research-execution routing, misclassifying it HERE meant
    a real astra_quick_search/run_research_pipeline result (correctly not
    comparison-shaped) got forced through _comparison_document, which
    requires exactly two evidence_ledger subjects and always failed with
    "Comparison evidence incomplete" for anything else. evidence_ledger is
    only ever populated by run_comparison_research's actual comparison
    pipeline -- checking it directly is ground truth, not a second guess
    from the same text a different regex already got wrong once."""
    return len(evidence.get("evidence_ledger") or {}) == 2


def _short_title(text: str, limit: int = 60) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _research_subject(intent: str) -> str:
    """Resolve high-risk product-language ambiguity before web queries are generated."""
    if "cookie clicker" in intent.lower():
        return f"{intent} as an idle/incremental video game, including game monetization, retention, platform fees, player acquisition, and comparable games"
    return intent


def _find(items: list[Mapping[str, Any]], key: str, value: object) -> Mapping[str, Any] | None:
    return next((item for item in items if item.get(key) == value), None)
