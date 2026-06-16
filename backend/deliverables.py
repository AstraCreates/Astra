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
    search_dirs = [Path(vault) / "files", Path(vault)]
    for d in search_dirs:
        candidate = d / safe_name
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


# Keys that hold a generated-file path, wherever they appear in the (possibly
# nested) result dict — agents often wrap their output under one key, e.g.
# {"competitor_report": {"summary": ..., "pdf_path": ...}}.
_PATH_KEYS = {"pdfs", "pdf_path", "path", "file_path", "output_path"}


def collect_result_attachment_paths(result: dict[str, Any]) -> list[Path]:
    """Recursively find every generated-file path in a run's result dict
    (regardless of nesting depth) and resolve each to an on-disk Path."""
    found: list[str] = []

    def _walk(d: dict[str, Any]) -> None:
        for k, v in d.items():
            if k in _PATH_KEYS:
                if isinstance(v, list):
                    found.extend(str(x) for x in v)
                elif v:
                    found.append(str(v))
            elif isinstance(v, dict):
                _walk(v)

    _walk(result or {})
    resolved: list[Path] = []
    seen: set[str] = set()
    for raw in found:
        path = resolve_deliverable_path(raw)
        if path is not None and str(path) not in seen:
            seen.add(str(path))
            resolved.append(path)
    return resolved


def _find_summary(result: dict[str, Any]) -> str:
    """Find the first usable summary string, checking the top-level result
    then each nested dict in turn — without merging sections together, since
    that silently drops same-named fields from whichever section loses."""
    for k in _SUMMARY_KEYS:
        if result.get(k):
            return str(result[k])
    for v in result.values():
        if isinstance(v, dict):
            for k in _SUMMARY_KEYS:
                if v.get(k):
                    return str(v[k])
    return ""


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
_SUMMARY_KEYS = ("summary", "description", "overview")


def _humanize_key(key: str) -> str:
    return key.replace("_", " ").strip().capitalize()


def _humanize_list_item(item: Any) -> str:
    """A list entry that's itself a dict (e.g. a competitor record) shouldn't
    render as a raw Python repr — pick its most identifying fields instead."""
    if not isinstance(item, dict):
        return str(item)
    name = item.get("name") or item.get("title") or item.get("label")
    tag = item.get("threat_level") or item.get("tier") or item.get("price")
    if name:
        return f"{name} ({tag})" if tag else str(name)
    return ", ".join(f"{k}: {v}" for k, v in list(item.items())[:3])


def _humanize_value(value: Any) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (list, tuple)):
        if not value:
            return "—"
        shown = ", ".join(_humanize_list_item(v) for v in value[:12])
        return shown + ("…" if len(value) > 12 else "")
    if isinstance(value, dict):
        parts = []
        for k, v in list(value.items())[:6]:
            v_str = _humanize_value(v) if isinstance(v, (list, tuple, dict)) else str(v)
            parts.append(f"{_humanize_key(k)}: {v_str}")
        return ", ".join(parts) or "—"
    text = str(value).strip()
    return (text[:800] + "…") if len(text) > 800 else (text or "—")


def _result_rows_html(d: dict[str, Any]) -> str:
    rows = ""
    for k, v in d.items():
        if k in _SKIP_RESULT_KEYS or k in _SUMMARY_KEYS or v in (None, "", [], {}):
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
    return (
        f"<table role='presentation' width='100%' cellpadding='0' cellspacing='0' style='margin-top:8px'>{rows}</table>"
        if rows else ""
    )


def _render_section(label: str, d: dict[str, Any], *, heading: bool) -> str:
    """Render one dict (top-level result, or a nested wrapper like
    "competitor_report") as its own block: a featured summary paragraph
    followed by a key/value table — never merged with any sibling dict, so
    fields with the same name in two different sections don't clobber each other."""
    summary_text = next((d.get(k) for k in _SUMMARY_KEYS if d.get(k)), "")
    summary_html = (
        f"<p style='margin:{'8px' if heading else '14px'} 0 0;color:#374151;font-size:14px;line-height:1.7'>"
        f"{_humanize_value(summary_text)}</p>"
        if summary_text else ""
    )
    rows_html = _result_rows_html(d)
    body = summary_html + rows_html
    if not body:
        return ""
    if not heading:
        return body
    return (
        "<div style='margin-top:22px;padding-top:16px;border-top:1px solid #EEF1F6'>"
        f"<div style='font-size:13px;font-weight:700;color:#1A1F2B;margin-bottom:2px'>{label}</div>"
        f"{body}</div>"
    )


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

    result = result or {}

    error_text = result.get("error") or next(
        (v.get("error") for v in result.values() if isinstance(v, dict) and v.get("error")), None
    )
    error_block = ""
    if not is_done and error_text:
        error_block = (
            "<div style='margin-top:14px;padding:12px 14px;border-radius:10px;"
            "background:rgba(192,57,43,0.06);border:1px solid rgba(192,57,43,0.18);"
            "color:#A93226;font-size:13px;line-height:1.6'>"
            f"{_humanize_value(error_text)}</div>"
        )

    # Render the top-level dict as the lead section (no heading), then every
    # nested dict value as its own clearly labeled section underneath — each
    # section keeps its own fields, so nothing from one section overwrites
    # another's same-named field. Dict-valued keys are excluded from the lead
    # section since they get their own heading section below.
    top_level = {k: v for k, v in result.items() if not isinstance(v, dict)}
    result_table = _render_section("", top_level, heading=False)
    for k, v in result.items():
        if k in _SKIP_RESULT_KEYS or not isinstance(v, dict):
            continue
        result_table += _render_section(_humanize_key(k), v, heading=True)
    if not result_table:
        result_table = "<p style='color:#8A93A6;font-size:13px;margin:8px 0 0'>No structured output was returned.</p>"

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


def _build_subject(agent_label: str, status: str, result: dict[str, Any]) -> str:
    if status != "done":
        return f"⚠ {agent_label} needs attention"
    summary = _find_summary(result or {}).strip()
    if not summary:
        return f"✓ {agent_label} — new results ready"
    snippet = summary.split("\n")[0].split(". ")[0].rstrip(".")
    if snippet.lower().startswith(agent_label.lower()):
        snippet = snippet[len(agent_label):].lstrip(" :-—")
    if len(snippet) > 70:
        snippet = snippet[:70].rsplit(" ", 1)[0] + "…"
    return f"✓ {agent_label}: {snippet}" if snippet else f"✓ {agent_label} — new results ready"


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
    subject = _build_subject(agent_label, status, result)
    return resend_send_email(
        to=to_email,
        from_email="noreply@astracreates.com",
        subject=subject,
        html=html,
        attachment_paths=[str(p) for p in attachment_paths],
    )
