"""Shared helpers for locating and emailing generated deliverable files
(PDF/TXT outputs from agent tool calls like generate_pdf)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from backend.provisioning.credentials_store import load_credentials
from backend.tools.resend_tools import resend_send_email, send_deliverable_email


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


# Keys that are either internal plumbing or already rendered as attachments —
# don't repeat them in the human-readable result summary.
_SKIP_RESULT_KEYS = {
    "pdfs", "path", "filename", "pdf_path", "file_path", "output_path",
    "documents", "generated", "error", "ok", "files_preview", "files_in_repo",
}


def _humanize_key(key: str) -> str:
    return key.replace("_", " ").strip().capitalize()


def _humanize_value(value: Any) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value[:8]) or "—"
    if isinstance(value, dict):
        return ", ".join(f"{k}: {v}" for k, v in list(value.items())[:6]) or "—"
    text = str(value).strip()
    return (text[:500] + "…") if len(text) > 500 else (text or "—")


def build_run_email_html(
    *,
    agent_label: str,
    company_name: str,
    status: str,
    result: dict[str, Any],
    attachment_names: list[str],
    session_url: str,
) -> str:
    """A clean, branded HTML email summarizing a finished custom agent run."""
    is_done = status == "done"
    accent = "#3D9E5F" if is_done else "#C0392B"
    badge_bg = "rgba(61,158,95,0.10)" if is_done else "rgba(192,57,43,0.10)"
    status_label = "Completed" if is_done else "Needs attention"

    error_block = ""
    if not is_done and (result or {}).get("error"):
        error_block = (
            "<div style='margin-top:14px;padding:12px 14px;border-radius:10px;"
            "background:rgba(192,57,43,0.06);border:1px solid rgba(192,57,43,0.18);"
            "color:#A93226;font-size:13px;line-height:1.6'>"
            f"{_humanize_value(result.get('error'))}</div>"
        )

    rows = ""
    for k, v in (result or {}).items():
        if k in _SKIP_RESULT_KEYS or v in (None, "", [], {}):
            continue
        rows += (
            f"<tr>"
            f"<td style='padding:10px 0;border-top:1px solid #EEF1F6;color:#6B7280;"
            f"font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.04em;"
            f"vertical-align:top;width:140px'>{_humanize_key(k)}</td>"
            f"<td style='padding:10px 0;border-top:1px solid #EEF1F6;color:#1A1F2B;"
            f"font-size:14px;line-height:1.6'>{_humanize_value(v)}</td>"
            f"</tr>"
        )
    result_table = (
        f"<table role='presentation' width='100%' cellpadding='0' cellspacing='0' "
        f"style='margin-top:8px'>{rows}</table>"
        if rows else
        "<p style='color:#8A93A6;font-size:13px;margin:8px 0 0'>No structured output was returned.</p>"
    )

    attachments_block = ""
    if attachment_names:
        items = "".join(
            f"<li style='padding:8px 0;border-top:1px solid #EEF1F6;color:#1A1F2B;font-size:14px'>"
            f"📄&nbsp; {name}</li>"
            for name in attachment_names
        )
        attachments_block = (
            "<div style='margin-top:28px'>"
            "<div style='font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;"
            "color:#6B7280;margin-bottom:4px'>Attached</div>"
            f"<ul style='list-style:none;margin:0;padding:0'>{items}</ul>"
            "</div>"
        )

    return f"""\
<!DOCTYPE html>
<html>
  <body style="margin:0;padding:32px 16px;background:#F4F6FB;
               font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
      <tr><td align="center">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
               style="max-width:560px;background:#FFFFFF;border-radius:16px;overflow:hidden;
                      box-shadow:0 1px 3px rgba(16,24,40,0.06),0 1px 2px rgba(16,24,40,0.04);">
          <tr>
            <td style="background:#002EFF;background-image:linear-gradient(135deg,#002EFF,#1A4BFF);
                       padding:28px 32px;">
              <div style="color:#FFFFFF;font-size:13px;font-weight:700;letter-spacing:.08em;
                          text-transform:uppercase;opacity:.85">Astra</div>
              <div style="color:#FFFFFF;font-size:20px;font-weight:700;margin-top:6px">{agent_label}</div>
              {f"<div style='color:rgba(255,255,255,0.75);font-size:13px;margin-top:2px'>{company_name}</div>" if company_name else ""}
            </td>
          </tr>
          <tr>
            <td style="padding:28px 32px 8px;">
              <span style="display:inline-block;padding:4px 12px;border-radius:999px;
                          background:{badge_bg};color:{accent};font-size:12px;font-weight:700;
                          letter-spacing:.03em;">{status_label}</span>
            </td>
          </tr>
          <tr>
            <td style="padding:8px 32px 0;">
              {error_block}
              {result_table}
              {attachments_block}
            </td>
          </tr>
          <tr>
            <td style="padding:28px 32px 32px;">
              <a href="{session_url}" style="display:inline-block;background:#002EFF;color:#FFFFFF;
                 font-size:14px;font-weight:600;padding:11px 22px;border-radius:8px;
                 text-decoration:none;">View full run →</a>
            </td>
          </tr>
          <tr>
            <td style="padding:18px 32px;background:#FAFBFD;border-top:1px solid #EEF1F6;">
              <p style="margin:0;color:#9AA3B5;font-size:11px;line-height:1.6;">
                You're receiving this because this agent run completed on Astra.
                This is an automated message — replies aren't monitored.
              </p>
            </td>
          </tr>
        </table>
      </td></tr>
    </table>
  </body>
</html>"""


def send_run_result_email(
    *,
    founder_id: str,
    agent_label: str,
    company_name: str,
    status: str,
    result: dict[str, Any],
    attachment_paths: list[Path],
    session_id: str,
) -> dict[str, Any]:
    """Email the founder a formatted summary of a finished custom agent run,
    with any generated deliverables attached, from Astra's no-reply address."""
    to_email = get_founder_notify_email(founder_id)
    if not to_email:
        return {"sent": False, "skipped": "no_email_on_file"}

    html = build_run_email_html(
        agent_label=agent_label,
        company_name=company_name,
        status=status,
        result=result,
        attachment_names=[p.name for p in attachment_paths],
        session_url=f"https://astracreates.com/s/{session_id}",
    )
    is_done = status == "done"
    subject = f"{'✓' if is_done else '⚠'} {agent_label} {'finished' if is_done else 'needs attention'}"
    return resend_send_email(
        to=to_email,
        from_email="noreply@astracreates.com",
        subject=subject,
        html=html,
        attachment_paths=[str(p) for p in attachment_paths],
    )
