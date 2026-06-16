"""Shared helpers for locating and emailing generated deliverable files
(PDF/TXT outputs from agent tool calls like generate_pdf)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from backend.provisioning.credentials_store import load_credentials
from backend.tools.resend_tools import send_deliverable_email


def resolve_deliverable_path(filename: str) -> Path | None:
    """Safely resolve a deliverable filename to an on-disk path, basename-only
    to prevent path traversal, searched across the known output directories."""
    safe_name = Path(filename).name
    vault = os.environ.get("OBSIDIAN_VAULT", "/tmp/astra_docs")
    search_dirs = [Path(vault) / "files", Path(vault), Path("/tmp/astra_docs")]
    for d in search_dirs:
        candidate = d / safe_name
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def get_founder_notify_email(founder_id: str) -> str:
    """The only reliable real email address on file for a founder: their
    connected Gmail account (from the Integrations OAuth flow)."""
    creds = load_credentials(founder_id, "gmail") or {}
    return str(creds.get("email") or "")


def send_deliverable(founder_id: str, path: Path, label: str = "") -> dict[str, Any]:
    """Email a deliverable file to the founder from Astra's no-reply address.
    Returns {"sent": False, "skipped": "<reason>"} if there's no email on file."""
    to_email = get_founder_notify_email(founder_id)
    if not to_email:
        return {"sent": False, "skipped": "no_email_on_file"}
    return send_deliverable_email(to_email, label or path.name, str(path))
