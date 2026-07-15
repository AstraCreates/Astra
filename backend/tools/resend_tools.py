"""Resend email tools — transactional email for user projects (not Astra itself)."""
import asyncio
import hashlib
import logging
import threading
from typing import Any

import requests
from backend.config import settings

logger = logging.getLogger(__name__)
_API = "https://api.resend.com"


# ── Durable idempotency for resend_send_email ───────────────────────────────
# PLAN.md invariant: "Every external side effect has an idempotency key and
# durable receipt before Temporal retries are enabled." Same reasoning/pattern
# as backend/tools/stripe_tools.py's _execute_with_idempotency: Resend's send
# endpoint accepts a native Idempotency-Key header, layered on top of Astra's
# own durable action/receipt tracking so retries are safe whether run_id is
# available or not.
def _run_async(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    box: dict = {}

    def _runner() -> None:
        try:
            box["result"] = asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001 - re-raised on the caller's thread below
            box["error"] = exc

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join()
    if "error" in box:
        raise box["error"]
    return box["result"]


def _send_with_idempotency(*, run_id: str, step_id: str, args: dict[str, Any], http_call) -> dict:
    """Route the Resend send through Astra's durable action/receipt control
    plane AND pass the computed idempotency key as Resend's own
    Idempotency-Key header. With no run_id, we can't key a durable Astra
    receipt to anything, so we fall back to a content-derived key sent only
    to Resend -- still protects against exact-duplicate resubmission within
    Resend's own idempotency window."""
    from backend.control_plane.action_executor import canonicalize_tool_args

    if not run_id:
        fallback_key = hashlib.sha256(canonicalize_tool_args(args).encode("utf-8")).hexdigest()
        return http_call(fallback_key)

    from backend.control_plane.action_executor import (
        ExternalActionRequest,
        execute_external_action,
        get_default_repo_bundle,
    )

    canonical_args = canonicalize_tool_args(args)
    action_id = hashlib.sha256(f"{run_id}::{step_id}::resend_send_email::{canonical_args}".encode("utf-8")).hexdigest()
    bundle = get_default_repo_bundle()

    async def _effect(_effect_args: dict, idempotency_key: str) -> dict:
        return http_call(idempotency_key)

    result = _run_async(execute_external_action(
        ExternalActionRequest(
            run_id=run_id,
            step_id=step_id or "resend_send_email",
            action_id=action_id,
            tool="resend_send_email",
            args=args,
        ),
        action_repo=bundle.action_repo,
        receipt_repo=bundle.receipt_repo,
        approval_repo=bundle.approval_repo,
        execute_effect=_effect,
    ))
    return dict(result.provider_result or {})


def resend_send_email(
    to: str, from_email: str, subject: str, html: str, text: str = "",
    attachment_path: str = "", attachment_paths: list[str] | None = None,
    *, run_id: str = "", step_id: str = "",
) -> dict:
    """Send transactional email via Resend. Requires RESEND_API_KEY in founder's env.

    run_id/step_id are optional and, when provided by the caller, route the
    send through Astra's durable action/receipt idempotency layer so a
    Temporal activity retry replays the stored result instead of re-sending
    to the real recipient."""
    api_key = getattr(settings, "resend_api_key", "")
    if not api_key:
        return {
            "sent": False,
            "queued": True,
            "note": "RESEND_API_KEY not set — email content generated, set key to send",
            "preview": {"to": to, "subject": subject, "body": html[:300]},
        }
    payload: dict = {"from": from_email, "to": [to], "subject": subject, "html": html, "text": text or subject}
    paths = list(attachment_paths or [])
    if attachment_path:
        paths.append(attachment_path)
    if paths:
        import base64
        import os
        attachments = []
        for p in paths:
            if not os.path.isfile(p):
                return {"error": f"Attachment not found: {p}", "sent": False}
            with open(p, "rb") as f:
                content = base64.b64encode(f.read()).decode()
            attachments.append({"filename": os.path.basename(p), "content": content})
        payload["attachments"] = attachments

    def _post(idempotency_key: str) -> dict:
        try:
            resp = requests.post(
                f"{_API}/emails",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "Idempotency-Key": idempotency_key,
                },
                json=payload,
                timeout=20,
            )
            data = resp.json()
            return {"sent": resp.ok, "id": data.get("id"), "status": resp.status_code}
        except Exception as e:
            return {"error": str(e), "sent": False}

    return _send_with_idempotency(
        run_id=run_id, step_id=step_id,
        args={"to": to, "from_email": from_email, "subject": subject, "html": html, "text": text, "paths": paths},
        http_call=_post,
    )


def send_deliverable_email(to: str, label: str, attachment_path: str) -> dict:
    """Email a generated deliverable (PDF/TXT) to a founder from Astra's no-reply address."""
    html = (
        f"<div style='font-family:sans-serif;max-width:580px;margin:auto;padding:40px 24px'>"
        f"<h2 style='margin:0 0 16px'>Your deliverable is ready</h2>"
        f"<p style='color:#555'>Attached is <b>{label}</b>, generated by your Astra agent.</p>"
        f"</div>"
    )
    return resend_send_email(
        to=to,
        from_email="noreply@astracreates.com",
        subject=f"Your deliverable: {label}",
        html=html,
        attachment_path=attachment_path,
    )


def resend_generate_integration(app_name: str, from_domain: str) -> dict:
    """
    Generate Resend integration code for a user's Next.js/Node app.
    Returns install command, env vars, and ready-to-use send function.
    """
    return {
        "app": app_name,
        "install": "npm install resend",
        "env_vars": {"RESEND_API_KEY": "re_your_api_key_here"},
        "setup_code": (
            "import { Resend } from 'resend';\n"
            f"const resend = new Resend(process.env.RESEND_API_KEY);\n\n"
            f"// Send email\n"
            f"const {{ data, error }} = await resend.emails.send({{\n"
            f"  from: 'noreply@{from_domain}',\n"
            f"  to: ['user@example.com'],\n"
            f"  subject: 'Welcome to {app_name}',\n"
            f"  html: '<p>Welcome!</p>',\n"
            f"}});"
        ),
        "welcome_template": (
            f"<div style='font-family:sans-serif;max-width:600px;margin:auto;padding:40px'>\n"
            f"  <h1>Welcome to {app_name}!</h1>\n"
            f"  <p>You're in. Here's what to do next:</p>\n"
            f"  <a href='{{{{dashboard_url}}}}' style='background:#000;color:#fff;padding:12px 24px;border-radius:6px;text-decoration:none'>Open Dashboard</a>\n"
            f"</div>"
        ),
        "dns_records": [
            {"type": "TXT", "host": f"resend._domainkey.{from_domain}", "value": "Add DKIM from Resend dashboard"},
            {"type": "TXT", "host": from_domain, "value": "v=spf1 include:amazonses.com ~all"},
        ],
        "dashboard": "https://resend.com/domains",
    }


def resend_create_email_templates(app_name: str, templates: list[str] = None) -> dict:
    """
    Generate HTML email templates for common transactional flows.
    templates: ['welcome', 'reset_password', 'magic_link', 'invoice', 'trial_ending']
    """
    templates = templates or ["welcome", "magic_link", "reset_password"]
    result = {}
    for t in templates:
        if t == "welcome":
            result[t] = _template(app_name, "Welcome!", "You're all set.", "Go to Dashboard", "{{dashboard_url}}")
        elif t == "magic_link":
            result[t] = _template(app_name, "Your login link", "Click below to sign in — link expires in 10 minutes.", "Sign In", "{{magic_link}}")
        elif t == "reset_password":
            result[t] = _template(app_name, "Reset your password", "Click below to choose a new password.", "Reset Password", "{{reset_url}}")
        elif t == "invoice":
            result[t] = _template(app_name, "Invoice #{{invoice_number}}", "Payment of {{amount}} received.", "View Invoice", "{{invoice_url}}")
        elif t == "trial_ending":
            result[t] = _template(app_name, "Your trial ends in 3 days", "Upgrade to keep access.", "Upgrade Now", "{{upgrade_url}}")
    return {"app": app_name, "templates": result}


def _template(app, subject, body, cta, url):
    return (
        f"<div style='font-family:sans-serif;max-width:580px;margin:auto;padding:40px 24px'>"
        f"<h2 style='margin:0 0 16px'>{subject}</h2>"
        f"<p style='margin:0 0 24px;color:#555'>{body}</p>"
        f"<a href='{url}' style='background:#000;color:#fff;padding:12px 28px;border-radius:6px;text-decoration:none;font-weight:600'>{cta}</a>"
        f"<hr style='margin:32px 0;border:none;border-top:1px solid #eee'/>"
        f"<p style='color:#999;font-size:12px'>Sent by {app}</p>"
        f"</div>"
    )
