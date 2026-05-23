import asyncio
from datetime import datetime, timezone
from typing import Optional

from supabase import create_client, Client

from backend.config import settings

_client: Optional[Client] = None


def get_supabase() -> Client:
    global _client
    if _client is None:
        _client = create_client(settings.supabase_url, settings.supabase_key)
    return _client


async def get_ready_tasks(goal_id: str) -> list[dict]:
    def _query():
        return get_supabase().table("tasks").select("*").eq("goal_id", goal_id).execute().data

    all_tasks = await asyncio.to_thread(_query)
    done_ids = {t["id"] for t in all_tasks if t["status"] == "done"}
    return [
        t for t in all_tasks
        if t["status"] == "pending"
        and all(dep in done_ids for dep in t["depends_on"])
    ]


async def has_in_progress_tasks(goal_id: str) -> bool:
    def _query():
        return get_supabase().table("tasks").select("id").eq("goal_id", goal_id).eq("status", "in_progress").execute().data

    result = await asyncio.to_thread(_query)
    return len(result) > 0


async def persist_goal(goal_id: str, founder_id: str, instruction: str, constraints: dict):
    def _insert():
        get_supabase().table("goals").insert({
            "id": goal_id,
            "founder_id": founder_id,
            "instruction": instruction,
            "constraints": constraints,
            "status": "pending",
        }).execute()

    await asyncio.to_thread(_insert)


async def persist_task_graph(goal_id: str, founder_id: str, tasks: list[dict]):
    def _insert():
        rows = [
            {
                "id": t["task_id"],
                "goal_id": goal_id,
                "founder_id": founder_id,
                "agent": t["agent"],
                "instruction": t.get("instruction", ""),
                "depends_on": t.get("depends_on", []),
                "tools_available": t.get("tools_available", []),
                "constraints": t.get("constraints", {}),
                "context_bundle": t.get("context_bundle", {}),
                "status": "pending",
            }
            for t in tasks
        ]
        get_supabase().table("tasks").insert(rows).execute()

    await asyncio.to_thread(_insert)


async def update_task_status(task_id: str, status: str, result: Optional[dict] = None):
    def _update():
        payload: dict = {"status": status}
        if result is not None:
            payload["result"] = result
        if status in ("done", "failed", "awaiting_approval"):
            payload["completed_at"] = datetime.now(timezone.utc).isoformat()
        get_supabase().table("tasks").update(payload).eq("id", task_id).execute()

    await asyncio.to_thread(_update)


async def store_memory_document(doc: dict):
    def _insert():
        get_supabase().table("memory_documents").insert(doc).execute()

    await asyncio.to_thread(_insert)


async def update_goal_status(goal_id: str, status: str, elapsed_seconds: Optional[float] = None):
    def _update():
        payload: dict = {"status": status}
        if elapsed_seconds is not None:
            payload["elapsed_seconds"] = elapsed_seconds
        if status == "done":
            payload["completed_at"] = datetime.now(timezone.utc).isoformat()
        get_supabase().table("goals").update(payload).eq("id", goal_id).execute()

    await asyncio.to_thread(_update)
