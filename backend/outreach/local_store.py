"""Free, file-backed contact/outreach store.

A drop-in replacement for the small slice of the Supabase query API that the
outreach subsystem uses, so the Outreach tab works with zero paid services
(no Supabase, Apollo, or Hunter required).

Data lives in a single JSON document on the persistent volume:
  $OBSIDIAN_VAULT/outreach/store.json
shaped as { "<table>": [ {row}, ... ] }. Tables are global (rows carry a
founder_id column) exactly like the Postgres schema, so the same filters work.

Only the operations actually used by the outreach code are implemented:
  .table(name).select(cols, count=).insert().upsert(on_conflict, ignore_duplicates)
  .update().delete().eq().in_().order(desc=).limit().execute()
execute() returns an object exposing .data (list) and .count (int | None),
matching the Supabase client's result shape.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

_lock = threading.RLock()


def _store_path() -> Path:
    vault = Path(os.environ.get("OBSIDIAN_VAULT", "/tmp/astra_docs"))
    d = vault / "outreach"
    d.mkdir(parents=True, exist_ok=True)
    return d / "store.json"


def _load() -> dict[str, list[dict]]:
    p = _store_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _save(data: dict[str, list[dict]]) -> None:
    tmp = _store_path().with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")))
    tmp.replace(_store_path())


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class _Result:
    def __init__(self, data: list[dict], count: int | None = None):
        self.data = data
        self.count = count


class _Query:
    def __init__(self, table: str):
        self.table = table
        self._filters: list[tuple[str, str, Any]] = []  # (op, col, val)
        self._op = "select"
        self._payload: Any = None
        self._cols = "*"
        self._count = False
        self._order: tuple[str, bool] | None = None
        self._limit: int | None = None
        self._range: tuple[int, int] | None = None
        self._on_conflict: list[str] | None = None
        self._ignore_dupes = False

    # ── builders ───────────────────────────────────────────────────────────
    def select(self, cols: str = "*", count: str | None = None) -> "_Query":
        self._op = "select"
        self._cols = cols
        self._count = count == "exact"
        return self

    def insert(self, rows: Any) -> "_Query":
        self._op = "insert"
        self._payload = rows
        return self

    def upsert(self, rows: Any, on_conflict: str | None = None, ignore_duplicates: bool = False) -> "_Query":
        self._op = "upsert"
        self._payload = rows
        self._on_conflict = [c.strip() for c in on_conflict.split(",")] if on_conflict else None
        self._ignore_dupes = ignore_duplicates
        return self

    def update(self, values: dict) -> "_Query":
        self._op = "update"
        self._payload = values
        return self

    def delete(self) -> "_Query":
        self._op = "delete"
        return self

    def eq(self, col: str, val: Any) -> "_Query":
        self._filters.append(("eq", col, val))
        return self

    def in_(self, col: str, vals: list) -> "_Query":
        self._filters.append(("in", col, list(vals)))
        return self

    def order(self, col: str, desc: bool = False) -> "_Query":
        self._order = (col, desc)
        return self

    def limit(self, n: int) -> "_Query":
        self._limit = n
        return self

    def range(self, start: int, end: int) -> "_Query":
        # Supabase range is inclusive on both ends.
        self._range = (start, end)
        return self

    # ── matching ───────────────────────────────────────────────────────────
    def _matches(self, row: dict) -> bool:
        for op, col, val in self._filters:
            if op == "eq" and row.get(col) != val:
                return False
            if op == "in" and row.get(col) not in val:
                return False
        return True

    def _conflict_key(self, row: dict) -> tuple:
        return tuple(row.get(c) for c in (self._on_conflict or []))

    # ── execution ──────────────────────────────────────────────────────────
    def execute(self) -> _Result:
        with _lock:
            data = _load()
            rows = data.setdefault(self.table, [])

            if self._op == "select":
                matched = [dict(r) for r in rows if self._matches(r)]
                if self._order:
                    col, desc = self._order
                    matched.sort(key=lambda r: (r.get(col) is None, r.get(col)), reverse=desc)
                total = len(matched)
                if self._range is not None:
                    start, end = self._range
                    matched = matched[start : end + 1]
                elif self._limit is not None:
                    matched = matched[: self._limit]
                matched = [self._project(r, data) for r in matched]
                return _Result(matched, count=total if self._count else None)

            if self._op in ("insert", "upsert"):
                payload = self._payload if isinstance(self._payload, list) else [self._payload]
                out: list[dict] = []
                for raw in payload:
                    row = dict(raw)
                    row.setdefault("id", str(uuid.uuid4()))
                    row.setdefault("created_at", _now())
                    if self._op == "upsert" and self._on_conflict:
                        key = self._conflict_key(row)
                        existing = next((r for r in rows if tuple(r.get(c) for c in self._on_conflict) == key), None)
                        if existing is not None:
                            if not self._ignore_dupes:
                                existing.update({k: v for k, v in row.items() if k not in ("id", "created_at")})
                            out.append(dict(existing))
                            continue
                    rows.append(row)
                    out.append(dict(row))
                _save(data)
                return _Result(out)

            if self._op == "update":
                changed: list[dict] = []
                for r in rows:
                    if self._matches(r):
                        r.update(self._payload)
                        changed.append(dict(r))
                _save(data)
                return _Result(changed)

            if self._op == "delete":
                kept = [r for r in rows if not self._matches(r)]
                removed = [r for r in rows if self._matches(r)]
                data[self.table] = kept
                _save(data)
                return _Result(removed)

        return _Result([])

    def _project(self, row: dict, data: dict) -> dict:
        """Handle the one nested-join select used by get_campaign_contacts:
        'outreach_contacts(first_name, last_name, email, company_name, title)'.
        """
        if "outreach_contacts(" not in self._cols:
            return row
        contacts = data.get("outreach_contacts", [])
        c = next((x for x in contacts if x.get("id") == row.get("contact_id")), None)
        row["outreach_contacts"] = (
            {k: c.get(k) for k in ("first_name", "last_name", "email", "company_name", "title")}
            if c else None
        )
        return row


class LocalSupabase:
    """Minimal Supabase-client stand-in scoped to outreach tables."""

    def table(self, name: str) -> _Query:
        return _Query(name)


_instance: LocalSupabase | None = None


def get_local_store() -> LocalSupabase:
    global _instance
    if _instance is None:
        _instance = LocalSupabase()
    return _instance
