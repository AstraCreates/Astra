from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncIterator

from backend.control_plane.projection import list_run_events
from backend.control_plane.supabase_repositories import SupabaseRunRepository

logger = logging.getLogger(__name__)

_STREAM_MAXLEN = 5000
_STREAM_BLOCK_MS = 30000


def _fmt_sse(sequence: int, payload: dict[str, Any]) -> str:
    return f"id: {sequence}\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"


def _stream_key(org_id: str, run_id: str) -> str:
    return f"events:{org_id}:{run_id}"


def _stream_id(sequence: int) -> str:
    return f"{max(1, int(sequence))}-0"


def _parse_stream_sequence(stream_id: str) -> int:
    try:
        return int(str(stream_id).split("-", 1)[0])
    except Exception:
        return 0


async def publish_outbox_batch(limit: int = 100) -> int:
    return await asyncio.to_thread(_publish_outbox_batch_sync, limit)


def _publish_outbox_batch_sync(limit: int = 100) -> int:
    from backend.core.events import _redis
    from backend.db.client import get_supabase

    redis_client = _redis()
    if redis_client is None:
        return 0

    rows = (
        get_supabase().table("astra_outbox")
        .select("id,run_id,event_sequence,payload,attempts")
        .is_("published_at", "null")
        .order("created_at")
        .limit(limit)
        .execute()
        .data
    )
    run_repo = SupabaseRunRepository()
    published = 0
    for row in rows:
        outbox_id = int(row["id"])
        run_id = str(row["run_id"])
        event_sequence = int(row["event_sequence"])
        payload = row.get("payload") or {}
        run = run_repo.get(run_id)
        org_id = str((run.org_id if run else "") or "")
        if not org_id:
            continue
        key = _stream_key(org_id, run_id)
        try:
            redis_client.xadd(
                key,
                {"payload": json.dumps(payload, separators=(",", ":"))},
                id=_stream_id(event_sequence),
                maxlen=_STREAM_MAXLEN,
                approximate=True,
            )
        except Exception as exc:
            if "equal or smaller" not in str(exc).lower():
                logger.warning("Redis stream publish failed for outbox_id=%s run_id=%s: %s", outbox_id, run_id, exc)
                continue
        (
            get_supabase().table("astra_outbox")
            .update({"published_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "attempts": int(row.get("attempts") or 0) + 1})
            .eq("id", outbox_id)
            .execute()
        )
        (
            get_supabase().table("astra_run_events")
            .update({"published_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
            .eq("run_id", run_id)
            .eq("sequence", event_sequence)
            .execute()
        )
        published += 1
    return published


async def outbox_publisher_loop(poll_seconds: float = 1.0) -> None:
    await asyncio.sleep(2)
    while True:
        try:
            await publish_outbox_batch()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Outbox publisher loop failed: %s", exc)
        await asyncio.sleep(poll_seconds)


async def stream_run_events(run_id: str, *, last_event_id: int | None = None) -> AsyncIterator[str]:
    run = await asyncio.to_thread(SupabaseRunRepository().get, run_id)
    if run is None:
        yield _fmt_sse(0, {"type": "session_expired"})
        return

    after_sequence = int(last_event_id or 0)
    replay = await list_run_events(run_id, after_sequence)
    latest_sequence = after_sequence
    for event in replay:
        latest_sequence = max(latest_sequence, int(event.get("sequence") or 0))
        payload = dict(event.get("payload") or {})
        payload.setdefault("type", event.get("event_type") or "")
        yield _fmt_sse(int(event.get("sequence") or 0), payload)

    if str(run.status) in {"cancelled", "succeeded", "failed"}:
        return

    from backend.core.events import _redis

    redis_client = _redis()
    if redis_client is None:
        while True:
            await asyncio.sleep(1)
            current_run = await asyncio.to_thread(SupabaseRunRepository().get, run_id)
            if current_run is None:
                return
            replay = await list_run_events(run_id, latest_sequence)
            for event in replay:
                latest_sequence = max(latest_sequence, int(event.get("sequence") or 0))
                payload = dict(event.get("payload") or {})
                payload.setdefault("type", event.get("event_type") or "")
                yield _fmt_sse(int(event.get("sequence") or 0), payload)
            if str(current_run.status) in {"cancelled", "succeeded", "failed"}:
                return

    key = _stream_key(run.org_id, run_id)
    cursor = _stream_id(latest_sequence) if latest_sequence else "0-0"
    while True:
        try:
            response = await asyncio.to_thread(
                redis_client.xread,
                {key: cursor},
                count=None,
                block=_STREAM_BLOCK_MS,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Redis XREAD failed for run=%s: %s", run_id, exc)
            response = []
        if not response:
            current_run = await asyncio.to_thread(SupabaseRunRepository().get, run_id)
            if current_run is None or str(current_run.status) in {"cancelled", "succeeded", "failed"}:
                replay = await list_run_events(run_id, latest_sequence)
                for event in replay:
                    latest_sequence = max(latest_sequence, int(event.get("sequence") or 0))
                    payload = dict(event.get("payload") or {})
                    payload.setdefault("type", event.get("event_type") or "")
                    yield _fmt_sse(int(event.get("sequence") or 0), payload)
                return
            yield 'data: {"type":"ping"}\n\n'
            continue
        for _stream_name, entries in response:
            for stream_event_id, fields in entries:
                cursor = str(stream_event_id)
                sequence = _parse_stream_sequence(stream_event_id)
                latest_sequence = max(latest_sequence, sequence)
                raw_payload = fields.get("payload") if isinstance(fields, dict) else None
                if raw_payload is None:
                    continue
                try:
                    payload_wrapper = json.loads(raw_payload)
                except Exception:
                    continue
                payload = dict(payload_wrapper.get("payload") or {})
                payload.setdefault("type", payload_wrapper.get("event_type") or "")
                sequence = int(payload_wrapper.get("sequence") or sequence)
                latest_sequence = max(latest_sequence, sequence)
                yield _fmt_sse(sequence, payload)
