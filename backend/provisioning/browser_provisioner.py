"""
Headless browser provisioner.
Creates GitHub, Vercel, SendGrid accounts with founder email+password,
extracts API tokens, returns them.
"""
import logging
import secrets
import time
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_COMPOSIO_APP_SERVICE_MAP: dict[str, tuple[str, ...]] = {
    "gmail": ("gmail",),
    "google_drive": ("google_drive", "google_sheets"),
    "googlecalendar": ("google_calendar",),
    "notion": ("notion",),
    "linear": ("linear", "product_tracker"),
    "linkedin": ("linkedin",),
}

_STEALTH_ARGS = [
    "--no-sandbox",
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars",
    "--disable-dev-shm-usage",
    "--disable-setuid-sandbox",
    "--disable-web-security",
    "--disable-features=IsolateOrigins,site-per-process",
    "--flag-switches-begin",
    "--disable-site-isolation-trials",
    "--flag-switches-end",
    "--window-size=1366,768",
]

# JS injected before every page load to patch automation fingerprints
_STEALTH_JS = """
// Remove webdriver flag
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

// Restore chrome runtime object that headless strips
window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){}, app: {} };

// Realistic plugins list
Object.defineProperty(navigator, 'plugins', {
  get: () => {
    const arr = [
      { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
      { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
      { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' },
    ];
    arr.__proto__ = PluginArray.prototype;
    return arr;
  }
});

// Realistic languages
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });

// Hide automation in permissions
const originalQuery = window.navigator.permissions ? window.navigator.permissions.query : null;
if (originalQuery) {
  window.navigator.permissions.query = (parameters) =>
    parameters.name === 'notifications'
      ? Promise.resolve({ state: Notification.permission })
      : originalQuery(parameters);
}
"""


def _launch_options() -> dict:
    from backend.config import settings

    args = list(_STEALTH_ARGS)
    headless = settings.browser_headless
    ext = (settings.capsolver_extension_path or "").strip()
    # Extension works in non-headless; in headless we use the CapSolver API instead
    if ext and Path(ext).exists() and not headless:
        args.extend([
            f"--disable-extensions-except={ext}",
            f"--load-extension={ext}",
        ])
    proxy_server = (settings.browser_proxy_server or "").strip()
    proxy_username = (settings.browser_proxy_username or "").strip()
    proxy_password = (settings.browser_proxy_password or "").strip()
    options: dict[str, object] = {"headless": headless, "args": args}
    if proxy_server:
        options["proxy"] = {
            "server": proxy_server,
            **({"username": proxy_username} if proxy_username else {}),
            **({"password": proxy_password} if proxy_password else {}),
        }
    return options


def _new_stealth_context(browser, user_agent: str | None = None):
    """Create a browser context with stealth patches applied to every page."""
    ctx = browser.new_context(
        user_agent=user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1366, "height": 768},
        locale="en-US",
        timezone_id="America/New_York",
        java_script_enabled=True,
    )
    ctx.add_init_script(_STEALTH_JS)
    return ctx


def _human_delay(page, lo: float = 0.8, hi: float = 2.4) -> None:
    """Random human-like pause — avoids the fixed-2000ms bot timing fingerprint."""
    import random
    ms = int(random.uniform(lo, hi) * 1000)
    page.wait_for_timeout(ms)


def _solve_turnstile(page, site_key: str | None = None, site_url: str | None = None) -> bool:
    """
    Attempt to solve a Cloudflare Turnstile using the CapSolver API.
    Returns True if a token was injected, False if unavailable or failed.
    """
    from backend.config import settings
    api_key = (settings.capsolver_api_key or "").strip()
    if not api_key:
        return False
    try:
        import requests as _req
        url = site_url or page.url
        # Auto-detect the site key from the page if not provided
        if not site_key:
            try:
                el = page.locator("[data-sitekey]").first
                if el.count() > 0:
                    site_key = el.get_attribute("data-sitekey")
            except Exception:
                pass
        if not site_key:
            try:
                content = page.content()
                import re
                m = re.search(r'sitekey["\s:=]+["\']([0-9a-f\-]{20,})["\']', content, re.I)
                if m:
                    site_key = m.group(1)
            except Exception:
                pass
        if not site_key:
            logger.warning("Turnstile: could not find site key on %s", url)
            return False

        # Create task
        resp = _req.post(
            "https://api.capsolver.com/createTask",
            json={
                "clientKey": api_key,
                "task": {
                    "type": "AntiTurnstileTaskProxyLess",
                    "websiteURL": url,
                    "websiteKey": site_key,
                },
            },
            timeout=15,
        )
        task_id = resp.json().get("taskId")
        if not task_id:
            logger.warning("CapSolver: no taskId returned: %s", resp.text[:200])
            return False

        # Poll for result (up to 90s)
        for _ in range(30):
            time.sleep(3)
            r = _req.post(
                "https://api.capsolver.com/getTaskResult",
                json={"clientKey": api_key, "taskId": task_id},
                timeout=10,
            )
            data = r.json()
            if data.get("status") == "ready":
                token = data.get("solution", {}).get("token")
                if token:
                    # Inject into the page
                    page.evaluate(f"""
                        (() => {{
                            const resp = document.querySelector('[name="cf-turnstile-response"]');
                            if (resp) resp.value = {token!r};
                            const cb = window.__cfTurnstileCallback || window.turnstileCallback;
                            if (cb) cb({token!r});
                        }})()
                    """)
                    logger.info("Turnstile solved via CapSolver API")
                    return True
                break
            if data.get("status") == "failed":
                logger.warning("CapSolver task failed: %s", data.get("errorDescription"))
                break

    except Exception as exc:
        logger.warning("CapSolver Turnstile solve error: %s", exc)
    return False


def provision_github(email: str, password: str, username: str = None, imap_password: str = None) -> dict:
    """
    Create GitHub account + personal access token.
    Returns {"token": "ghp_...", "username": "...", "created": bool}
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    username = username or _slug(email)

    with sync_playwright() as p:
        browser = p.chromium.launch(**_launch_options())
        ctx = _new_stealth_context(browser)
        page = ctx.new_page()

        try:
            # --- Attempt login first (account may already exist) ---
            page.goto("https://github.com/login", timeout=30000)
            _human_delay(page, 0.5, 1.2)
            page.fill("input#login_field", email)
            _human_delay(page, 0.3, 0.7)
            page.fill("input#password", password)
            _human_delay(page, 0.4, 0.9)
            page.click("input[type=submit]")
            _human_delay(page, 2.0, 4.0)

            logged_in = "github.com" in page.url and "login" not in page.url and "session" not in page.url

            if not logged_in:
                # --- Sign up flow (GitHub stepped form) ---
                page.goto("https://github.com/signup", timeout=30000)
                _human_delay(page, 1.5, 3.0)

                # Step 1: email
                email_input = page.locator("input[name='user[email]'], input#email, input[type=email]").first
                email_input.wait_for(timeout=10000)
                email_input.fill(email)
                page.keyboard.press("Tab")
                _human_delay(page, 0.4, 1.0)

                # Step 2: password (may be on same page or next step)
                pwd_input = page.locator("input[name='user[password]'], input#password, input[type=password]").first
                if pwd_input.count() > 0:
                    pwd_input.fill(password)
                    page.keyboard.press("Tab")
                    _human_delay(page, 0.4, 1.0)

                # Step 3: username
                uname_input = page.locator("input[name='user[login]'], input#login, input[autocomplete=username]").first
                if uname_input.count() > 0:
                    uname_input.fill(username)
                    page.keyboard.press("Tab")
                    _human_delay(page, 0.4, 1.0)

                # Handle any Turnstile/captcha before submitting
                _try_solve_turnstile(page)

                # Submit
                submit = page.locator("button[type=submit]").first
                submit.click()
                _human_delay(page, 2.5, 4.5)

                # GitHub requires email verification before anything else
                needs_verify = (
                    "verify" in page.url
                    or "email" in page.url
                    or page.locator("text=verify your email").count() > 0
                    or page.locator("text=Check your email").count() > 0
                )
                if needs_verify:
                    if imap_password:
                        from backend.testing.email_reader import (
                            wait_for_verification_url,
                            wait_for_verification_code,
                        )
                        # GitHub may show an OTP input field (code) or a link in email
                        otp_input = page.locator("input[autocomplete='one-time-code'], input[name='otp'], input[maxlength='6']").first
                        if otp_input.count() > 0:
                            # OTP code flow
                            code = wait_for_verification_code(email, imap_password, "github", timeout=300)
                            if code:
                                otp_input.fill(code)
                                page.keyboard.press("Enter")
                                _human_delay(page, 2.0, 3.5)
                            else:
                                browser.close()
                                return {
                                    "token": None, "username": username, "created": False,
                                    "needs_verification": True,
                                    "note": "GitHub OTP code not received within 5 minutes.",
                                }
                        else:
                            # Link-in-email flow
                            verify_url = wait_for_verification_url(email, imap_password, "github", timeout=300)
                            if verify_url:
                                page.goto(verify_url, timeout=30000)
                                _human_delay(page, 2.0, 3.5)
                            else:
                                browser.close()
                                return {
                                    "token": None, "username": username, "created": False,
                                    "needs_verification": True,
                                    "note": "Verification email not received within 5 minutes.",
                                }
                    else:
                        browser.close()
                        return {
                            "token": None,
                            "username": username,
                            "created": False,
                            "needs_verification": True,
                            "note": "GitHub sent a verification email to %s. Verify then reconnect." % email,
                        }

                # Re-attempt login after signup
                page.goto("https://github.com/login", timeout=30000)
                _human_delay(page, 0.8, 1.5)
                page.fill("input#login_field", email)
                _human_delay(page, 0.3, 0.6)
                page.fill("input#password", password)
                _human_delay(page, 0.3, 0.6)
                page.click("input[type=submit]")
                _human_delay(page, 2.0, 3.5)
                logged_in = "login" not in page.url

            if not logged_in:
                browser.close()
                return {"token": None, "created": False, "error": "Login failed after signup"}

            # Read actual username from DOM
            actual_username = (
                page.locator("meta[name='user-login']").get_attribute("content")
                or page.locator("[data-login]").first.get_attribute("data-login")
                or username
            )

            # --- Create fine-grained personal access token ---
            page.goto("https://github.com/settings/personal-access-tokens/new", timeout=30000)
            _human_delay(page, 1.5, 2.8)

            name_field = page.locator("input#token_nickname, input[name='token[nickname]']").first
            if name_field.count() > 0:
                name_field.fill("Astra Automation Token")

            # Fallback: classic token page
            classic = page.locator("input#oauth_access_description, input[name='oauth_access[description]']").first
            if classic.count() > 0:
                classic.fill("Astra Automation Token")
                page.locator("input#repo").check()
                exp = page.locator("select[name='oauth_access[expires_at]']")
                if exp.count() > 0:
                    exp.select_option(index=0)  # first option = no expiry or longest

            page.locator("button[type=submit]").last.click()
            _human_delay(page, 1.5, 2.8)

            # Extract token
            token_el = page.locator("code#new-oauth-token, [data-value], input.js-token-value").first
            token = None
            if token_el.count() > 0:
                token = token_el.text_content() or token_el.get_attribute("value")

            browser.close()
            return {
                "token": token,
                "username": actual_username,
                "created": True,
                "note": "Token created." if token else "Token extraction failed — create at github.com/settings/tokens",
            }

        except PWTimeout as e:
            logger.error("GitHub provisioning timed out: %s", e)
            browser.close()
            return {"token": None, "created": False, "error": "Timeout: %s" % str(e)}
        except Exception as e:
            logger.error("GitHub provisioning failed: %s", e)
            try:
                browser.close()
            except Exception:
                pass
            return {"token": None, "created": False, "error": str(e)}


def provision_vercel(email: str, password: str, github_token: str = None, imap_password: str = None) -> dict:
    """
    Sign into Vercel (via GitHub OAuth or email) and extract API token.
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    with sync_playwright() as p:
        browser = p.chromium.launch(**_launch_options())
        ctx = _new_stealth_context(browser)
        page = ctx.new_page()

        try:
            page.goto("https://vercel.com/login", timeout=30000)
            _human_delay(page, 1.0, 2.0)

            if github_token:
                # Continue with GitHub
                page.click("button:has-text('Continue with GitHub')")
                _human_delay(page, 2.0, 3.5)
                # GitHub OAuth redirect
                if "github.com" in page.url:
                    page.fill("input#login_field", email)
                    _human_delay(page, 0.3, 0.7)
                    page.fill("input#password", password)
                    _human_delay(page, 0.3, 0.6)
                    page.click("input[type=submit]")
                    _human_delay(page, 2.0, 3.0)
                    # Authorize if prompted
                    auth_btn = page.locator("button:has-text('Authorize')")
                    if auth_btn.count() > 0:
                        auth_btn.click()
                        _human_delay(page, 1.5, 2.5)
            else:
                page.click("button:has-text('Continue with Email')")
                _human_delay(page, 0.5, 1.0)
                page.fill("input[type=email]", email)
                _human_delay(page, 0.3, 0.6)
                page.click("button[type=submit]")
                _human_delay(page, 1.5, 2.5)
                if imap_password:
                    from backend.testing.email_reader import wait_for_verification_url
                    magic_url = wait_for_verification_url(email, imap_password, "vercel", timeout=300)
                    if magic_url:
                        page.goto(magic_url, timeout=30000)
                        _human_delay(page, 3.0, 5.0)
                    else:
                        browser.close()
                        return {
                            "token": None, "created": False, "needs_email_link": True,
                            "note": "Vercel magic link not received within 5 minutes.",
                        }
                else:
                    browser.close()
                    return {
                        "token": None,
                        "created": False,
                        "needs_email_link": True,
                        "note": "Vercel sent a magic link to %s. Click it then reconnect." % email,
                    }

            # Extract token from account settings
            page.goto("https://vercel.com/account/tokens", timeout=30000)
            _human_delay(page, 1.5, 2.5)

            # Click create token
            create_btn = page.locator("button:has-text('Create')")
            if create_btn.count() > 0:
                create_btn.click()
                _human_delay(page, 0.8, 1.5)
                page.fill("input[placeholder*='Token Name']", "Astra Deploy Token")
                _human_delay(page, 0.3, 0.6)
                page.click("button:has-text('Create Token')")
                _human_delay(page, 1.0, 2.0)
                token_el = page.locator("input[readonly]").first
                token = token_el.input_value() if token_el.count() > 0 else None
            else:
                token = None

            browser.close()
            return {
                "token": token,
                "created": token is not None,
                "note": "Vercel deploy token created." if token else "Token extraction failed — create at vercel.com/account/tokens",
            }

        except PWTimeout as e:
            try:
                browser.close()
            except Exception:
                pass
            return {"token": None, "created": False, "error": "Timeout"}
        except Exception as e:
            try:
                browser.close()
            except Exception:
                pass
            return {"token": None, "created": False, "error": str(e)}


def provision_sendgrid(email: str, password: str, imap_password: str = None) -> dict:
    """
    Create SendGrid account and extract API key.
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    with sync_playwright() as p:
        browser = p.chromium.launch(**_launch_options())
        ctx = _new_stealth_context(browser)
        page = ctx.new_page()

        try:
            page.goto("https://signup.sendgrid.com/", timeout=30000)
            _human_delay(page, 1.5, 3.0)
            page.fill("input[name='email']", email)
            _human_delay(page, 0.3, 0.7)
            page.fill("input[name='password']", password)
            _human_delay(page, 0.3, 0.6)

            # Fill required fields
            username_field = page.locator("input[name='username']")
            if username_field.count() > 0:
                username_field.fill(_slug(email))
                _human_delay(page, 0.3, 0.6)

            _try_solve_turnstile(page)
            page.click("button[type=submit]")
            _human_delay(page, 2.5, 4.0)

            if "app.sendgrid.com" not in page.url:
                if imap_password:
                    from backend.testing.email_reader import wait_for_verification_url
                    verify_url = wait_for_verification_url(email, imap_password, "sendgrid", timeout=300)
                    if verify_url:
                        page.goto(verify_url, timeout=30000)
                        _human_delay(page, 3.0, 5.0)
                        # If still not on dashboard, bail
                        if "app.sendgrid.com" not in page.url:
                            browser.close()
                            return {
                                "api_key": None, "created": False, "needs_verification": True,
                                "note": "SendGrid verification link did not redirect to dashboard.",
                            }
                    else:
                        browser.close()
                        return {
                            "api_key": None, "created": False, "needs_verification": True,
                            "note": "SendGrid verification email not received within 5 minutes.",
                        }
                else:
                    browser.close()
                    return {
                        "api_key": None,
                        "created": False,
                        "needs_verification": True,
                        "note": "SendGrid sent a verification email to %s. Verify then reconnect." % email,
                    }

            # Create API key
            page.goto("https://app.sendgrid.com/settings/api_keys", timeout=30000)
            _human_delay(page, 1.5, 2.8)
            page.click("button:has-text('Create API Key')")
            _human_delay(page, 0.7, 1.4)
            page.fill("input[name='name']", "Astra Marketing Key")
            # Full access
            page.click("label:has-text('Full Access')")
            page.click("button:has-text('Create & View')")
            _human_delay(page, 1.5, 2.8)

            key_el = page.locator(".api-key-text, code, input[readonly]").first
            api_key = key_el.text_content() or key_el.input_value() if key_el.count() > 0 else None

            browser.close()
            return {
                "api_key": api_key,
                "created": api_key is not None,
                "note": "SendGrid key created." if api_key else "Key extraction failed — create at app.sendgrid.com/settings/api_keys",
            }

        except Exception as e:
            try:
                browser.close()
            except Exception:
                pass
            return {"api_key": None, "created": False, "error": str(e)}


def provision_composio(email: str, password: str) -> dict:
    """
    Sign up for / log into Composio via GitHub OAuth and extract the API key.
    Returns {"api_key": "...", "created": bool}
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    with sync_playwright() as p:
        browser = p.chromium.launch(**_launch_options())
        ctx = _new_stealth_context(browser)
        page = ctx.new_page()

        try:
            page.goto("https://app.composio.dev/login", timeout=30000)
            _human_delay(page, 1.5, 2.5)

            # Click "Continue with GitHub"
            github_btn = page.locator(
                "button:has-text('GitHub'), a:has-text('GitHub'), "
                "button:has-text('Continue with GitHub'), a:has-text('Continue with GitHub')"
            ).first
            if github_btn.count() > 0:
                github_btn.click()
                _human_delay(page, 2.5, 4.0)
            else:
                # Try direct GitHub OAuth URL pattern used by many SaaS
                page.goto("https://app.composio.dev/auth/github", timeout=30000)
                _human_delay(page, 2.0, 3.5)

            # GitHub OAuth consent screen
            if "github.com" in page.url:
                login_field = page.locator("input#login_field, input[name='login']").first
                if login_field.count() > 0:
                    login_field.fill(email)
                    _human_delay(page, 0.3, 0.6)
                pwd_field = page.locator("input#password, input[name='password']").first
                if pwd_field.count() > 0:
                    pwd_field.fill(password)
                    _human_delay(page, 0.3, 0.6)
                page.locator("input[type=submit], button[type=submit]").first.click()
                _human_delay(page, 2.0, 3.5)

                # Authorize Composio app if consent screen appears
                authorize_btn = page.locator("button:has-text('Authorize'), input[value='Authorize']").first
                if authorize_btn.count() > 0:
                    authorize_btn.click()
                    _human_delay(page, 2.5, 4.0)

            # Wait for redirect back to Composio dashboard
            try:
                page.wait_for_url("**/app.composio.dev/**", timeout=15000)
            except PWTimeout:
                pass  # might already be there

            if "app.composio.dev" not in page.url:
                browser.close()
                return {
                    "api_key": None,
                    "created": False,
                    "error": "Could not authenticate with Composio — check GitHub credentials",
                }

            # Navigate to API key settings
            for settings_url in [
                "https://app.composio.dev/settings",
                "https://app.composio.dev/api-keys",
                "https://app.composio.dev/settings/api-keys",
            ]:
                page.goto(settings_url, timeout=15000)
                _human_delay(page, 1.5, 2.8)

                # Look for existing key or generate new one
                api_key = _extract_composio_key(page)
                if api_key:
                    break

                # Try clicking a generate/create button
                for label in ["Generate API Key", "Create API Key", "New API Key", "Generate", "Create"]:
                    btn = page.locator(f"button:has-text('{label}')").first
                    if btn.count() > 0:
                        btn.click()
                        _human_delay(page, 1.5, 2.8)
                        api_key = _extract_composio_key(page)
                        if api_key:
                            break

                if api_key:
                    break

            browser.close()
            return {
                "api_key": api_key.strip() if api_key else None,
                "created": bool(api_key),
                "note": "Composio API key extracted." if api_key else (
                    "Logged in but key extraction failed — visit app.composio.dev/settings to copy your API key"
                ),
            }

        except PWTimeout as e:
            try:
                browser.close()
            except Exception:
                pass
            return {"api_key": None, "created": False, "error": f"Timeout: {e}"}
        except Exception as e:
            try:
                browser.close()
            except Exception:
                pass
            return {"api_key": None, "created": False, "error": str(e)}


def _extract_composio_key(page) -> str | None:
    """Try various selectors to extract an API key value from the current page."""
    selectors = [
        "input[readonly]",
        "input[type='text'][value^='sk-']",
        "input[type='text'][value^='api-']",
        "[data-testid='api-key']",
        "[data-testid='apiKey']",
        ".api-key",
        "code",
        "span[class*='api']",
        "p[class*='key']",
    ]
    for sel in selectors:
        el = page.locator(sel).first
        if el.count() > 0:
            val = None
            try:
                val = el.input_value()
            except Exception:
                pass
            if not val:
                val = el.text_content()
            if val and len(val) > 20 and " " not in val.strip():
                return val.strip()
    return None


def provision_composio_oauth_apps(
    founder_id: str,
    oauth_urls: dict[str, str],
    email: str,
    password: str,
    imap_password: str | None = None,
    timeout_per_app: int = 180,
) -> dict[str, dict]:
    """Complete provider OAuth flows for Composio apps using founder credentials."""
    from playwright.sync_api import sync_playwright
    from backend.tools.integration_connect import get_composio_app_status

    results: dict[str, dict] = {}
    if not oauth_urls:
        return results

    with sync_playwright() as p:
        browser = p.chromium.launch(**_launch_options())
        ctx = _new_stealth_context(browser)
        page = ctx.new_page()
        try:
            for app, url in oauth_urls.items():
                try:
                    results[app] = _complete_composio_oauth_app(
                        founder_id=founder_id,
                        app=app,
                        url=url,
                        page=page,
                        email=email,
                        password=password,
                        imap_password=imap_password,
                        timeout_seconds=timeout_per_app,
                        get_status=get_composio_app_status,
                    )
                except Exception as e:
                    logger.warning("Composio OAuth auto-connect failed for %s: %s", app, e)
                    results[app] = {"connected": False, "error": str(e)}
        finally:
            browser.close()
    return results


def _complete_composio_oauth_app(
    *,
    founder_id: str,
    app: str,
    url: str,
    page,
    email: str,
    password: str,
    imap_password: str | None,
    timeout_seconds: int,
    get_status,
) -> dict:
    deadline = time.time() + timeout_seconds
    oauth_state: dict[str, float] = {}
    if app == "linear":
        oauth_state["linear_oauth_url"] = url
        page.goto("https://linear.app/signup", timeout=30000)
    else:
        page.goto(url, timeout=30000)
    _human_delay(page, 1.0, 2.0)

    while time.time() < deadline:
        page = _latest_page(page)
        status = get_status(founder_id)
        if status.get(app):
            _persist_connected_composio_app(founder_id, app)
            return {"connected": True, "app": app}

        current = page.url or ""
        host = urlparse(current).netloc.lower()
        page_text = _page_text(page)

        if app == "linear" and _has_turnstile_challenge(page):
            solved = _try_solve_turnstile(page)
            if not solved:
                return _interaction_required_result(
                    app=app,
                    provider="linear",
                    category="anti_bot",
                    detail="Linear signup/login is blocked by a Cloudflare Turnstile challenge that could not be solved automatically.",
                    url=current,
                    state=page_text,
                    next_step="Add CAPSOLVER_API_KEY to env for automatic solving, or complete the challenge in-browser then resume.",
                )
            # Solved — click through any remaining submit buttons
            _click_generic_oauth_buttons(page)

        if "accounts.google.com" in host:
            _handle_google_login(page, email, password)
            if app == "linear" and _is_google_rejected(page):
                page.goto("https://linear.app/signup", timeout=30000)
                _human_delay(page, 1.0, 2.0)
        elif "linkedin.com" in host:
            _handle_linkedin_login(page, email, password)
        elif "notion" in host:
            _handle_notion_login(page, email, password, imap_password)
        elif "linear.app" in host:
            _handle_linear_login(page, email, password, imap_password)
        elif "github.com" in host:
            _handle_github_login(page, email, password)
        elif "app.composio.dev" in host:
            _handle_composio_return(page)

        service = app if app in {"notion", "linear", "github"} else ("google" if "google" in app or app == "gmail" else app)
        _maybe_handle_email_challenge(
            page,
            email,
            imap_password,
            service,
            deadline=deadline,
            state=oauth_state,
            email_password=password,
        )
        _click_generic_oauth_buttons(page)
        _human_delay(page, 2.0, 3.5)

    status = get_status(founder_id)
    if status.get(app):
        _persist_connected_composio_app(founder_id, app)
        return {"connected": True, "app": app}
    return {
        "connected": False,
        "app": app,
        "error": f"Timed out completing OAuth for {app}",
        "last_url": getattr(page, "url", ""),
        "last_state": _page_text(page)[:240],
    }


def _persist_connected_composio_app(founder_id: str, app: str) -> None:
    from backend.provisioning.credentials_store import store_credentials

    for service in _COMPOSIO_APP_SERVICE_MAP.get(app, (app,)):
        store_credentials(founder_id, service, {
            "connected": True,
            "connected_via": "composio_oauth",
            "composio_app": app,
        })


def _interaction_required_result(
    *,
    app: str,
    provider: str,
    category: str,
    detail: str,
    url: str,
    state: str,
    next_step: str,
) -> dict:
    return {
        "connected": False,
        "app": app,
        "provider": provider,
        "status": "interaction_required",
        "requires_human": True,
        "category": category,
        "error": detail,
        "last_url": url,
        "last_state": state[:240],
        "next_step": next_step,
        "resume_supported": True,
    }


def _click_first(page, selectors: list[str]) -> bool:
    for selector in selectors:
        try:
            el = page.locator(selector).first
            if el.count() > 0 and el.is_visible():
                el.click(timeout=4000)
                _human_delay(page, 0.5, 1.1)
                return True
        except Exception:
            continue
    return False


def _click_text(page, labels: list[str]) -> bool:
    selectors = [f"button:has-text('{label}')" for label in labels]
    selectors += [f"a:has-text('{label}')" for label in labels]
    selectors += [f"text={label}" for label in labels]
    return _click_first(page, selectors)


def _fill_first(page, selectors: list[str], value: str) -> bool:
    for selector in selectors:
        try:
            el = page.locator(selector).first
            if el.count() > 0 and el.is_visible():
                el.fill(value, timeout=4000)
                _human_delay(page, 0.3, 0.7)
                return True
        except Exception:
            continue
    return False


def _latest_page(page):
    try:
        pages = list(page.context.pages)
    except Exception:
        return page
    return pages[-1] if pages else page


def _page_text(page) -> str:
    try:
        return (page.content() or "").lower()
    except Exception:
        return ""


def _click_generic_oauth_buttons(page) -> bool:
    return _click_first(page, [
        "button:has-text('Allow access')",
        "button:has-text('Allow')",
        "button:has-text('Authorize')",
        "button:has-text('Accept')",
        "button:has-text('Continue')",
        "button:has-text('Grant access')",
        "button:has-text('Approve')",
        "button:has-text('Confirm')",
        "button:has-text('Open app')",
        "button:has-text('Use this account')",
        "button:has-text('Select')",
        "button:has-text('Connect')",
        "button:has-text('Sign in')",
        "button:has-text('Log in')",
        "button:has-text('Next')",
        "button:has-text('Done')",
        "input[type='submit']",
    ])


def _has_turnstile_challenge(page) -> bool:
    page_text = _page_text(page)
    if "verifying it's you" in page_text or "verifying it’s you" in page_text or "turnstile" in page_text or "cf-challenge" in page_text:
        return True
    try:
        return page.locator("input[name='cf-turnstile-response'], iframe[src*='challenges.cloudflare.com']").count() > 0
    except Exception:
        return False


def _try_solve_turnstile(page) -> bool:
    """Detect and attempt to solve Turnstile; return True if solved or not present."""
    if not _has_turnstile_challenge(page):
        return True
    logger.info("Turnstile detected on %s — attempting CapSolver API solve", page.url)
    solved = _solve_turnstile(page)
    if solved:
        _human_delay(page, 1.0, 2.0)
    return solved


def _is_google_rejected(page) -> bool:
    current = (getattr(page, "url", "") or "").lower()
    return "accounts.google.com" in current and "/signin/rejected" in current


def _maybe_handle_email_challenge(
    page,
    email: str,
    imap_password: str | None,
    service: str,
    *,
    deadline: float | None = None,
    state: dict[str, float] | None = None,
    email_password: str | None = None,
) -> bool:
    page_text = _page_text(page)
    mailbox_email, mailbox_password = _resolve_webmail_credentials(email, email_password)
    if not imap_password and not mailbox_password:
        return False
    if not any(marker in page_text for marker in (
        "check your email",
        "verification code",
        "enter code",
        "one-time code",
        "magic link",
        "confirm your email",
    )):
        return False
    attempt_key = f"{service}:{urlparse(getattr(page, 'url', '') or '').path}:{'otp' if 'code' in page_text else 'link'}"
    if state is not None:
        last_attempt = state.get(attempt_key, 0.0)
        # Avoid re-polling IMAP for the exact same challenge every loop.
        if time.time() - last_attempt < 45:
            return False
        state[attempt_key] = time.time()
    remaining = max(0, int((deadline - time.time()) if deadline else 90))
    if remaining < 5:
        return _maybe_handle_webmail_fallback(page, mailbox_email, mailbox_password, service, state)
    wait_timeout = min(45, remaining)
    from backend.testing.email_reader import wait_for_verification_code, wait_for_verification_url
    last_imap_error = ""
    try:
        code = wait_for_verification_code(email, imap_password, service, timeout=wait_timeout)
    except RuntimeError as exc:
        last_imap_error = str(exc)
        code = None
    if code:
        filled = _fill_first(page, [
            "input[autocomplete='one-time-code']",
            "input[inputmode='numeric']",
            "input[name='code']",
            "input[name='otp']",
            "input[type='text']",
        ], code)
        if filled:
            _click_text(page, ["Continue", "Verify", "Submit", "Next"])
            return True
    remaining = max(0, int((deadline - time.time()) if deadline else wait_timeout))
    if remaining < 5:
        return _maybe_handle_webmail_fallback(page, mailbox_email, mailbox_password, service, state, last_imap_error)
    try:
        link = wait_for_verification_url(email, imap_password, service, timeout=min(45, remaining))
    except RuntimeError as exc:
        last_imap_error = str(exc)
        link = None
    if link:
        page.goto(link, timeout=30000)
        _human_delay(page, 1.0, 2.0)
        return True
    return _maybe_handle_webmail_fallback(page, mailbox_email, mailbox_password, service, state, last_imap_error)


def _maybe_handle_webmail_fallback(
    page,
    email: str,
    email_password: str | None,
    service: str,
    state: dict[str, float] | None,
    imap_error: str = "",
) -> bool:
    if not email_password:
        return False
    domain = email.split("@")[-1].lower()
    fallback_key = f"webmail:{service}:{domain}"
    if state is not None and state.get(fallback_key):
        return False
    if state is not None:
        state[fallback_key] = time.time()
    logger.info("Falling back to in-browser mailbox verification for %s (%s)", service, imap_error or "no IMAP result")
    if domain in {"gmail.com", "googlemail.com"}:
        return _open_gmail_for_verification(page, email, email_password, service)
    return False


def _open_gmail_for_verification(page, email: str, password: str, service: str) -> bool:
    try:
        inbox = page.context.new_page()
        inbox.goto("https://mail.google.com", timeout=30000)
        _human_delay(inbox, 1.0, 2.0)
        if "accounts.google.com" in (inbox.url or ""):
            _handle_google_login(inbox, email, password)
            _human_delay(inbox, 2.0, 3.5)
        if "mail.google.com" not in (inbox.url or ""):
            return False
        query = _gmail_service_query(service)
        try:
            inbox.goto(f"https://mail.google.com/mail/u/0/#search/{query}", timeout=30000)
            _human_delay(inbox, 2.0, 3.5)
        except Exception:
            pass
        return True
    except Exception as exc:
        logger.warning("Webmail fallback failed for %s: %s", service, exc)
        return False


def _resolve_webmail_credentials(email: str, email_password: str | None) -> tuple[str, str]:
    from backend.config import settings

    candidate_email = email.strip()
    candidate_password = (email_password or "").strip()
    base_email = (getattr(settings, "test_email_base", "") or "").strip()
    base_web_password = (getattr(settings, "test_email_web_password", "") or "").strip()

    if base_email and _is_gmail_alias_for(candidate_email, base_email):
        return base_email, base_web_password or candidate_password
    if base_email and candidate_email.lower() == base_email.lower():
        return base_email, base_web_password or candidate_password
    return candidate_email, candidate_password


def _is_gmail_alias_for(email: str, base_email: str) -> bool:
    try:
        local, domain = email.lower().split("@", 1)
        base_local, base_domain = base_email.lower().split("@", 1)
    except ValueError:
        return False
    if domain not in {"gmail.com", "googlemail.com"} or base_domain not in {"gmail.com", "googlemail.com"}:
        return False
    return local.split("+", 1)[0] == base_local.split("+", 1)[0]


def _gmail_service_query(service: str) -> str:
    service = (service or "").lower()
    if service == "notion":
        return "from:(notion.so OR notion.com OR mail.notion.so) newer_than:1d"
    if service == "linear":
        return "from:(linear.app OR linear.com) newer_than:1d"
    return f"from:{service} newer_than:1d"


def _handle_google_login(page, email: str, password: str) -> None:
    page_text = _page_text(page)
    if "@gmail.com" in email or "@googlemail.com" in email:
        _click_text(page, [email, "Use another account"])
    _fill_first(page, ["input[type='email']", "input[name='identifier']"], email)
    _click_first(page, ["#identifierNext", "button:has-text('Next')"])
    _fill_first(page, ["input[type='password']", "input[name='Passwd']"], password)
    _click_first(page, ["#passwordNext", "button:has-text('Next')"])
    if "choose an account" in page_text or "select an account" in page_text:
        _click_text(page, [email, "Use another account"])
    _click_text(page, ["Continue", "Allow", "Accept", "Continue as", "Grant access"])


def _handle_linkedin_login(page, email: str, password: str) -> None:
    _fill_first(page, ["input#username", "input[name='session_key']", "input[type='email']"], email)
    _fill_first(page, ["input#password", "input[name='session_password']", "input[type='password']"], password)
    _click_first(page, ["button[type='submit']", "button:has-text('Sign in')", "button:has-text('Continue')"])
    _click_text(page, ["Allow", "Continue", "Approve", "Accept"])


def _handle_notion_login(page, email: str, password: str, imap_password: str | None) -> None:
    page_text = _page_text(page)
    if "new user? sign up" in page_text or page.url.rstrip("/").endswith("/login"):
        _click_text(page, ["Sign up"])
        _human_delay(page, 0.7, 1.4)
        page_text = _page_text(page)
    if "log in" in page_text or "sign in" in page_text:
        _click_text(page, ["Log in", "Sign in"])
    _fill_first(page, ["input[type='email']", "input[name='email']"], email)
    _click_text(page, ["Continue with email", "Continue", "Email me a code"])
    _fill_first(page, ["input[type='password']", "input[name='password']"], password)
    _click_text(page, ["Continue", "Sign in", "Open Notion"])
    _maybe_handle_email_challenge(page, email, imap_password, "notion", email_password=password)
    _click_text(page, ["Select pages", "Allow access", "Allow", "Continue", "Authorize"])


def _handle_linear_login(page, email: str, password: str, imap_password: str | None) -> None:
    page_text = _page_text(page)
    if page.url.rstrip("/").endswith("/signup") or "create your workspace" in page_text or "what’s your email address?" in page_text or "what's your email address?" in page_text:
        _click_text(page, ["Continue with email"])
        _fill_first(page, ["input[type='email']", "input[name='email']"], email)
        _click_text(page, ["Continue with email", "Continue"])
        return
    if "log in" in page_text or "sign in" in page_text:
        _click_text(page, ["Log in", "Sign in"])
    _fill_first(page, ["input[type='email']", "input[name='email']"], email)
    _click_text(page, ["Continue", "Continue with email", "Next"])
    _fill_first(page, ["input[type='password']", "input[name='password']"], password)
    _click_text(page, ["Sign in", "Continue", "Open Linear"])
    _maybe_handle_email_challenge(page, email, imap_password, "linear", email_password=password)
    _click_text(page, ["Allow access", "Allow", "Authorize", "Approve", "Continue"])


def _handle_github_login(page, email: str, password: str) -> None:
    _fill_first(page, ["input#login_field", "input[name='login']", "input[type='email']"], email)
    _fill_first(page, ["input#password", "input[name='password']", "input[type='password']"], password)
    _click_first(page, ["input[type='submit']", "button[type='submit']", "button:has-text('Sign in')"])
    _click_text(page, ["Authorize", "Authorize Composio", "Continue", "Approve"])


def _handle_composio_return(page) -> None:
    _click_text(page, ["Continue", "Open app", "Back to app", "Done"])


def _slug(email: str) -> str:
    base = email.split("@")[0].lower().replace(".", "-").replace("_", "-")
    suffix = secrets.token_hex(3)
    return f"{base}-{suffix}"[:39]  # GitHub username max 39 chars
