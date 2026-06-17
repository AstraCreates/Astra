import logging
import requests

from backend.config import settings

logger = logging.getLogger(__name__)


def send_email_campaign(
    to_email: str,
    from_name: str,
    from_email: str,
    subject: str,
    body_html: str,
    body_text: str = "",
) -> dict:
    """Send a single email via SendGrid. Falls back to logging if no API key."""
    api_key = getattr(settings, "sendgrid_api_key", None)

    if not api_key:
        logger.info("SendGrid not configured — email queued: %s → %s", subject, to_email)
        return {
            "sent": False,
            "queued": True,
            "note": "SENDGRID_API_KEY not set. Email content generated — set key to auto-send.",
            "preview": {"to": to_email, "subject": subject, "body_preview": body_text[:200]},
        }

    payload = {
        "personalizations": [{"to": [{"email": to_email}]}],
        "from": {"email": from_email, "name": from_name},
        "subject": subject,
        "content": [
            {"type": "text/plain", "value": body_text or body_html},
            {"type": "text/html", "value": body_html},
        ],
    }
    try:
        resp = requests.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=10,
        )
        if resp.status_code in (200, 202):
            return {"sent": True, "to": to_email, "subject": subject}
        err = resp.text
        if "Sender Identity" in err or "verified" in err.lower():
            logger.warning("SendGrid unverified sender — email queued locally")
            return {
                "sent": False,
                "queued": True,
                "note": "SendGrid sender not verified. Email content saved — verify sender at sendgrid.com/settings/sender_auth.",
                "preview": {"to": to_email, "subject": subject},
            }
        return {"sent": False, "error": err[:300], "status_code": resp.status_code}
    except Exception as e:
        logger.error("send_email_campaign failed: %s", e)
        return {"sent": False, "error": str(e)}


def build_email_html(
    subject: str = "",
    body_paragraphs: list[str] | None = None,
    cta_text: str = "",
    cta_url: str = "",
    brand_color: str = "#000000",
    sender_name: str = "",
) -> str:
    from backend.tools._arg_utils import parse_list_arg
    if not subject:
        return "<p>Error: subject is required for build_email_html</p>"
    body_paragraphs = parse_list_arg(body_paragraphs, "body_paragraphs") or []
    paras = "".join(f"<p style='margin:0 0 16px'>{p}</p>" for p in body_paragraphs)
    cta_block = ""
    if cta_text and cta_url:
        cta_block = (
            f"<p style='margin:24px 0'>"
            f"<a href='{cta_url}' style='background:{brand_color};color:#fff;padding:12px 28px;"
            f"border-radius:6px;text-decoration:none;font-weight:600'>{cta_text}</a></p>"
        )
    footer_text = f"Sent by {sender_name}." if sender_name else "Sent via email."
    return f"""
<div style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;max-width:580px;margin:0 auto;padding:40px 24px">
  <h2 style="font-size:1.5rem;margin:0 0 20px;font-weight:700">{subject}</h2>
  {paras}
  {cta_block}
  <hr style="border:none;border-top:1px solid #eee;margin:32px 0"/>
  <p style="color:#999;font-size:.8rem">{footer_text}</p>
</div>
"""
