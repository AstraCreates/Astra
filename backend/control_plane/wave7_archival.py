"""Wave 7 archival snapshot and legacy-retirement helpers."""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LEGACY_DELETE_LAST_TARGETS: tuple[dict[str, str], ...] = (
    {"key": "process_local_approval_waiters", "path": ".astra/approvals", "kind": "dir"},
    {"key": "shared_sse_queues", "path": ".astra/workflows", "kind": "dir"},
    {"key": "legacy_redis_lists", "path": ".astra/run_ledger", "kind": "dir"},
    {"key": "json_approval_workflow_ledgers", "path": ".astra/storage_mirror/approval_workflows", "kind": "dir"},
    {"key": "process_schedulers", "path": "backend/scheduler.py", "kind": "file"},
    {"key": "direct_model_provider_code_paths", "path": "backend/control_plane/gateway.py", "kind": "file"},
    {"key": "recursive_deep_research_synthesis", "path": "backend/deep_research.py", "kind": "file"},
    {"key": "whole_document_company_brain_relationship_rebuilds", "path": "backend/tools/graph_rag_ingest.py", "kind": "file"},
)

ARCHIVE_SNAPSHOT_TARGETS: tuple[dict[str, str], ...] = (
    {"key": "workflows", "path": ".astra/workflows"},
    {"key": "approvals", "path": ".astra/approvals"},
    {"key": "run_ledger", "path": ".astra/run_ledger"},
    {"key": "anomalies", "path": ".astra/control_plane_anomalies"},
    {"key": "production_verification", "path": ".astra/production_verification"},
    {"key": "production_launch", "path": ".astra/production_launch"},
    {"key": "company_brain", "path": ".astra/company_brain"},
    {"key": "storage_mirror", "path": ".astra/storage_mirror"},
)


def export_wave7_archival_snapshot(*, output_path: str | None = None) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    output = Path(output_path or f".astra/archives/wave7-{now.strftime('%Y%m%dT%H%M%SZ')}.zip")
    output.parent.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {
        "created_at": now.isoformat(),
        "targets": [],
    }

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for target in ARCHIVE_SNAPSHOT_TARGETS:
            root = Path(target["path"])
            included = []
            if root.is_dir():
                for path in sorted(root.rglob("*")):
                    if not path.is_file():
                        continue
                    arcname = f"{target['key']}/{path.relative_to(root)}"
                    archive.write(path, arcname=arcname)
                    included.append(arcname)
            elif root.is_file():
                arcname = f"{target['key']}/{root.name}"
                archive.write(root, arcname=arcname)
                included.append(arcname)
            manifest["targets"].append({
                "key": target["key"],
                "source": target["path"],
                "included": included,
            })
        archive.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))

    return {
        "ok": True,
        "path": str(output),
        "manifest": manifest,
    }


def build_legacy_retirement_manifest() -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for target in LEGACY_DELETE_LAST_TARGETS:
        path = Path(target["path"])
        exists = path.exists()
        entries = 0
        if path.is_dir():
            entries = sum(1 for item in path.rglob("*") if item.is_file())
        elif path.is_file():
            entries = 1
        items.append({
            "key": target["key"],
            "path": target["path"],
            "kind": target["kind"],
            "exists": exists,
            "entries": entries,
            "retirement_ready": not exists or entries == 0,
        })
    ready = all(item["retirement_ready"] for item in items)
    return {
        "ok": True,
        "ready_for_delete_last": ready,
        "items": items,
    }
