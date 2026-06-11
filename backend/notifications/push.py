"""Send Web Push notifications via pywebpush + VAPID."""
from __future__ import annotations
import json
import logging
import os
import threading

logger = logging.getLogger(__name__)

_VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")
_VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
_VAPID_CLAIMS = {"sub": "mailto:hello@astrafounder.com"}


def send_push(subscription: dict, title: str, body: str, url: str = "/") -> bool:
    """Send a single Web Push notification. Returns True on success."""
    if not (_VAPID_PUBLIC_KEY and _VAPID_PRIVATE_KEY):
        logger.debug("VAPID keys not configured — skipping push")
        return False
    try:
        from pywebpush import webpush, WebPushException
        payload = json.dumps({"title": title, "body": body, "url": url})
        webpush(
            subscription_info=subscription,
            data=payload,
            vapid_private_key=_VAPID_PRIVATE_KEY,
            vapid_claims=_VAPID_CLAIMS,
        )
        return True
    except Exception as exc:
        logger.warning("push.send_push failed: %s", exc)
        return False


def notify_founder(founder_id: str, title: str, body: str, url: str = "/") -> None:
    """Load all subscriptions for founder and send push (best-effort, background thread)."""
    def _send():
        from backend.notifications.store import get_subscriptions
        for sub in get_subscriptions(founder_id):
            send_push(sub, title, body, url)
    threading.Thread(target=_send, daemon=True).start()
