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
_OUTBOX_MAX_ATTEMPTS = 5
_STREAM_MAX_AGE_MS = 1000 * 60 * 60 * 24


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


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _record_outbox_failure(outbox_id: int, row: dict[str, Any], error: str) -> None:
    from backend.db.client import get_supabase

    attempts = int(row.get("attempts") or 0) + 1
    patch: dict[str, Any] = {
        "attempts": attempts,
        "last_error": error[:2000],
    }
    if attempts >= _OUTBOX_MAX_ATTEMPTS:
        patch["dead_lettered_at"] = _utc_now()
    (
        get_supabase().table("astra_outbox")
        .update(patch)
        .eq("id", outbox_id)
        .execute()
    )


def _trim_stream(redis_client: Any, key: str) -> None:
    try:
        min_timestamp_ms = max(0, int(time.time() * 1000) - _STREAM_MAX_AGE_MS)
        redis_client.xtrim(key, minid=f"{min_timestamp_ms}-0", approximate=True)
    except Exception:
        pass


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
        .select("id,run_id,event_sequence,payload,attempts,last_error")
        .is_("published_at", "null")
        .is_("dead_lettered_at", "null")
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
            error = "run lookup produced no org_id; cannot publish stream event"
            _record_outbox_failure(outbox_id, row, error)
            attempts = int(row.get("attempts") or 0) + 1
            if attempts >= _OUTBOX_MAX_ATTEMPTS:
                logger.error(
                    "Redis stream publish dead-lettered outbox_id=%s run_id=%s attempts=%s error=%s",
                    outbox_id, run_id, attempts, error,
                )
            else:
                logger.warning(
                    "Redis stream publish deferred for outbox_id=%s run_id=%s attempt=%s: %s",
                    outbox_id, run_id, attempts, error,
                )
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
            _trim_stream(redis_client, key)
        except Exception as exc:
            if "equal or smaller" not in str(exc).lower():
                attempts = int(row.get("attempts") or 0) + 1
                _record_outbox_failure(outbox_id, row, str(exc))
                if attempts >= _OUTBOX_MAX_ATTEMPTS:
                    logger.error(
                        "Redis stream publish dead-lettered outbox_id=%s run_id=%s attempts=%s error=%s",
                        outbox_id, run_id, attempts, exc,
                    )
                else:
                    logger.warning(
                        "Redis stream publish failed for outbox_id=%s run_id=%s attempt=%s: %s",
                        outbox_id, run_id, attempts, exc,
                    )
                continue
        (
            get_supabase().table("astra_outbox")
            .update({"published_at": _utc_now(), "attempts": int(row.get("attempts") or 0) + 1, "last_error": None})
            .eq("id", outbox_id)
            .execute()
        )
        (
            get_supabase().table("astra_run_events")
            .update({"published_at": _utc_now()})
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
                sequence = _parse_stream_sequence(stream_event_id)
                raw_payload = fields.get("payload") if isinstance(fields, dict) else None
                if raw_payload is None:
                    cursor = str(stream_event_id)
                    latest_sequence = max(latest_sequence, sequence)
                    continue
                try:
                    payload_wrapper = json.loads(raw_payload)
                except Exception as exc:
                    logger.warning("Malformed Redis stream payload for run=%s stream_id=%s: %s", run_id, stream_event_id, exc)
                    cursor = str(stream_event_id)
                    replay = await list_run_events(run_id, latest_sequence)
                    for event in replay:
                        latest_sequence = max(latest_sequence, int(event.get("sequence") or 0))
                        payload = dict(event.get("payload") or {})
                        payload.setdefault("type", event.get("event_type") or "")
                        yield _fmt_sse(int(event.get("sequence") or 0), payload)
                    continue
                payload = dict(payload_wrapper.get("payload") or {})
                payload.setdefault("type", payload_wrapper.get("event_type") or "")
                sequence = int(payload_wrapper.get("sequence") or sequence)
                cursor = str(stream_event_id)
                latest_sequence = max(latest_sequence, sequence)
                yield _fmt_sse(sequence, payload)
