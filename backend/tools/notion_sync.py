"""One-way Astra -> Notion operating system mirror."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }


def _rich_text(text: str) -> list[dict[str, Any]]:
    if not text:
        text = "-"
    return [{"type": "text", "text": {"content": text[:1800]}}]


def _title(text: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": {"content": (text or "Untitled")[:1800]}}]


def _get_requests():
    import requests

    return requests


def _ensure_database(token: str, parent_id: str, title: str) -> dict[str, Any]:
    requests = _get_requests()
    search = requests.post(
        "https://api.notion.com/v1/search",
        headers=_headers(token),
        json={"query": title, "filter": {"property": "object", "value": "database"}},
        timeout=20,
    )
    if search.ok:
        for item in search.json().get("results", []):
            if item.get("title") and any(fragment.get("plain_text") == title for block in item["title"]):
                parent = item.get("parent") or {}
                if parent.get("page_id") == parent_id:
                    return {"ok": True, "database_id": item.get("id"), "url": item.get("url"), "created": False}

    create = requests.post(
        "https://api.notion.com/v1/databases",
        headers=_headers(token),
        json={
            "parent": {"type": "page_id", "page_id": parent_id},
            "title": _title(title),
            "properties": {
                "Name": {"title": {}},
                "Astra ID": {"rich_text": {}},
                "Type": {"rich_text": {}},
                "Status": {"rich_text": {}},
                "Owner": {"rich_text": {}},
                "Parent Astra ID": {"rich_text": {}},
                "Source Session": {"rich_text": {}},
                "Notes": {"rich_text": {}},
            },
        },
        timeout=20,
    )
    data = create.json()
    if not create.ok:
        return {"ok": False, "error": data.get("message", create.text[:300])}
    return {"ok": True, "database_id": data.get("id"), "url": data.get("url"), "created": True}


def _find_page_by_astra_id(token: str, database_id: str, astra_id: str) -> dict[str, Any] | None:
    requests = _get_requests()
    res = requests.post(
        f"https://api.notion.com/v1/databases/{database_id}/query",
        headers=_headers(token),
        json={"filter": {"property": "Astra ID", "rich_text": {"equals": astra_id}}},
        timeout=20,
    )
    if not res.ok:
        return None
    results = res.json().get("results", [])
    return results[0] if results else None


def _page_properties(
    *,
    title: str,
    astra_id: str,
    row_type: str,
    status: str,
    owner: str,
    parent_astra_id: str,
    source_session_id: str,
    notes: str,
) -> dict[str, Any]:
    return {
        "Name": {"title": _title(title)},
        "Astra ID": {"rich_text": _rich_text(astra_id)},
        "Type": {"rich_text": _rich_text(row_type[:100] or "item")},
        "Status": {"rich_text": _rich_text(status[:100] or "pending")},
        "Owner": {"rich_text": _rich_text(owner)},
        "Parent Astra ID": {"rich_text": _rich_text(parent_astra_id)},
        "Source Session": {"rich_text": _rich_text(source_session_id)},
        "Notes": {"rich_text": _rich_text(notes[:1800])},
    }


def _upsert_page(
    token: str,
    database_id: str,
    *,
    title: str,
    astra_id: str,
    row_type: str,
    status: str,
    owner: str,
    parent_astra_id: str,
    source_session_id: str,
    notes: str,
) -> dict[str, Any]:
    requests = _get_requests()
    current = _find_page_by_astra_id(token, database_id, astra_id)
    properties = _page_properties(
        title=title,
        astra_id=astra_id,
        row_type=row_type,
        status=status,
        owner=owner,
        parent_astra_id=parent_astra_id,
        source_session_id=source_session_id,
        notes=notes,
    )
    if current and current.get("id"):
        res = requests.patch(
            f"https://api.notion.com/v1/pages/{current['id']}",
            headers=_headers(token),
            json={"properties": properties},
            timeout=20,
        )
        data = res.json()
        if not res.ok:
            return {"ok": False, "error": data.get("message", res.text[:300])}
        return {"ok": True, "page_id": data.get("id"), "url": data.get("url"), "updated": True}
    res = requests.post(
        "https://api.notion.com/v1/pages",
        headers=_headers(token),
        json={"parent": {"database_id": database_id}, "properties": properties},
        timeout=20,
    )
    data = res.json()
    if not res.ok:
        return {"ok": False, "error": data.get("message", res.text[:300])}
    return {"ok": True, "page_id": data.get("id"), "url": data.get("url"), "updated": False}


def sync_founder_operating_system(founder_id: str) -> dict[str, Any]:
    from backend.config import settings
    from backend.missions.company_goal import get_company_goal, upsert_company_goal
    from backend.missions.store import list_missions, update_mission, update_task

    token = getattr(settings, "notion_token", "") or ""
    parent_id = getattr(settings, "notion_operating_parent_id", "") or ""
    if not token or not parent_id:
        return {
            "ok": False,
            "skipped": True,
            "reason": "missing_notion_config",
            "detail": "Set NOTION_TOKEN and NOTION_OPERATING_PARENT_ID to enable Astra -> Notion sync.",
        }

    company_goal = get_company_goal(founder_id)
    if not company_goal:
        return {"ok": False, "skipped": True, "reason": "missing_company_goal"}

    db_result = _ensure_database(token, parent_id, f"Astra Operating System - {founder_id}")
    if not db_result.get("ok"):
        return db_result
    database_id = db_result["database_id"]
    upsert_company_goal(
        founder_id,
        north_star=company_goal.get("north_star", ""),
        company_goal=company_goal.get("company_goal", ""),
        source_session_id=company_goal.get("source_session_id", ""),
        status=company_goal.get("status", "operating"),
        kpis=company_goal.get("kpis") or [],
        notion_database_id=database_id,
        notion_url=db_result.get("url"),
    )

    goal_row = _upsert_page(
        token,
        database_id,
        title=company_goal.get("company_goal", "Company Goal"),
        astra_id=f"company_goal:{founder_id}",
        row_type="company_goal",
        status=company_goal.get("status", "operating"),
        owner="astra",
        parent_astra_id="",
        source_session_id=company_goal.get("source_session_id", ""),
        notes=company_goal.get("north_star", ""),
    )
    if not goal_row.get("ok"):
        return goal_row

    missions = list_missions(founder_id)
    synced = {"missions": 0, "tasks": 0}
    for mission in missions:
        mission_row = _upsert_page(
            token,
            database_id,
            title=mission.get("name", "Mission"),
            astra_id=f"mission:{mission['id']}",
            row_type="mission",
            status=mission.get("status", "active"),
            owner=mission.get("department", ""),
            parent_astra_id=f"company_goal:{founder_id}",
            source_session_id=company_goal.get("source_session_id", ""),
            notes=mission.get("goal", ""),
        )
        if mission_row.get("ok"):
            synced["missions"] += 1
            try:
                update_mission(
                    mission["id"],
                    notion_page_id=mission_row.get("page_id"),
                    notion_page_url=mission_row.get("url"),
                )
            except Exception:
                logger.debug("notion sync: unable to persist mission page metadata", exc_info=True)
        for task in mission.get("tasks") or []:
            task_row = _upsert_page(
                token,
                database_id,
                title=task.get("title", "Task"),
                astra_id=f"task:{task['id']}",
                row_type="subtask" if task.get("parent_id") else "task",
                status=task.get("status", "pending"),
                owner=task.get("owner_agent", mission.get("department", "")),
                parent_astra_id=f"task:{task['parent_id']}" if task.get("parent_id") else f"mission:{mission['id']}",
                source_session_id=(task.get("last_run_id") or company_goal.get("source_session_id", "")),
                notes=task.get("notes", ""),
            )
            if task_row.get("ok"):
                synced["tasks"] += 1
                try:
                    update_task(
                        mission["id"],
                        task["id"],
                        notion_page_id=task_row.get("page_id"),
                        notion_page_url=task_row.get("url"),
                    )
                except Exception:
                    logger.debug("notion sync: unable to persist task page metadata", exc_info=True)

    return {
        "ok": True,
        "database_id": database_id,
        "url": db_result.get("url"),
        "company_goal_page_id": goal_row.get("page_id"),
        "synced": synced,
    }
