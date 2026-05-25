"""
IMAP reader for auto-verifying accounts during provisioning.
Connects to Gmail, polls for verification emails, returns clickable URLs.
"""
import email as email_lib
import imaplib
import logging
import re
import time

logger = logging.getLogger(__name__)

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993

VERIFICATION_SENDERS = {
    "github": ["github.com", "noreply@github.com"],
    "sendgrid": ["sendgrid.com", "twilio.com", "noreply@sendgrid.com"],
    "composio": ["composio.dev", "composio.io"],
    "vercel": ["vercel.com", "noreply@vercel.com", "team@vercel.com"],
}


def wait_for_verification_url(
    email_address: str,
    imap_password: str,
    service: str,
    timeout: int = 300,
    poll_interval: int = 8,
) -> str | None:
    """
    Poll inbox until a verification email from `service` arrives.
    Returns the verification URL or None on timeout.
    """
    password = imap_password.replace(" ", "")
    senders = VERIFICATION_SENDERS.get(service, [service])
    deadline = time.time() + timeout

    logger.info("Waiting for %s verification email (timeout=%ds)…", service, timeout)

    while time.time() < deadline:
        try:
            url = _check_inbox(email_address, password, senders)
            if url:
                logger.info("Found %s verification URL: %s", service, url[:80])
                return url
        except Exception as e:
            logger.debug("IMAP poll error: %s", e)
        time.sleep(poll_interval)

    logger.warning("Timed out waiting for %s verification email", service)
    return None


def wait_for_verification_code(
    email_address: str,
    imap_password: str,
    service: str,
    timeout: int = 300,
    poll_interval: int = 8,
) -> str | None:
    """
    Like wait_for_verification_url but returns a 6–8 digit OTP code.
    Some services (GitHub) send a numeric code instead of a clickable link.
    """
    password = imap_password.replace(" ", "")
    senders = VERIFICATION_SENDERS.get(service, [service])
    deadline = time.time() + timeout

    logger.info("Waiting for %s OTP code (timeout=%ds)…", service, timeout)

    while time.time() < deadline:
        try:
            code = _check_inbox_for_code(email_address, password, senders)
            if code:
                logger.info("Found %s OTP code: %s", service, code)
                return code
        except Exception as e:
            logger.debug("IMAP poll error: %s", e)
        time.sleep(poll_interval)

    logger.warning("Timed out waiting for %s OTP code", service)
    return None


def _check_inbox(email_address: str, password: str, senders: list[str]) -> str | None:
    mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    try:
        mail.login(email_address, password)

        result = None
        # Search both inbox and spam — Gmail may filter automated emails
        for folder in ["INBOX", "[Gmail]/Spam", "[Gmail]/All Mail"]:
            try:
                status, _ = mail.select(folder, readonly=False)
                if status != "OK":
                    continue
            except Exception:
                continue

            _, data = mail.search(None, "UNSEEN")
            mail_ids = data[0].split()

            for mid in reversed(mail_ids):
                _, msg_data = mail.fetch(mid, "(RFC822)")
                msg = email_lib.message_from_bytes(msg_data[0][1])

                from_hdr = msg.get("From", "").lower()
                subject = msg.get("Subject", "").lower()
                combined = from_hdr + " " + subject

                if not any(s.lower() in combined for s in senders):
                    continue

                body = _extract_body(msg)
                url = _find_verification_url(body)
                if url:
                    mail.store(mid, "+FLAGS", "\\Seen")
                    result = url
                    break

            if result:
                break

    finally:
        try:
            mail.logout()
        except Exception:
            pass
    return result


def _check_inbox_for_code(email_address: str, password: str, senders: list[str]) -> str | None:
    mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    try:
        mail.login(email_address, password)

        for folder in ["INBOX", "[Gmail]/Spam", "[Gmail]/All Mail"]:
            try:
                status, _ = mail.select(folder, readonly=False)
                if status != "OK":
                    continue
            except Exception:
                continue

            _, data = mail.search(None, "UNSEEN")
            mail_ids = data[0].split()

            for mid in reversed(mail_ids):
                _, msg_data = mail.fetch(mid, "(RFC822)")
                msg = email_lib.message_from_bytes(msg_data[0][1])

                from_hdr = msg.get("From", "").lower()
                subject = msg.get("Subject", "").lower()
                combined = from_hdr + " " + subject

                if not any(s.lower() in combined for s in senders):
                    continue

                body = _extract_body(msg)
                code = _find_otp_code(body)
                if code:
                    mail.store(mid, "+FLAGS", "\\Seen")
                    return code

    finally:
        try:
            mail.logout()
        except Exception:
            pass
    return None


def _extract_body(msg) -> str:
    parts = []
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct in ("text/plain", "text/html"):
                try:
                    parts.append(part.get_payload(decode=True).decode("utf-8", errors="ignore"))
                except Exception:
                    pass
    else:
        try:
            parts.append(msg.get_payload(decode=True).decode("utf-8", errors="ignore"))
        except Exception:
            pass
    return "\n".join(parts)


def _find_verification_url(body: str) -> str | None:
    keywords = ["verify", "confirm", "activate", "validate", "email", "account", "magic", "login", "signup"]
    urls = re.findall(r'https?://[^\s<>"\')\]]+', body)
    for url in urls:
        url_lower = url.lower()
        if any(kw in url_lower for kw in keywords):
            url = re.sub(r'[.,;!?\'"]+$', '', url)
            return url
    # Fallback: return any non-tracking URL if it looks like an action link
    for url in urls:
        url = re.sub(r'[.,;!?\'"]+$', '', url)
        if len(url) > 60 and ("token" in url.lower() or "code" in url.lower()):
            return url
    return None


def _find_otp_code(body: str) -> str | None:
    """Extract a 6-8 digit OTP code from email body."""
    # Look for isolated digit sequences (GitHub sends 6-digit codes)
    matches = re.findall(r'(?<!\d)(\d{6,8})(?!\d)', body)
    for m in matches:
        # Skip years and common non-OTP numbers
        if m.startswith("20") and len(m) == 4:
            continue
        return m
    return None
