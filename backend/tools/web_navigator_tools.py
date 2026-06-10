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


def _goal_requests_secret(goal: str) -> bool:
    goal_l = (goal or "").lower()
    markers = (
        "api key", "token", "secret", "credentials", "access key", "webhook",
        "copy key", "grab key", "get key", "auth key",
    )
    return any(marker in goal_l for marker in markers)


def _looks_like_email_verification(text: str) -> bool:
    t = (text or "").lower()
    hints = (
        "check your email", "verification code", "verify your email",
        "enter the code", "magic link", "confirmation code", "one-time code",
    )
    return any(hint in t for hint in hints)


def _service_name_from_url(url: str) -> str:
    m = re.search(r"https?://(?:www\.)?([^./]+)", url or "", re.IGNORECASE)
    return (m.group(1) if m else "").strip()


async def _capture_page_context(page: Any) -> dict[str, Any]:
    title = ""
    body_text = ""
    forms: list[dict[str, str]] = []
    elements: list[dict[str, str]] = []
    try:
        title = await page.title()
    except Exception:
        pass
    try:
        body_text = await page.inner_text("body")
    except Exception:
        pass
    try:
        forms = await page.evaluate("""() => {
            const candidates = Array.from(document.querySelectorAll('input, textarea, select')).slice(0, 20);
            return candidates.map((el) => ({
                tag: el.tagName.toLowerCase(),
                type: (el.getAttribute('type') || '').toLowerCase(),
                name: el.getAttribute('name') || '',
                id: el.id || '',
                placeholder: el.getAttribute('placeholder') || '',
                label: el.getAttribute('aria-label') || el.getAttribute('autocomplete') || ''
            }));
        }""")
    except Exception:
        forms = []
    try:
        elements = await page.evaluate("""() => {
            const els = Array.from(document.querySelectorAll('a, button, [role="button"], input[type="submit"], input[type="button"]')).slice(0, 40);
            return els.map((el) => ({
                tag: el.tagName.toLowerCase(),
                text: (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().slice(0, 80),
                id: el.id || '',
                href: el.href || ''
            })).filter((el) => el.text || el.id || el.href);
        }""")
    except Exception:
        elements = []
    return {
        "url": getattr(page, "url", ""),
        "title": title,
        "body_text": body_text[:4000],
        "forms": forms[:12],
        "elements": elements[:20],
    }


async def _maybe_switch_to_latest_page(browser: Any, page: Any) -> Any:
    try:
        pages = list(page.context.pages)
    except Exception:
        return page
    if not pages:
        return page
    latest = pages[-1]
    if latest is not page:
        try:
            await latest.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass
        return latest
    return page


async def _extract_goal_artifacts(page: Any, goal: str) -> dict[str, Any]:
    page_text = ""
    try:
        page_text = await page.inner_text("body")
    except Exception:
        page_text = ""
    extracted = _scan_for_keys(page_text)
    if _goal_requests_secret(goal) and extracted:
        return {
            "done": True,
            "payload": {
                "success": True,
                "message": "Found requested credentials on the page.",
                "url": page.url,
                "extracted": extracted,
            },
        }
    return {"done": False, "page_text": page_text, "extracted": extracted}


async def _maybe_handle_email_verification(page: Any, goal: str, session: dict) -> dict | None:
    ctx = await _capture_page_context(page)
    page_text = ctx.get("body_text", "")
    if not _looks_like_email_verification(page_text):
        return None
    verification = await check_email_for_verification(_service_name_from_url(page.url), timeout_seconds=45)
    code = verification.get("code", "")
    link = verification.get("link", "")
    if link:
        try:
            await page.goto(link, wait_until="domcontentloaded", timeout=30000)
            return {"ok": True, "message": "Opened email verification link automatically."}
        except Exception as e:
            return {"ok": False, "message": f"Found verification link but navigation failed: {e}"}
    if code:
        session.setdefault("credentials", {})["verification_code"] = code
        try:
            code_input = page.locator("input").filter(has_text=None).first
            if await code_input.count():
                await code_input.fill(code)
            else:
                await page.keyboard.type(code)
            await page.keyboard.press("Enter")
            return {"ok": True, "message": "Filled verification code automatically."}
        except Exception:
            return {"ok": True, "message": "Captured verification code and added it to available credentials."}
    return None


def _get_vision_client():
    import openai
    from backend.config import settings
    from backend.core.key_rotator import get_openrouter_key
    key = get_openrouter_key() or settings.openrouter_api_key
    return openai.OpenAI(base_url=settings.openrouter_base_url, api_key=key)


def _vision_next_action(
    screenshot_b64: str,
    goal: str,
    history: list[dict],
    credentials: dict,
    page_context: dict | None = None,
) -> dict:
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
        f"PAGE CONTEXT: {json.dumps(page_context or {}, ensure_ascii=True)}\n\n"
        f"HISTORY (last 5): {json.dumps(history[-5:]) if history else '[]'}\n\n"
        "Look at this browser screenshot. Decide the single best next action.\n\n"
        "Respond with ONLY a JSON object. Actions:\n"
        '{"action": "navigate", "url": "..."}\n'
        '{"action": "click", "selector": "css-selector"}\n'
        '{"action": "click_text", "text": "visible text"}\n'
        '{"action": "type", "selector": "css-selector", "text": "value"}\n'
        '{"action": "type_credential", "selector": "css-selector", "credential_key": "email|password|verification_code|card_number|name|zip"}\n'
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
        "Prefer click_text when there is visible text in PAGE CONTEXT. Prefer type_credential when filling known secrets.\n"
        "If the page is an API/dashboard page, prioritize navigating to Billing / Settings / API / Developers / Keys.\n"
        "If the goal is sign-up, prioritize email verification completion before declaring done.\n"
        "Do NOT use need_input for things you can figure out yourself.\n"
        "When using 'done', only put things in extracted that the goal explicitly asked for "
        "(e.g. if goal says 'get the API key', include the key; if goal just says 'sign up', extracted should be empty)."
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
            extra_body={"provider": {"allow_fallbacks": True}},
        )
        raw = (resp.choices[0].message.content if getattr(resp, "choices", None) else "") or ""
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


async def _fill_best_effort(page: Any, selector: str, text_val: str) -> None:
    try:
        await page.fill(selector, text_val, timeout=8000)
        return
    except Exception:
        pass
    try:
        await page.click(selector, timeout=8000)
        await page.keyboard.press("Meta+A")
        await page.keyboard.press("Backspace")
        await page.keyboard.type(text_val)
        return
    except Exception:
        pass
    await page.keyboard.type(text_val)


async def vision_browse_streaming(
    session_id: str,
    url: str,
    goal: str,
    max_steps: int = 50,
) -> None:
    """
    Run the vision browse loop for a session, pushing SSE events to the session queue.
    Pauses when need_input is returned and waits for user response via resume_session().
    """
    session = _nav_sessions.get(session_id)
    if not session:
        return

    queue: asyncio.Queue = session["event_queue"]

    async def emit(event_type: str, data: dict):
        await queue.put({"type": event_type, **data})

    try:
        await _vision_browse_inner(session_id, url, goal, max_steps, session, emit, queue)
    except Exception as e:
        logger.exception("vision_browse_streaming crashed: %s", e)
        try:
            await emit("error", {"message": f"Agent crashed: {e}"})
        except Exception:
            pass
        session["status"] = "done"
        await queue.put(None)


async def _vision_browse_inner(session_id, url, goal, max_steps, session, emit, queue):
    from backend.computer_use.browser import BrowserSession
    browser = BrowserSession(headless=True)
    session["browser"] = browser

    try:
        await browser.start()
    except Exception as e:
        await emit("error", {"message": f"Browser failed to start: {e}. Make sure 'playwright install chromium' has been run."})
        session["status"] = "done"
        await queue.put(None)
        return

    page = browser._page
    history: list[dict] = []

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
        page = await _maybe_switch_to_latest_page(browser, page)

        verification_result = await _maybe_handle_email_verification(page, goal, session)
        if verification_result:
            await emit("status", {"message": verification_result["message"], "step": step, "url": page.url})

        # Take screenshot
        try:
            import base64
            png = await page.screenshot(type="png")
            screenshot_b64 = base64.b64encode(png).decode()
        except Exception as e:
            await emit("error", {"message": f"Screenshot failed: {e}"})
            break

        extraction_check = await _extract_goal_artifacts(page, goal)
        if extraction_check.get("done"):
            await emit("done", {
                **extraction_check["payload"],
                "steps": step,
            })
            session["status"] = "done"
            await queue.put(None)
            await browser.stop()
            return

        await emit("status", {"message": f"Analysing page…", "step": step, "url": page.url})
        page_context = await _capture_page_context(page)

        # Ask vision model
        action = await asyncio.to_thread(
            _vision_next_action, screenshot_b64, goal, history, session.get("credentials", {}), page_context
        )

        act = action.get("action", "")
        history.append({"step": step, "action": act, "url": page.url})

        if act == "done":
            result = action.get("result", {})
            # Only include what the vision model explicitly extracted for this goal
            extracted = result.get("extracted", {})
            await emit("done", {
                "success": result.get("success", True),
                "message": result.get("message", "Task complete"),
                "url": page.url,
                "extracted": extracted,
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
                page = await _maybe_switch_to_latest_page(browser, page)
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=5000)
                except Exception:
                    pass

            elif act == "click_text":
                await emit("status", {"message": f"Clicking '{action.get('text', '')}'", "step": step})
                await _click_by_text(page, action["text"])
                page = await _maybe_switch_to_latest_page(browser, page)

            elif act == "type":
                text_val = action.get("text", "")
                for cred_key, cred_val in session.get("credentials", {}).items():
                    text_val = text_val.replace(f"{{{cred_key}}}", str(cred_val))
                await emit("status", {"message": f"Typing into {action.get('selector', 'field')}", "step": step})
                if action.get("selector"):
                    await _fill_best_effort(page, action["selector"], text_val)
                else:
                    await page.keyboard.type(text_val)

            elif act == "type_credential":
                cred_key = action.get("credential_key", "")
                text_val = str(session.get("credentials", {}).get(cred_key, ""))
                if not text_val:
                    raise RuntimeError(f"Missing credential: {cred_key}")
                await emit("status", {"message": f"Filling {cred_key}", "step": step})
                await _fill_best_effort(page, action.get("selector", "input"), text_val)

            elif act == "key":
                await page.keyboard.press(action.get("key", "Enter"))
                page = await _maybe_switch_to_latest_page(browser, page)
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

    await emit("done", {
        "success": False,
        "message": f"Reached max steps ({max_steps}) without completing the goal.",
        "url": page.url,
        "extracted": {},
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
    max_steps: int = 50,
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
