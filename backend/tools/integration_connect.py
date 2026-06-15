"""
Live Playwright browser flows for connecting GitHub, Vercel, and SendGrid.

Login phase: user-controlled — they see the live canvas and interact with it
             directly (clicks + keystrokes forwarded via CDP Input domain).
             OAuth popups (Google, Apple, etc.) are auto-detected and the
             screencast switches to them so the user sees and controls them.
Post-login:  bot takes over, navigates to token page, extracts and saves token.

Interface:
  send_message(dict)         — async, streams frame/status/user_control/done/error
  wait_input()               — async, blocks for form submission
  event_q (queue.Queue)      — thread-safe; receives mouse_event / key_event dicts
"""
import asyncio
import logging
import queue as _queue

logger = logging.getLogger(__name__)


# ── Browser launch ─────────────────────────────────────────────────────────────

async def _launch_browser(pw):
    return await pw.chromium.launch(
        headless=False,
        args=[
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--window-position=-32000,0",
            "--window-size=1280,800",
        ],
    )


async def _new_context(browser):
    ctx = await browser.new_context(
        viewport={"width": 1280, "height": 800},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    )
    await ctx.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        window.chrome = {runtime: {}};
    """)
    return ctx


# ── Screencast with popup tracking ────────────────────────────────────────────

async def _attach_screencast(context, page, send_message, refs: dict) -> None:
    """
    Start screencasting `page`, updating refs["client"] and refs["page"].
    Stops any existing screencast first.
    """
    old_client = refs.get("client")
    if old_client:
        try:
            await old_client.send("Page.stopScreencast")
        except Exception:
            pass

    client = await context.new_cdp_session(page)

    async def on_frame(params):
        try:
            await client.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]})
            await send_message({"type": "frame", "data": params["data"]})
        except Exception:
            pass

    client.on("Page.screencastFrame", lambda p: asyncio.ensure_future(on_frame(p)))
    await client.send("Page.startScreencast", {
        "format": "jpeg", "quality": 70,
        "maxWidth": 1280, "maxHeight": 800, "everyNthFrame": 2,
    })

    refs["client"] = client
    refs["page"] = page


async def _setup_popup_tracking(context, main_page, send_message, refs: dict) -> None:
    """
    Listen for ANY new page in the context (covers popups opened by CDP clicks,
    which don't always fire page.on('popup')).  When one opens, switch the
    screencast and input target to it.  When it closes, switch back to main_page.
    """
    async def on_new_page(new_page):
        if new_page is main_page:
            return
        logger.info("New page detected: %s", new_page.url)
        await _attach_screencast(context, new_page, send_message, refs)

        async def on_close():
            logger.info("Popup/tab closed, switching back to main page")
            try:
                await _attach_screencast(context, main_page, send_message, refs)
            except Exception as e:
                logger.warning("Could not reattach screencast after page close: %s", e)

        new_page.on("close", lambda: asyncio.ensure_future(on_close()))

    context.on("page", lambda p: asyncio.ensure_future(on_new_page(p)))


# ── Input forwarding ──────────────────────────────────────────────────────────

async def _input_forward_loop(refs: dict, event_q: _queue.Queue, stop: list) -> None:
    """
    Drain event_q and forward mouse/key events to whatever page is currently
    active (refs["client"] may change when popups open/close).
    """
    key_codes = {
        "Enter": 13, "Tab": 9, "Backspace": 8, "Delete": 46,
        "ArrowLeft": 37, "ArrowRight": 39, "ArrowUp": 38, "ArrowDown": 40,
        "Escape": 27, "Home": 36, "End": 35, " ": 32,
    }
    while not stop[0]:
        try:
            event = event_q.get_nowait()
            client = refs.get("client")
            if not client:
                await asyncio.sleep(0.02)
                continue

            etype = event.get("type")

            if etype == "mouse_event":
                x, y = float(event.get("x", 0)), float(event.get("y", 0))
                for mtype in ("mousePressed", "mouseReleased"):
                    try:
                        await client.send("Input.dispatchMouseEvent", {
                            "type": mtype, "x": x, "y": y,
                            "button": "left", "clickCount": 1, "modifiers": 0,
                            "pointerType": "mouse",
                        })
                    except Exception:
                        pass
                    if mtype == "mousePressed":
                        await asyncio.sleep(0.06)

            elif etype == "mouse_move":
                try:
                    await client.send("Input.dispatchMouseEvent", {
                        "type": "mouseMoved",
                        "x": float(event.get("x", 0)),
                        "y": float(event.get("y", 0)),
                        "button": "none", "modifiers": 0, "pointerType": "mouse",
                    })
                except Exception:
                    pass

            elif etype == "key_event":
                char = event.get("char", "")
                key = event.get("key", "")
                if char:
                    try:
                        await client.send("Input.dispatchKeyEvent", {
                            "type": "char", "text": char, "unmodifiedText": char,
                        })
                    except Exception:
                        pass
                if key in key_codes or key in ("Enter", "Tab", "Backspace"):
                    code = key_codes.get(key, 0)
                    for ktype in ("rawKeyDown", "keyUp"):
                        try:
                            await client.send("Input.dispatchKeyEvent", {
                                "type": ktype, "key": key, "code": key,
                                "windowsVirtualKeyCode": code,
                                "nativeVirtualKeyCode": code,
                            })
                        except Exception:
                            pass

        except _queue.Empty:
            await asyncio.sleep(0.02)
        except Exception:
            await asyncio.sleep(0.02)


# ── Login detection ────────────────────────────────────────────────────────────

async def _wait_for_login(page, service_domain: str, login_path: str, timeout: float = 300.0) -> bool:
    """
    Block until back on service_domain AND the URL no longer contains login_path.

    This correctly handles OAuth redirects (e.g. main page → accounts.google.com →
    back to github.com/dashboard): we only declare success once the user is back
    on the target service, not mid-OAuth on a third-party domain.
    """
    # First confirm we land on the login page (up to 10s)
    for _ in range(20):
        try:
            if login_path in page.url:
                break
        except Exception:
            pass
        await asyncio.sleep(0.5)

    # Now wait: must be on service_domain AND not on login_path
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            url = page.url
            if service_domain in url and login_path not in url:
                return True
        except Exception:
            pass
        await asyncio.sleep(1)
    return False


# ── Credential persistence ────────────────────────────────────────────────────

def _save_founder_credentials(founder_id: str, service: str, creds: dict) -> None:
    from backend.provisioning.credentials_store import store_credentials

    store_credentials(founder_id, service, creds)


# ── GitHub ────────────────────────────────────────────────────────────────────

async def connect_github_live(
    founder_id: str,
    send_message,
    wait_input,
    event_q: _queue.Queue | None = None,
) -> dict:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        await send_message({"type": "error", "message": "playwright not installed — run: pip install playwright && playwright install chromium"})
        return {"error": "playwright not installed"}

    result: dict = {}
    async with async_playwright() as pw:
        browser = await _launch_browser(pw)
        context = await _new_context(browser)
        page = await context.new_page()

        # refs holds the currently active CDP client + page (switches on popup open/close)
        refs: dict = {}
        await _attach_screencast(context, page, send_message, refs)
        await _setup_popup_tracking(context, page, send_message, refs)

        stop_forward = [False]
        forward_task = None
        if event_q is not None:
            forward_task = asyncio.create_task(_input_forward_loop(refs, event_q, stop_forward))

        try:
            # ── Step 1: User-controlled login ────────────────────────────────
            await send_message({
                "type": "user_control",
                "step": "Login",
                "step_num": 1,
                "total": 3,
                "message": "Sign in to GitHub — use any method (password, Google, Apple…)",
            })
            await page.goto("https://github.com/login", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(1)

            logged_in = await _wait_for_login(page, "github.com", "/login", timeout=300)
            if not logged_in:
                await send_message({"type": "error", "message": "Login timed out (5 min)."})
                return {"error": "login_timeout"}

            # ── Step 2: Bot navigates to token creation ───────────────────────
            stop_forward[0] = True  # lock canvas — bot takes over
            await send_message({"type": "status", "step": "Creating Token", "step_num": 2, "total": 3})
            await page.goto(
                "https://github.com/settings/tokens/new?description=Astra&scopes=repo,workflow,read:org",
                wait_until="domcontentloaded", timeout=20000,
            )
            await asyncio.sleep(1.5)

            try:
                await page.select_option("select#token_expiration", "0")
                await asyncio.sleep(0.5)
            except Exception:
                pass

            # ── Step 3: Generate + extract ────────────────────────────────────
            await send_message({"type": "status", "step": "Extracting Token", "step_num": 3, "total": 3})
            try:
                await page.click("button:has-text('Generate token')", timeout=8000)
            except Exception:
                await page.click("input[type='submit']", timeout=6000)
            await asyncio.sleep(2.5)

            token = ""
            for selector in [
                "#new-oauth-token", "code#new-oauth-token",
                "input[aria-label='Token']", ".token", "div.flash-full code",
            ]:
                try:
                    el = await page.query_selector(selector)
                    if el:
                        val = ((await el.inner_text()) or (await el.get_attribute("value")) or "").strip()
                        if len(val) > 10:
                            token = val
                            break
                except Exception:
                    continue

            if not token:
                await send_message({"type": "error", "message": "Could not extract GitHub token — try the manual key option."})
                return {"error": "token_extraction_failed"}

            _save_founder_credentials(founder_id, "github", {"token": token})
            result = {"status": "connected", "token_prefix": token[:8] + "…"}
            await send_message({"type": "done", **result})

        except Exception as e:
            logger.error("GitHub connect error: %s", e, exc_info=True)
            await send_message({"type": "error", "message": str(e)})
            result = {"error": str(e)}
        finally:
            stop_forward[0] = True
            if forward_task:
                forward_task.cancel()
            try:
                await refs["client"].send("Page.stopScreencast")
            except Exception:
                pass
            await browser.close()

    return result


# ── Vercel ────────────────────────────────────────────────────────────────────

async def connect_vercel_live(
    founder_id: str,
    send_message,
    wait_input,
    event_q: _queue.Queue | None = None,
) -> dict:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        await send_message({"type": "error", "message": "playwright not installed"})
        return {"error": "playwright not installed"}

    result: dict = {}
    async with async_playwright() as pw:
        browser = await _launch_browser(pw)
        context = await _new_context(browser)
        page = await context.new_page()

        refs: dict = {}
        await _attach_screencast(context, page, send_message, refs)
        await _setup_popup_tracking(context, page, send_message, refs)

        stop_forward = [False]
        forward_task = None
        if event_q is not None:
            forward_task = asyncio.create_task(_input_forward_loop(refs, event_q, stop_forward))

        try:
            await send_message({
                "type": "user_control",
                "step": "Login",
                "step_num": 1,
                "total": 3,
                "message": "Sign in to Vercel — use any method (GitHub, Google, email…)",
            })
            await page.goto("https://vercel.com/login", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(1)

            logged_in = await _wait_for_login(page, "vercel.com", "/login", timeout=300)
            if not logged_in:
                await send_message({"type": "error", "message": "Login timed out."})
                return {"error": "login_timeout"}

            stop_forward[0] = True
            await send_message({"type": "status", "step": "Creating Token", "step_num": 2, "total": 3})
            await page.goto("https://vercel.com/account/tokens", wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(1.5)

            try:
                await page.click("button:has-text('Create')", timeout=8000)
                await asyncio.sleep(1)
            except Exception:
                pass

            for placeholder in ["Token Name", "name", "Name"]:
                try:
                    await page.fill(f"input[placeholder='{placeholder}'], input[name='name']", "Astra", timeout=4000)
                    break
                except Exception:
                    continue
            await asyncio.sleep(0.5)

            await send_message({"type": "status", "step": "Extracting Token", "step_num": 3, "total": 3})
            try:
                await page.click("button:has-text('Create Token'), button[type='submit']", timeout=6000)
                await asyncio.sleep(2.5)
            except Exception:
                pass

            token = ""
            for selector in ["input[type='text'][readonly]", "input[type='text'][value]",
                              "[data-testid='token-value']", "code", ".copyable"]:
                try:
                    el = await page.query_selector(selector)
                    if el:
                        val = ((await el.get_attribute("value")) or (await el.inner_text()) or "").strip()
                        if len(val) > 10:
                            token = val
                            break
                except Exception:
                    continue

            if not token:
                await send_message({"type": "error", "message": "Could not extract Vercel token."})
                return {"error": "token_extraction_failed"}

            _save_founder_credentials(founder_id, "vercel", {"token": token})
            result = {"status": "connected", "token_prefix": token[:8] + "…"}
            await send_message({"type": "done", **result})

        except Exception as e:
            logger.error("Vercel connect error: %s", e, exc_info=True)
            await send_message({"type": "error", "message": str(e)})
            result = {"error": str(e)}
        finally:
            stop_forward[0] = True
            if forward_task:
                forward_task.cancel()
            try:
                await refs["client"].send("Page.stopScreencast")
            except Exception:
                pass
            await browser.close()

    return result


# ── SendGrid ──────────────────────────────────────────────────────────────────

async def connect_sendgrid_live(
    founder_id: str,
    send_message,
    wait_input,
    event_q: _queue.Queue | None = None,
) -> dict:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        await send_message({"type": "error", "message": "playwright not installed"})
        return {"error": "playwright not installed"}

    result: dict = {}
    async with async_playwright() as pw:
        browser = await _launch_browser(pw)
        context = await _new_context(browser)
        page = await context.new_page()

        refs: dict = {}
        await _attach_screencast(context, page, send_message, refs)
        await _setup_popup_tracking(context, page, send_message, refs)

        stop_forward = [False]
        forward_task = None
        if event_q is not None:
            forward_task = asyncio.create_task(_input_forward_loop(refs, event_q, stop_forward))

        try:
            await send_message({
                "type": "user_control",
                "step": "Login",
                "step_num": 1,
                "total": 3,
                "message": "Sign in to SendGrid — use any method.",
            })
            await page.goto("https://app.sendgrid.com/login", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(1)

            logged_in = await _wait_for_login(page, "sendgrid.com", "/login", timeout=300)
            if not logged_in:
                await send_message({"type": "error", "message": "Login timed out."})
                return {"error": "login_timeout"}

            stop_forward[0] = True
            await send_message({"type": "status", "step": "Creating API Key", "step_num": 2, "total": 3})
            await page.goto("https://app.sendgrid.com/settings/api_keys", wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(1.5)

            try:
                await page.click("button:has-text('Create API Key')", timeout=8000)
                await asyncio.sleep(1.2)
            except Exception:
                pass

            try:
                await page.fill("input[placeholder*='API Key Name' i], input[name='name']", "Astra", timeout=5000)
                await asyncio.sleep(0.5)
            except Exception:
                pass

            try:
                await page.click("label:has-text('Full Access')", timeout=4000)
                await asyncio.sleep(0.5)
            except Exception:
                pass

            await send_message({"type": "status", "step": "Extracting Key", "step_num": 3, "total": 3})
            try:
                await page.click("button:has-text('Create & View')", timeout=6000)
                await asyncio.sleep(2.5)
            except Exception:
                pass

            api_key = ""
            for selector in ["[data-key-value]", ".api-key-copy", "input[readonly]", "code", ".clipboard-key"]:
                try:
                    el = await page.query_selector(selector)
                    if el:
                        val = ((await el.get_attribute("value")) or (await el.inner_text()) or "").strip()
                        if val.startswith("SG."):
                            api_key = val
                            break
                except Exception:
                    continue

            if not api_key:
                await send_message({"type": "error", "message": "Could not extract SendGrid API key."})
                return {"error": "key_extraction_failed"}

            _save_founder_credentials(founder_id, "sendgrid", {"api_key": api_key})
            result = {"status": "connected", "key_prefix": api_key[:12] + "…"}
            await send_message({"type": "done", **result})

        except Exception as e:
            logger.error("SendGrid connect error: %s", e, exc_info=True)
            await send_message({"type": "error", "message": str(e)})
            result = {"error": str(e)}
        finally:
            stop_forward[0] = True
            if forward_task:
                forward_task.cancel()
            try:
                await refs["client"].send("Page.stopScreencast")
            except Exception:
                pass
            await browser.close()

    return result


# ── Composio per-app connection status ────────────────────────────────────────

def get_composio_app_status(founder_id: str) -> dict[str, bool]:
    """Check which Composio apps are connected for this founder."""
    import requests as _req
    from backend.tools.composio_tools import _resolve_composio_key

    api_key = _resolve_composio_key()
    if not api_key:
        return {}
    try:
        r = _req.get(
            "https://backend.composio.dev/api/v3/connected_accounts",
            headers={"X-API-KEY": api_key},
            params={"user_id": founder_id, "limit": 100},
            timeout=10,
        )
        r.raise_for_status()
        # Multiple records per slug exist (old EXPIRED + new ACTIVE).
        # Any ACTIVE record means the app is connected — don't let a later EXPIRED entry clobber it.
        active: set[str] = set()
        seen: set[str] = set()
        for acc in r.json().get("items", []):
            slug = (acc.get("toolkit") or {}).get("slug", "")
            if not slug:
                continue
            seen.add(slug)
            if acc.get("status") == "ACTIVE":
                active.add(slug)
        return {slug: slug in active for slug in seen}
    except Exception as e:
        logger.warning("Composio status check failed: %s", e)
        return {}
