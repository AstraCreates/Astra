"""
Web navigator tools — vision-driven autonomous browser control.
Supports pause/resume for when the agent hits obstacles (login, 2FA, payment, etc.)
"""
import asyncio
import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# In-memory sessions: {session_id: {status, event_queue, input_event, input_data, browser}}
_nav_sessions: dict[str, dict] = {}

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
    (r"AKIA[0-9A-Z]{16}", "aws_access_key"),
    (r'"api[_-]?key"\s*:\s*"([A-Za-z0-9\-_]{16,})"', "generic_api_key"),
    (r'"token"\s*:\s*"([A-Za-z0-9\-_\.]{20,})"', "generic_token"),
    (r'"secret"\s*:\s*"([A-Za-z0-9\-_]{16,})"', "generic_secret"),
]


def _scan_for_keys(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for pattern, key_type in _KEY_PATTERNS:
        m = re.search(pattern, text)
        if m:
            val = m.group(1) if m.lastindex else m.group(0)
            found[key_type] = val
    return found


def _get_vision_client():
    import openai
    from backend.config import settings
    from backend.core.key_rotator import get_openrouter_key
    key = get_openrouter_key() or settings.openrouter_api_key
    return openai.OpenAI(base_url=settings.openrouter_base_url, api_key=key)


def _vision_next_action(screenshot_b64: str, goal: str, history: list[dict], credentials: dict) -> dict:
    """Ask Gemini Flash what to do next. Can return need_input when hitting an obstacle."""
    cred_hint = ""
    if credentials:
        safe = {k: v for k, v in credentials.items() if "password" not in k.lower() and "card" not in k.lower() and "cvv" not in k.lower()}
        if safe:
            cred_hint = f"\nCredentials available (use when needed): {json.dumps(safe)}"
        if any(k in credentials for k in ("password", "card_number", "cvv")):
            cred_hint += "\n(Sensitive credentials available — use them for login/payment forms)"

    client = _get_vision_client()
    prompt = (
        f"GOAL: {goal}{cred_hint}\n\n"
        f"HISTORY (last 5): {json.dumps(history[-5:]) if history else '[]'}\n\n"
        "Look at this browser screenshot. Decide the single best next action.\n\n"
        "Respond with ONLY a JSON object. Actions:\n"
        '{"action": "navigate", "url": "..."}\n'
        '{"action": "click", "selector": "css-selector"}\n'
        '{"action": "click_text", "text": "visible text"}\n'
        '{"action": "type", "selector": "css-selector", "text": "value"}\n'
        '{"action": "key", "key": "Enter|Tab|Escape"}\n'
        '{"action": "scroll", "delta_y": 300}\n'
        '{"action": "wait", "ms": 2000}\n'
        '{"action": "need_input", "prompt": "...", "fields": [{"key": "email", "label": "Email", "type": "email"}, ...]}\n'
        '{"action": "done", "result": {"success": true, "message": "...", "extracted": {...}}}\n\n'
        "Use need_input ONLY when you genuinely cannot proceed without user info:\n"
        "- Login/sign-in form with no credentials available\n"
        "- 2FA / OTP code prompt\n"
        "- Payment form with no card details\n"
        "- CAPTCHA or phone verification\n"
        "- Security question\n\n"
        "field types: text, email, password, tel, number\n"
        "Do NOT use need_input for things you can figure out yourself.\n"
        "If goal is done or impossible, use 'done'. Include extracted keys/tokens in done.result.extracted."
    )

    try:
        resp = client.chat.completions.create(
            model="google/gemini-2.5-flash",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"}},
                ],
            }],
            max_tokens=512,
        )
        raw = resp.choices[0].message.content or ""
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw).rstrip("```").strip()
        start = raw.find("{")
        end = raw.rfind("}") + 1
        return json.loads(raw[start:end])
    except Exception as e:
        logger.warning("vision_next_action error: %s", e)
        return {"action": "done", "result": {"success": False, "message": f"Vision model error: {e}"}}


async def _click_by_text(page: Any, text: str) -> dict:
    try:
        el = page.get_by_text(text, exact=False).first
        await el.click(timeout=8000)
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=4000)
        except Exception:
            pass
        return {"ok": True}
    except Exception as e:
        try:
            await page.click(f"button:has-text('{text}'), a:has-text('{text}')", timeout=5000)
            return {"ok": True}
        except Exception:
            return {"error": str(e)}


async def vision_browse_streaming(
    session_id: str,
    url: str,
    goal: str,
    max_steps: int = 30,
) -> None:
    """
    Run the vision browse loop for a session, pushing SSE events to the session queue.
    Pauses when need_input is returned and waits for user response via resume_session().
    """
    session = _nav_sessions.get(session_id)
    if not session:
        return

    queue: asyncio.Queue = session["event_queue"]
    credentials: dict = session.get("credentials", {})

    async def emit(event_type: str, data: dict):
        await queue.put({"type": event_type, **data})

    from backend.computer_use.browser import BrowserSession
    browser = BrowserSession(headless=True)
    session["browser"] = browser

    try:
        await browser.start()
    except Exception as e:
        await emit("error", {"message": f"Browser failed to start: {e}"})
        session["status"] = "done"
        await queue.put(None)  # sentinel
        return

    page = browser._page
    history: list[dict] = []
    all_extracted: dict[str, str] = {}

    await emit("status", {"message": f"Navigating to {url}…", "step": 0})

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
    except Exception as e:
        await emit("error", {"message": f"Failed to navigate to {url}: {e}"})
        session["status"] = "done"
        await queue.put(None)
        await browser.stop()
        return

    step = 0
    while step < max_steps:
        step += 1

        # Take screenshot
        try:
            import base64
            png = await page.screenshot(type="png")
            screenshot_b64 = base64.b64encode(png).decode()
        except Exception as e:
            await emit("error", {"message": f"Screenshot failed: {e}"})
            break

        # Scan page for keys
        try:
            page_text = await page.inner_text("body")
            found = _scan_for_keys(page_text)
            if found:
                all_extracted.update(found)
        except Exception:
            pass

        await emit("status", {"message": f"Analysing page…", "step": step, "url": page.url})

        # Ask vision model
        action = await asyncio.to_thread(
            _vision_next_action, screenshot_b64, goal, history, session.get("credentials", {})
        )

        act = action.get("action", "")
        history.append({"step": step, "action": act, "url": page.url})

        if act == "done":
            result = action.get("result", {})
            all_extracted.update(result.get("extracted", {}))
            try:
                page_text = await page.inner_text("body")
                all_extracted.update(_scan_for_keys(page_text))
            except Exception:
                pass
            await emit("done", {
                "success": result.get("success", True),
                "message": result.get("message", "Task complete"),
                "url": page.url,
                "extracted": all_extracted,
                "steps": step,
            })
            session["status"] = "done"
            await queue.put(None)
            await browser.stop()
            return

        if act == "need_input":
            session["status"] = "waiting"
            await emit("need_input", {
                "prompt": action.get("prompt", "The agent needs more information to continue."),
                "fields": action.get("fields", [{"key": "info", "label": "Information needed", "type": "text"}]),
                "url": page.url,
                "step": step,
            })
            # Wait for user response (up to 10 minutes)
            input_event: asyncio.Event = session["input_event"]
            input_event.clear()
            try:
                await asyncio.wait_for(input_event.wait(), timeout=600)
            except asyncio.TimeoutError:
                await emit("error", {"message": "Timed out waiting for user input."})
                break
            # Merge provided credentials and continue
            session["credentials"].update(session.get("input_data", {}))
            session["status"] = "running"
            await emit("status", {"message": "Resuming…", "step": step, "url": page.url})
            continue

        # Execute action
        try:
            if act == "navigate":
                await emit("status", {"message": f"Navigating to {action['url']}", "step": step})
                await page.goto(action["url"], wait_until="domcontentloaded", timeout=30000)
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass

            elif act == "click":
                await emit("status", {"message": f"Clicking {action.get('selector', '')}", "step": step})
                await page.click(action["selector"], timeout=10000)
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=5000)
                except Exception:
                    pass

            elif act == "click_text":
                await emit("status", {"message": f"Clicking '{action.get('text', '')}'", "step": step})
                await _click_by_text(page, action["text"])

            elif act == "type":
                text_val = action.get("text", "")
                for cred_key, cred_val in session.get("credentials", {}).items():
                    text_val = text_val.replace(f"{{{cred_key}}}", cred_val)
                await emit("status", {"message": f"Typing into {action.get('selector', 'field')}", "step": step})
                if action.get("selector"):
                    await page.fill(action["selector"], text_val)
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
                await asyncio.sleep(0.4)

            elif act == "wait":
                await asyncio.sleep(action.get("ms", 1000) / 1000)

        except Exception as e:
            logger.warning("Action %s failed at step %d: %s", act, step, e)
            await asyncio.sleep(0.5)

    # Max steps
    try:
        page_text = await page.inner_text("body")
        all_extracted.update(_scan_for_keys(page_text))
    except Exception:
        pass

    await emit("done", {
        "success": len(all_extracted) > 0,
        "message": f"Reached max steps ({max_steps}).",
        "url": page.url,
        "extracted": all_extracted,
        "steps": step,
    })
    session["status"] = "done"
    await queue.put(None)
    await browser.stop()


def create_nav_session(session_id: str) -> dict:
    """Create a new navigator session and return it."""
    session = {
        "status": "running",
        "event_queue": asyncio.Queue(),
        "input_event": asyncio.Event(),
        "input_data": {},
        "credentials": {},
        "browser": None,
    }
    _nav_sessions[session_id] = session
    return session


def resume_nav_session(session_id: str, input_data: dict) -> bool:
    """Provide user input to a waiting session. Returns False if session not found/waiting."""
    session = _nav_sessions.get(session_id)
    if not session or session.get("status") != "waiting":
        return False
    session["input_data"] = input_data
    session["input_event"].set()
    return True


def get_nav_session(session_id: str) -> dict | None:
    return _nav_sessions.get(session_id)


async def check_email_for_verification(service_name: str = "", timeout_seconds: int = 60) -> dict:
    """Check the Astra test email inbox for a verification code or magic link."""
    import imaplib
    import email as email_lib
    import time
    from backend.config import settings

    imap_user = getattr(settings, "test_email_base", "astra.testingmail@gmail.com")
    imap_pass = getattr(settings, "test_email_imap_password", "")
    if not imap_pass:
        return {"error": "IMAP password not configured", "code": "", "link": ""}

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(imap_user, imap_pass)
            mail.select("INBOX")
            _, msg_ids = mail.search(None, "UNSEEN")
            for mid in (msg_ids[0].split() or [])[::-1]:
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
                if service_name and service_name.lower() not in subject.lower() and service_name.lower() not in body.lower():
                    continue
                codes = re.findall(r"\b\d{4,8}\b", body)
                links = re.findall(r"https?://\S+(?:verify|confirm|activate|magic|token)\S+", body, re.IGNORECASE)
                if codes or links:
                    mail.store(mid, "+FLAGS", "\\Seen")
                    mail.logout()
                    return {"code": codes[0] if codes else "", "link": links[0] if links else "", "subject": subject}
            mail.logout()
        except Exception as e:
            logger.warning("IMAP check failed: %s", e)
        await asyncio.sleep(5)

    return {"error": f"No verification email within {timeout_seconds}s", "code": "", "link": ""}


def scan_page_for_keys(page_text: str) -> dict:
    return _scan_for_keys(page_text)


# Keep simple synchronous vision_browse for agent tool use (non-sandbox)
async def vision_browse(
    url: str,
    goal: str,
    credentials: dict | None = None,
    max_steps: int = 30,
    founder_id: str = "",
    session_id: str = "",
    _browser_session=None,
) -> dict:
    """Simple blocking version for agent tool use (no streaming)."""
    import uuid
    sid = session_id or str(uuid.uuid4())
    session = create_nav_session(sid)
    session["credentials"] = credentials or {}

    # Run streaming version and collect the done event
    task = asyncio.create_task(vision_browse_streaming(sid, url, goal, max_steps))

    queue: asyncio.Queue = session["event_queue"]
    result = {"success": False, "message": "No result", "extracted": {}, "steps": 0}
    while True:
        event = await queue.get()
        if event is None:
            break
        if event.get("type") == "done":
            result = {k: v for k, v in event.items() if k != "type"}
        elif event.get("type") == "need_input":
            # In non-streaming mode, can't pause — skip and continue
            session["input_data"] = {}
            session["input_event"].set()

    await task
    _nav_sessions.pop(sid, None)
    return result
