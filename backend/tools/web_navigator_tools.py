"""
Web navigator tools — vision-driven autonomous browser control.
Used by the web_navigator specialist for sign-ups, API key grabs, purchases, and general web tasks.
"""
import asyncio
import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Patterns to scan pages for credentials / API keys
_KEY_PATTERNS = [
    (r"sk-[A-Za-z0-9]{20,}", "openai_api_key"),
    (r"sk-or-v1-[A-Za-z0-9]{40,}", "openrouter_api_key"),
    (r"ghp_[A-Za-z0-9]{36}", "github_token"),
    (r"glpat-[A-Za-z0-9\-_]{20,}", "gitlab_token"),
    (r"pk_live_[A-Za-z0-9]{24,}", "stripe_publishable_key"),
    (r"sk_live_[A-Za-z0-9]{24,}", "stripe_secret_key"),
    (r"pk_test_[A-Za-z0-9]{24,}", "stripe_test_publishable"),
    (r"sk_test_[A-Za-z0-9]{24,}", "stripe_test_secret"),
    (r"SG\.[A-Za-z0-9\-_]{22}\.[A-Za-z0-9\-_]{43}", "sendgrid_api_key"),
    (r"AC[a-f0-9]{32}", "twilio_account_sid"),
    (r"[a-f0-9]{32}:[a-f0-9]{32}", "twilio_auth_token"),
    (r"AKIA[0-9A-Z]{16}", "aws_access_key"),
    (r"EAAl[A-Za-z0-9]{100,}", "facebook_token"),
    (r"ya29\.[A-Za-z0-9\-_]{100,}", "google_oauth_token"),
    (r'"api[_-]?key"\s*:\s*"([A-Za-z0-9\-_]{16,})"', "generic_api_key"),
    (r'"token"\s*:\s*"([A-Za-z0-9\-_\.]{20,})"', "generic_token"),
    (r'"secret"\s*:\s*"([A-Za-z0-9\-_]{16,})"', "generic_secret"),
    (r'[A-Za-z0-9\-_]{32,64}', "possible_key"),  # broad fallback
]


def _scan_for_keys(text: str) -> dict[str, str]:
    """Scan text for API keys and tokens. Returns first match per type."""
    found: dict[str, str] = {}
    for pattern, key_type in _KEY_PATTERNS[:-1]:  # skip broad fallback
        m = re.search(pattern, text)
        if m:
            val = m.group(1) if m.lastindex else m.group(0)
            found[key_type] = val
    return found


def _get_vision_client():
    """Get OpenAI-compat client pointed at OpenRouter for Gemini vision."""
    import openai
    from backend.config import settings
    from backend.core.key_rotator import get_openrouter_key
    key = get_openrouter_key() or settings.openrouter_api_key
    return openai.OpenAI(
        base_url=settings.openrouter_base_url,
        api_key=key,
    )


def _vision_next_action(screenshot_b64: str, goal: str, history: list[dict], credentials: dict) -> dict:
    """
    Ask Gemini Flash (via OpenRouter) what action to take next given the current screenshot.
    Returns a browser action dict or {"action": "done", "result": {...}}.
    """
    cred_hint = ""
    if credentials:
        safe_creds = {k: v for k, v in credentials.items() if "password" not in k.lower() and "card" not in k.lower()}
        if safe_creds:
            cred_hint = f"\nAvailable credentials (use these for forms): {json.dumps(safe_creds)}"

    client = _get_vision_client()
    prompt = (
        f"GOAL: {goal}{cred_hint}\n\n"
        f"HISTORY (last 5 actions): {json.dumps(history[-5:]) if history else '[]'}\n\n"
        "Look at this screenshot of a web browser. Decide the single best next action to make progress toward the goal.\n\n"
        "Respond with ONLY a JSON object. Valid actions:\n"
        '- {"action": "navigate", "url": "https://..."}\n'
        '- {"action": "click", "selector": "css-selector"}\n'
        '- {"action": "click_text", "text": "visible button/link text"}\n'
        '- {"action": "type", "selector": "css-selector", "text": "value to type"}\n'
        '- {"action": "key", "key": "Enter|Tab|Escape"}\n'
        '- {"action": "scroll", "delta_y": 300}\n'
        '- {"action": "wait", "ms": 2000}\n'
        '- {"action": "done", "result": {"success": true/false, "message": "...", "extracted": {...}}}\n\n'
        "Use 'done' only when the goal is fully achieved or clearly impossible. "
        "Always prefer specific CSS selectors over click_text when visible. "
        "If you see an API key, token, or credential on screen, include it in done.result.extracted."
    )

    resp = client.chat.completions.create(
        model="google/gemini-2.5-flash",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"}},
                ],
            }
        ],
        max_tokens=512,
    )
    raw = resp.choices[0].message.content or ""
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw).rstrip("```").strip()
    try:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        return json.loads(raw[start:end])
    except Exception:
        logger.warning("vision_next_action parse failed: %s", raw[:200])
        return {"action": "done", "result": {"success": False, "message": "vision model returned unparseable response"}}


async def _click_by_text(page: Any, text: str) -> dict:
    """Click an element by its visible text using Playwright locators."""
    try:
        el = page.get_by_text(text, exact=False).first
        await el.click(timeout=8000)
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=4000)
        except Exception:
            pass
        return {"ok": True}
    except Exception as e:
        # Fallback: try button/link with contains text
        try:
            await page.click(f"button:has-text('{text}'), a:has-text('{text}')", timeout=5000)
            return {"ok": True}
        except Exception:
            return {"error": str(e)}


async def vision_browse(
    url: str,
    goal: str,
    credentials: dict | None = None,
    max_steps: int = 30,
    founder_id: str = "",
    session_id: str = "",
    _browser_session=None,
) -> dict:
    """
    Autonomously browse the web to achieve a goal using vision-guided actions.

    Starts at `url`, takes screenshots, asks Gemini Flash what to do next,
    executes the action, and repeats until the goal is done or max_steps reached.

    credentials: dict of {email, password, card_number, expiry, cvv, name, etc.}
    Returns: {"success": bool, "message": str, "extracted": {api_keys, tokens, etc.}, "steps": int}
    """
    if credentials is None:
        credentials = {}

    if _browser_session is None:
        from backend.computer_use.browser import BrowserSession
        _browser_session = BrowserSession(headless=True)

    try:
        await _browser_session.start()
    except Exception as e:
        return {"success": False, "message": f"Browser failed to start: {e}", "extracted": {}}

    page = _browser_session._page
    history: list[dict] = []
    all_extracted: dict[str, str] = {}
    step = 0

    # Navigate to start URL
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
    except Exception as e:
        return {"success": False, "message": f"Failed to navigate to {url}: {e}", "extracted": {}}

    while step < max_steps:
        step += 1

        # Grab screenshot
        try:
            png = await page.screenshot(type="png")
            import base64
            screenshot_b64 = base64.b64encode(png).decode()
        except Exception as e:
            return {"success": False, "message": f"Screenshot failed at step {step}: {e}", "extracted": all_extracted}

        # Scan current page text for API keys in background
        try:
            page_text = await page.inner_text("body")
            found_keys = _scan_for_keys(page_text)
            all_extracted.update(found_keys)
        except Exception:
            pass

        # Ask vision model for next action
        try:
            action = _vision_next_action(screenshot_b64, goal, history, credentials)
        except Exception as e:
            logger.warning("Vision model error at step %d: %s", step, e)
            action = {"action": "wait", "ms": 2000}

        history.append({"step": step, "action": action.get("action"), "url": page.url})

        act = action.get("action", "")

        if act == "done":
            result = action.get("result", {})
            extracted = result.get("extracted", {})
            all_extracted.update(extracted)
            # Final scan
            try:
                page_text = await page.inner_text("body")
                all_extracted.update(_scan_for_keys(page_text))
            except Exception:
                pass
            return {
                "success": result.get("success", True),
                "message": result.get("message", "Task complete"),
                "url": page.url,
                "extracted": all_extracted,
                "steps": step,
            }

        # Execute action
        try:
            if act == "navigate":
                await page.goto(action["url"], wait_until="domcontentloaded", timeout=30000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass

            elif act == "click":
                await page.click(action["selector"], timeout=10000)
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=5000)
                except Exception:
                    pass

            elif act == "click_text":
                await _click_by_text(page, action["text"])

            elif act == "type":
                selector = action.get("selector", "")
                text_val = action.get("text", "")
                # Substitute credential placeholders
                for cred_key, cred_val in credentials.items():
                    if f"{{{cred_key}}}" in text_val:
                        text_val = text_val.replace(f"{{{cred_key}}}", cred_val)
                if selector:
                    await page.fill(selector, text_val)
                else:
                    await page.keyboard.type(text_val)

            elif act == "key":
                await page.keyboard.press(action.get("key", "Enter"))
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=5000)
                except Exception:
                    pass

            elif act == "scroll":
                await page.mouse.wheel(0, action.get("delta_y", 300))
                await asyncio.sleep(0.5)

            elif act == "wait":
                await asyncio.sleep(action.get("ms", 1000) / 1000)

        except Exception as e:
            logger.warning("Action %s failed at step %d: %s", act, step, e)
            history[-1]["error"] = str(e)
            # Don't abort — let vision model try a different approach next step
            await asyncio.sleep(1)

    # Max steps reached — return what we have
    try:
        final_text = await page.inner_text("body")
        all_extracted.update(_scan_for_keys(final_text))
    except Exception:
        pass

    return {
        "success": len(all_extracted) > 0,
        "message": f"Reached max steps ({max_steps}). Partial result.",
        "url": page.url,
        "extracted": all_extracted,
        "steps": step,
    }


async def check_email_for_verification(service_name: str = "", timeout_seconds: int = 60) -> dict:
    """
    Check the Astra test email inbox (via IMAP) for a verification code or magic link.
    Waits up to timeout_seconds for a matching email.
    Returns {"code": "...", "link": "...", "subject": "..."}
    """
    import imaplib
    import email as email_lib
    import time
    from backend.config import settings

    imap_host = "imap.gmail.com"
    imap_user = settings.test_email_base if hasattr(settings, "test_email_base") else "astra.testingmail@gmail.com"
    imap_pass = settings.test_email_imap_password if hasattr(settings, "test_email_imap_password") else ""

    if not imap_pass:
        return {"error": "IMAP password not configured (TEST_EMAIL_IMAP_PASSWORD)"}

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            mail = imaplib.IMAP4_SSL(imap_host)
            mail.login(imap_user, imap_pass)
            mail.select("INBOX")
            _, msg_ids = mail.search(None, "UNSEEN")
            for mid in (msg_ids[0].split() or [])[::-1]:  # newest first
                _, msg_data = mail.fetch(mid, "(RFC822)")
                msg = email_lib.message_from_bytes(msg_data[0][1])
                subject = msg.get("Subject", "")
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            body = part.get_payload(decode=True).decode("utf-8", errors="replace")
                            break
                else:
                    body = msg.get_payload(decode=True).decode("utf-8", errors="replace")

                # Skip if service_name provided and not in email
                if service_name and service_name.lower() not in subject.lower() and service_name.lower() not in body.lower():
                    continue

                # Extract OTP codes (4-8 digits)
                codes = re.findall(r"\b\d{4,8}\b", body)
                # Extract magic links
                links = re.findall(r"https?://\S+(?:verify|confirm|activate|magic|token)\S+", body, re.IGNORECASE)

                if codes or links:
                    mail.store(mid, "+FLAGS", "\\Seen")
                    mail.logout()
                    return {
                        "code": codes[0] if codes else "",
                        "link": links[0] if links else "",
                        "subject": subject,
                        "all_codes": codes,
                        "all_links": links,
                    }
            mail.logout()
        except Exception as e:
            logger.warning("IMAP check failed: %s", e)

        await asyncio.sleep(5)

    return {"error": f"No verification email received within {timeout_seconds}s", "code": "", "link": ""}


def scan_page_for_keys(page_text: str) -> dict:
    """Scan arbitrary text for API keys and tokens. Useful for processing copied dashboard content."""
    return _scan_for_keys(page_text)
