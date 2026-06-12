"""
Browser-based auto-provisioning for new integration API keys.

Follows integration_connect.py pattern: user-controlled login phase,
bot-controlled key extraction phase, credentials saved to store.

Supported: klaviyo, printful, yelp, lemonsqueezy, square_sandbox
Not supported (phone verification required): twilio — returns setup guide only
"""
import asyncio
import logging
import queue as _queue

from backend.tools.integration_connect import (
    _launch_browser,
    _new_context,
    _attach_screencast,
    _setup_popup_tracking,
    _input_forward_loop,
    _wait_for_login,
    _save_founder_credentials,
)

logger = logging.getLogger(__name__)


# ── Klaviyo ───────────────────────────────────────────────────────────────────

async def provision_klaviyo_live(
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
                "message": "Sign in to Klaviyo (or create a free account at klaviyo.com)",
            })
            await page.goto("https://www.klaviyo.com/login", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(1)

            logged_in = await _wait_for_login(page, "klaviyo.com", "/login", timeout=300)
            if not logged_in:
                await send_message({"type": "error", "message": "Login timed out."})
                return {"error": "login_timeout"}

            stop_forward[0] = True
            await send_message({"type": "status", "step": "Opening API Keys", "step_num": 2, "total": 3})
            await page.goto("https://www.klaviyo.com/account#api-keys-tab", wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(2)

            # Create private key
            try:
                await page.click("button:has-text('Create Private API Key'), button:has-text('Create API Key')", timeout=8000)
                await asyncio.sleep(1)
                for placeholder in ["Key Name", "Name", "name"]:
                    try:
                        await page.fill(f"input[placeholder='{placeholder}']", "Astra", timeout=3000)
                        break
                    except Exception:
                        continue
                await asyncio.sleep(0.5)
                await page.click("button:has-text('Create'), button[type='submit']", timeout=6000)
                await asyncio.sleep(2)
            except Exception:
                pass

            await send_message({"type": "status", "step": "Extracting Key", "step_num": 3, "total": 3})
            api_key = ""
            for selector in [
                "input[type='text'][readonly]", "input[value^='pk_']",
                "code", "[data-testid='api-key']", ".api-key-value",
            ]:
                try:
                    el = await page.query_selector(selector)
                    if el:
                        val = ((await el.get_attribute("value")) or (await el.inner_text()) or "").strip()
                        if len(val) > 10:
                            api_key = val
                            break
                except Exception:
                    continue

            if not api_key:
                await send_message({"type": "error", "message": "Could not extract Klaviyo API key — copy it manually from account settings."})
                return {"error": "key_extraction_failed"}

            _save_founder_credentials(founder_id, "klaviyo", {"api_key": api_key})
            result = {"status": "connected", "service": "klaviyo", "key_prefix": api_key[:8] + "…"}
            await send_message({"type": "done", **result})

        except Exception as e:
            logger.error("Klaviyo provision error: %s", e, exc_info=True)
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


# ── Printful ──────────────────────────────────────────────────────────────────

async def provision_printful_live(
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
                "message": "Sign in to Printful (or create a free account at printful.com)",
            })
            await page.goto("https://www.printful.com/auth/login", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(1)

            logged_in = await _wait_for_login(page, "printful.com", "/auth/login", timeout=300)
            if not logged_in:
                await send_message({"type": "error", "message": "Login timed out."})
                return {"error": "login_timeout"}

            stop_forward[0] = True
            await send_message({"type": "status", "step": "Opening API Keys", "step_num": 2, "total": 3})
            await page.goto("https://www.printful.com/dashboard/settings/api", wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(2)

            try:
                await page.click("button:has-text('Enable API Access'), button:has-text('Generate')", timeout=6000)
                await asyncio.sleep(2)
            except Exception:
                pass

            await send_message({"type": "status", "step": "Extracting Key", "step_num": 3, "total": 3})
            api_key = ""
            for selector in [
                "input[type='text'][readonly]", "input[readonly]",
                "code", ".api-key", "[data-testid='api-key']",
            ]:
                try:
                    el = await page.query_selector(selector)
                    if el:
                        val = ((await el.get_attribute("value")) or (await el.inner_text()) or "").strip()
                        if len(val) > 10:
                            api_key = val
                            break
                except Exception:
                    continue

            if not api_key:
                await send_message({"type": "error", "message": "Could not extract Printful API key — copy from Dashboard → Settings → API."})
                return {"error": "key_extraction_failed"}

            _save_founder_credentials(founder_id, "printful", {"api_key": api_key})
            result = {"status": "connected", "service": "printful", "key_prefix": api_key[:8] + "…"}
            await send_message({"type": "done", **result})

        except Exception as e:
            logger.error("Printful provision error: %s", e, exc_info=True)
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


# ── Yelp ──────────────────────────────────────────────────────────────────────

async def provision_yelp_live(
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
                "message": "Sign in to Yelp Fusion (create free account at fusion.yelp.com if needed — 500 req/day free)",
            })
            await page.goto("https://fusion.yelp.com/", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(1)

            # Yelp Fusion redirects to yelp.com login then back
            logged_in = await _wait_for_login(page, "fusion.yelp.com", "login", timeout=300)
            if not logged_in:
                # Try broader check — may land on manage apps page directly
                for _ in range(10):
                    try:
                        url = page.url
                        if "fusion.yelp.com" in url and "login" not in url:
                            logged_in = True
                            break
                    except Exception:
                        pass
                    await asyncio.sleep(2)

            if not logged_in:
                await send_message({"type": "error", "message": "Login timed out."})
                return {"error": "login_timeout"}

            stop_forward[0] = True
            await send_message({"type": "status", "step": "Opening App Manager", "step_num": 2, "total": 3})
            await page.goto("https://www.yelp.com/developers/v3/manage_app", wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(2)

            # Create app if none exists
            try:
                create_btn = await page.query_selector("a:has-text('Create New App'), button:has-text('Create App')")
                if create_btn:
                    await create_btn.click()
                    await asyncio.sleep(1)
                    for name_sel in ["input[name='app_name']", "input[placeholder='App Name']"]:
                        try:
                            await page.fill(name_sel, "Astra", timeout=3000)
                            break
                        except Exception:
                            continue
                    for industry_sel in ["select[name='industry_name']"]:
                        try:
                            await page.select_option(industry_sel, index=1, timeout=3000)
                            break
                        except Exception:
                            continue
                    for contact_sel in ["input[name='contact_email']", "input[type='email']"]:
                        try:
                            from backend.config import settings
                            email = getattr(settings, "test_email_base", "") or ""
                            if email:
                                await page.fill(contact_sel, email, timeout=3000)
                            break
                        except Exception:
                            continue
                    try:
                        await page.check("input[type='checkbox']", timeout=3000)
                    except Exception:
                        pass
                    try:
                        await page.click("button[type='submit'], button:has-text('Submit')", timeout=6000)
                        await asyncio.sleep(3)
                    except Exception:
                        pass
            except Exception:
                pass

            await send_message({"type": "status", "step": "Extracting Key", "step_num": 3, "total": 3})
            api_key = ""
            for selector in [
                "input[name='api_key']", "input[readonly][value]",
                "code", ".api-key", "[data-testid='api-key']",
                "p:has-text('API Key') + code",
            ]:
                try:
                    el = await page.query_selector(selector)
                    if el:
                        val = ((await el.get_attribute("value")) or (await el.inner_text()) or "").strip()
                        if len(val) > 10:
                            api_key = val
                            break
                except Exception:
                    continue

            # Fallback: scan visible text for key-like string
            if not api_key:
                try:
                    content = await page.content()
                    import re
                    matches = re.findall(r'[A-Za-z0-9_-]{40,}', content)
                    for m in matches:
                        if len(m) >= 40:
                            api_key = m
                            break
                except Exception:
                    pass

            if not api_key:
                await send_message({"type": "error", "message": "Could not extract Yelp API key — copy from Manage App page."})
                return {"error": "key_extraction_failed"}

            _save_founder_credentials(founder_id, "yelp", {"api_key": api_key})
            result = {"status": "connected", "service": "yelp", "key_prefix": api_key[:8] + "…"}
            await send_message({"type": "done", **result})

        except Exception as e:
            logger.error("Yelp provision error: %s", e, exc_info=True)
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


# ── Lemon Squeezy ─────────────────────────────────────────────────────────────

async def provision_lemonsqueezy_live(
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
                "message": "Sign in to Lemon Squeezy (or create a free account at app.lemonsqueezy.com)",
            })
            await page.goto("https://app.lemonsqueezy.com/login", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(1)

            logged_in = await _wait_for_login(page, "app.lemonsqueezy.com", "/login", timeout=300)
            if not logged_in:
                await send_message({"type": "error", "message": "Login timed out."})
                return {"error": "login_timeout"}

            stop_forward[0] = True
            await send_message({"type": "status", "step": "Opening API Keys", "step_num": 2, "total": 3})
            await page.goto("https://app.lemonsqueezy.com/settings/api", wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(2)

            try:
                await page.click("button:has-text('+ Add API key'), button:has-text('Create')", timeout=6000)
                await asyncio.sleep(1)
                for name_sel in ["input[placeholder='Key name']", "input[name='name']"]:
                    try:
                        await page.fill(name_sel, "Astra", timeout=3000)
                        break
                    except Exception:
                        continue
                await asyncio.sleep(0.5)
                await page.click("button:has-text('Create API key'), button[type='submit']", timeout=6000)
                await asyncio.sleep(2)
            except Exception:
                pass

            await send_message({"type": "status", "step": "Extracting Key", "step_num": 3, "total": 3})
            api_key = ""
            for selector in [
                "input[type='text'][readonly]", "input[readonly]",
                "code", ".api-key-value", "[data-testid='api-key']",
            ]:
                try:
                    el = await page.query_selector(selector)
                    if el:
                        val = ((await el.get_attribute("value")) or (await el.inner_text()) or "").strip()
                        if val.startswith("eyJ") or len(val) > 20:
                            api_key = val
                            break
                except Exception:
                    continue

            if not api_key:
                await send_message({"type": "error", "message": "Could not extract Lemon Squeezy API key — copy from Settings → API."})
                return {"error": "key_extraction_failed"}

            _save_founder_credentials(founder_id, "lemonsqueezy", {"api_key": api_key})
            result = {"status": "connected", "service": "lemonsqueezy", "key_prefix": api_key[:8] + "…"}
            await send_message({"type": "done", **result})

        except Exception as e:
            logger.error("Lemon Squeezy provision error: %s", e, exc_info=True)
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


# ── Square (sandbox) ──────────────────────────────────────────────────────────

async def provision_square_sandbox_live(
    founder_id: str,
    send_message,
    wait_input,
    event_q: _queue.Queue | None = None,
) -> dict:
    """
    Provisions Square sandbox credentials (instant — no business verification).
    Sandbox access token starts with 'EAAAlb...' pattern.
    """
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
                "message": "Sign in to Square Developer (developer.squareup.com — free, no business verification needed for sandbox)",
            })
            await page.goto("https://developer.squareup.com/apps", wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(1)

            logged_in = await _wait_for_login(page, "developer.squareup.com", "login", timeout=300)
            if not logged_in:
                for _ in range(10):
                    try:
                        url = page.url
                        if "squareup.com" in url and "login" not in url:
                            logged_in = True
                            break
                    except Exception:
                        pass
                    await asyncio.sleep(2)

            if not logged_in:
                await send_message({"type": "error", "message": "Login timed out."})
                return {"error": "login_timeout"}

            stop_forward[0] = True
            await send_message({"type": "status", "step": "Finding Sandbox Token", "step_num": 2, "total": 3})
            await page.goto("https://developer.squareup.com/apps", wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(2)

            # Create app if none
            try:
                new_app = await page.query_selector("button:has-text('Create Your First Application'), a:has-text('New Application')")
                if new_app:
                    await new_app.click()
                    await asyncio.sleep(1)
                    try:
                        await page.fill("input[name='applicationName'], input[placeholder*='name']", "Astra", timeout=3000)
                    except Exception:
                        pass
                    try:
                        await page.click("button:has-text('Save'), button[type='submit']", timeout=5000)
                        await asyncio.sleep(2)
                    except Exception:
                        pass
            except Exception:
                pass

            # Navigate into first app
            try:
                app_link = await page.query_selector("a[href*='/apps/']")
                if app_link:
                    href = await app_link.get_attribute("href")
                    if href:
                        await page.goto(f"https://developer.squareup.com{href}/overview", wait_until="domcontentloaded", timeout=15000)
                        await asyncio.sleep(1.5)
            except Exception:
                pass

            await send_message({"type": "status", "step": "Extracting Sandbox Token", "step_num": 3, "total": 3})
            token = ""
            for selector in [
                "input[id*='sandbox'][readonly]", "input[value^='EAAAlb']",
                "input[type='text'][readonly]", "code",
            ]:
                try:
                    el = await page.query_selector(selector)
                    if el:
                        val = ((await el.get_attribute("value")) or (await el.inner_text()) or "").strip()
                        if len(val) > 20:
                            token = val
                            break
                except Exception:
                    continue

            if not token:
                await send_message({"type": "error", "message": "Could not extract Square sandbox token — copy from Developer Dashboard → Sandbox."})
                return {"error": "key_extraction_failed"}

            _save_founder_credentials(founder_id, "square", {"access_token": token, "environment": "sandbox"})
            result = {"status": "connected", "service": "square", "environment": "sandbox", "token_prefix": token[:8] + "…"}
            await send_message({"type": "done", **result})

        except Exception as e:
            logger.error("Square provision error: %s", e, exc_info=True)
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


# ── Twilio (guide only — phone verification required) ─────────────────────────

def provision_twilio_guide(founder_id: str) -> dict:
    """
    Twilio requires phone number verification; cannot be automated.
    Returns a setup guide instead.
    """
    return {
        "service": "twilio",
        "status": "manual_required",
        "reason": "Twilio requires a verified phone number — cannot be automated.",
        "steps": [
            "1. Go to twilio.com/try-twilio and sign up (free trial includes $15 credit)",
            "2. Verify your phone number when prompted",
            "3. In Console → Account Info, copy Account SID and Auth Token",
            "4. Get a free phone number: Console → Phone Numbers → Manage → Buy a Number",
            "5. Paste Account SID, Auth Token in Astra Settings → Integrations → Twilio",
        ],
        "free_tier": "Trial: $15 credit. SMS ~$0.008/msg (user-paid, not Astra's cost).",
    }


# ── Dispatcher ────────────────────────────────────────────────────────────────

PROVISION_FLOWS = {
    "klaviyo": provision_klaviyo_live,
    "printful": provision_printful_live,
    "yelp": provision_yelp_live,
    "lemonsqueezy": provision_lemonsqueezy_live,
    "square": provision_square_sandbox_live,
}


async def provision_integration_live(
    service: str,
    founder_id: str,
    send_message,
    wait_input,
    event_q: _queue.Queue | None = None,
) -> dict:
    """
    Entry point. Call with service name, returns credentials result.
    Twilio returns a guide dict synchronously (no browser needed).
    """
    if service == "twilio":
        result = provision_twilio_guide(founder_id)
        await send_message({"type": "done", **result})
        return result

    fn = PROVISION_FLOWS.get(service)
    if fn is None:
        msg = f"Unknown service '{service}'. Supported: {list(PROVISION_FLOWS.keys()) + ['twilio']}"
        await send_message({"type": "error", "message": msg})
        return {"error": msg}

    return await fn(founder_id, send_message, wait_input, event_q)
