"""
Headless browser provisioner.
Creates GitHub, Vercel, SendGrid accounts with founder email+password,
extracts API tokens, returns them.
"""
import logging
import secrets
import time
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


def provision_github(email: str, password: str, username: str = None, imap_password: str = None) -> dict:
    """
    Create GitHub account + personal access token.
    Returns {"token": "ghp_...", "username": "...", "created": bool}
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    username = username or _slug(email)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
        page = ctx.new_page()

        try:
            # --- Attempt login first (account may already exist) ---
            page.goto("https://github.com/login", timeout=30000)
            page.fill("input#login_field", email)
            page.fill("input#password", password)
            page.click("input[type=submit]")
            page.wait_for_timeout(3000)

            logged_in = "github.com" in page.url and "login" not in page.url and "session" not in page.url

            if not logged_in:
                # --- Sign up flow (GitHub stepped form) ---
                page.goto("https://github.com/signup", timeout=30000)
                page.wait_for_timeout(2000)

                # Step 1: email
                email_input = page.locator("input[name='user[email]'], input#email, input[type=email]").first
                email_input.wait_for(timeout=10000)
                email_input.fill(email)
                page.keyboard.press("Tab")
                page.wait_for_timeout(500)

                # Step 2: password (may be on same page or next step)
                pwd_input = page.locator("input[name='user[password]'], input#password, input[type=password]").first
                if pwd_input.count() > 0:
                    pwd_input.fill(password)
                    page.keyboard.press("Tab")
                    page.wait_for_timeout(500)

                # Step 3: username
                uname_input = page.locator("input[name='user[login]'], input#login, input[autocomplete=username]").first
                if uname_input.count() > 0:
                    uname_input.fill(username)
                    page.keyboard.press("Tab")
                    page.wait_for_timeout(500)

                # Submit
                submit = page.locator("button[type=submit]").first
                submit.click()
                page.wait_for_timeout(3000)

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
                                page.wait_for_timeout(3000)
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
                                page.wait_for_timeout(3000)
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
                page.fill("input#login_field", email)
                page.fill("input#password", password)
                page.click("input[type=submit]")
                page.wait_for_timeout(3000)
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
            page.wait_for_timeout(2000)

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
            page.wait_for_timeout(2000)

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
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()

        try:
            page.goto("https://vercel.com/login", timeout=30000)

            if github_token:
                # Continue with GitHub
                page.click("button:has-text('Continue with GitHub')")
                page.wait_for_timeout(3000)
                # GitHub OAuth redirect
                if "github.com" in page.url:
                    page.fill("input#login_field", email)
                    page.fill("input#password", password)
                    page.click("input[type=submit]")
                    page.wait_for_timeout(2000)
                    # Authorize if prompted
                    auth_btn = page.locator("button:has-text('Authorize')")
                    if auth_btn.count() > 0:
                        auth_btn.click()
                        page.wait_for_timeout(2000)
            else:
                page.click("button:has-text('Continue with Email')")
                page.fill("input[type=email]", email)
                page.click("button[type=submit]")
                page.wait_for_timeout(2000)
                if imap_password:
                    from backend.testing.email_reader import wait_for_verification_url
                    magic_url = wait_for_verification_url(email, imap_password, "vercel", timeout=300)
                    if magic_url:
                        page.goto(magic_url, timeout=30000)
                        page.wait_for_timeout(4000)
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
            page.wait_for_timeout(2000)

            # Click create token
            create_btn = page.locator("button:has-text('Create')")
            if create_btn.count() > 0:
                create_btn.click()
                page.wait_for_timeout(1000)
                page.fill("input[placeholder*='Token Name']", "Astra Deploy Token")
                page.click("button:has-text('Create Token')")
                page.wait_for_timeout(1000)
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
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()

        try:
            page.goto("https://signup.sendgrid.com/", timeout=30000)
            page.fill("input[name='email']", email)
            page.fill("input[name='password']", password)

            # Fill required fields
            username_field = page.locator("input[name='username']")
            if username_field.count() > 0:
                username_field.fill(_slug(email))

            page.click("button[type=submit]")
            page.wait_for_timeout(3000)

            if "app.sendgrid.com" not in page.url:
                if imap_password:
                    from backend.testing.email_reader import wait_for_verification_url
                    verify_url = wait_for_verification_url(email, imap_password, "sendgrid", timeout=300)
                    if verify_url:
                        page.goto(verify_url, timeout=30000)
                        page.wait_for_timeout(4000)
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
            page.wait_for_timeout(2000)
            page.click("button:has-text('Create API Key')")
            page.wait_for_timeout(1000)
            page.fill("input[name='name']", "Astra Marketing Key")
            # Full access
            page.click("label:has-text('Full Access')")
            page.click("button:has-text('Create & View')")
            page.wait_for_timeout(2000)

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
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
        page = ctx.new_page()

        try:
            page.goto("https://app.composio.dev/login", timeout=30000)
            page.wait_for_timeout(2000)

            # Click "Continue with GitHub"
            github_btn = page.locator(
                "button:has-text('GitHub'), a:has-text('GitHub'), "
                "button:has-text('Continue with GitHub'), a:has-text('Continue with GitHub')"
            ).first
            if github_btn.count() > 0:
                github_btn.click()
                page.wait_for_timeout(4000)
            else:
                # Try direct GitHub OAuth URL pattern used by many SaaS
                page.goto("https://app.composio.dev/auth/github", timeout=30000)
                page.wait_for_timeout(3000)

            # GitHub OAuth consent screen
            if "github.com" in page.url:
                login_field = page.locator("input#login_field, input[name='login']").first
                if login_field.count() > 0:
                    login_field.fill(email)
                pwd_field = page.locator("input#password, input[name='password']").first
                if pwd_field.count() > 0:
                    pwd_field.fill(password)
                page.locator("input[type=submit], button[type=submit]").first.click()
                page.wait_for_timeout(3000)

                # Authorize Composio app if consent screen appears
                authorize_btn = page.locator("button:has-text('Authorize'), input[value='Authorize']").first
                if authorize_btn.count() > 0:
                    authorize_btn.click()
                    page.wait_for_timeout(4000)

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
                page.wait_for_timeout(2000)

                # Look for existing key or generate new one
                api_key = _extract_composio_key(page)
                if api_key:
                    break

                # Try clicking a generate/create button
                for label in ["Generate API Key", "Create API Key", "New API Key", "Generate", "Create"]:
                    btn = page.locator(f"button:has-text('{label}')").first
                    if btn.count() > 0:
                        btn.click()
                        page.wait_for_timeout(2000)
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
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
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
    page.goto(url, timeout=30000)
    page.wait_for_timeout(1500)

    while time.time() < deadline:
        status = get_status(founder_id)
        if status.get(app):
            _persist_connected_composio_app(founder_id, app)
            return {"connected": True, "app": app}

        current = page.url or ""
        host = urlparse(current).netloc.lower()

        if "accounts.google.com" in host:
            _handle_google_login(page, email, password)
        elif "linkedin.com" in host:
            _handle_linkedin_login(page, email, password)
        elif "notion.so" in host:
            _handle_notion_login(page, email, password, imap_password)
        elif "linear.app" in host:
            _handle_linear_login(page, email, password, imap_password)
        elif "github.com" in host:
            _handle_github_login(page, email, password)

        _click_first(page, [
            "button:has-text('Allow access')",
            "button:has-text('Allow')",
            "button:has-text('Authorize')",
            "button:has-text('Accept')",
            "button:has-text('Continue')",
            "button:has-text('Grant access')",
            "button:has-text('Approve')",
            "input[type='submit']",
        ])
        page.wait_for_timeout(2500)

    status = get_status(founder_id)
    if status.get(app):
        _persist_connected_composio_app(founder_id, app)
        return {"connected": True, "app": app}
    return {"connected": False, "app": app, "error": f"Timed out completing OAuth for {app}"}


def _persist_connected_composio_app(founder_id: str, app: str) -> None:
    from backend.provisioning.credentials_store import store_credentials

    for service in _COMPOSIO_APP_SERVICE_MAP.get(app, (app,)):
        store_credentials(founder_id, service, {
            "connected": True,
            "connected_via": "composio_oauth",
            "composio_app": app,
        })


def _click_first(page, selectors: list[str]) -> bool:
    for selector in selectors:
        try:
            el = page.locator(selector).first
            if el.count() > 0 and el.is_visible():
                el.click(timeout=4000)
                page.wait_for_timeout(800)
                return True
        except Exception:
            continue
    return False


def _fill_first(page, selectors: list[str], value: str) -> bool:
    for selector in selectors:
        try:
            el = page.locator(selector).first
            if el.count() > 0 and el.is_visible():
                el.fill(value, timeout=4000)
                page.wait_for_timeout(500)
                return True
        except Exception:
            continue
    return False


def _handle_google_login(page, email: str, password: str) -> None:
    _fill_first(page, ["input[type='email']", "input[name='identifier']"], email)
    _click_first(page, ["#identifierNext", "button:has-text('Next')"])
    _fill_first(page, ["input[type='password']", "input[name='Passwd']"], password)
    _click_first(page, ["#passwordNext", "button:has-text('Next')"])
    _click_first(page, ["button:has-text('Continue')", "button:has-text('Allow')", "button:has-text('Accept')"])


def _handle_linkedin_login(page, email: str, password: str) -> None:
    _fill_first(page, ["input#username", "input[name='session_key']", "input[type='email']"], email)
    _fill_first(page, ["input#password", "input[name='session_password']", "input[type='password']"], password)
    _click_first(page, ["button[type='submit']", "button:has-text('Sign in')", "button:has-text('Continue')"])
    _click_first(page, ["button:has-text('Allow')", "button:has-text('Continue')"])


def _handle_notion_login(page, email: str, password: str, imap_password: str | None) -> None:
    _fill_first(page, ["input[type='email']", "input[name='email']"], email)
    _click_first(page, ["button:has-text('Continue with email')", "button:has-text('Continue')"])
    _fill_first(page, ["input[type='password']", "input[name='password']"], password)
    _click_first(page, ["button:has-text('Continue')", "button:has-text('Sign in')"])
    if imap_password and ("check your email" in page.content().lower() or "verification code" in page.content().lower()):
        from backend.testing.email_reader import wait_for_verification_code, wait_for_verification_url
        code = wait_for_verification_code(email, imap_password, "notion", timeout=90)
        if code:
            _fill_first(page, ["input[autocomplete='one-time-code']", "input[inputmode='numeric']", "input[type='text']"], code)
            _click_first(page, ["button:has-text('Continue')", "button:has-text('Verify')"])
        else:
            link = wait_for_verification_url(email, imap_password, "notion", timeout=90)
            if link:
                page.goto(link, timeout=30000)


def _handle_linear_login(page, email: str, password: str, imap_password: str | None) -> None:
    _fill_first(page, ["input[type='email']", "input[name='email']"], email)
    _click_first(page, ["button:has-text('Continue')", "button[type='submit']"])
    _fill_first(page, ["input[type='password']", "input[name='password']"], password)
    _click_first(page, ["button:has-text('Sign in')", "button:has-text('Continue')"])
    if imap_password and ("check your email" in page.content().lower() or "verification code" in page.content().lower()):
        from backend.testing.email_reader import wait_for_verification_code, wait_for_verification_url
        code = wait_for_verification_code(email, imap_password, "linear", timeout=90)
        if code:
            _fill_first(page, ["input[inputmode='numeric']", "input[autocomplete='one-time-code']", "input[type='text']"], code)
            _click_first(page, ["button:has-text('Continue')", "button:has-text('Verify')"])
        else:
            link = wait_for_verification_url(email, imap_password, "linear", timeout=90)
            if link:
                page.goto(link, timeout=30000)


def _handle_github_login(page, email: str, password: str) -> None:
    _fill_first(page, ["input#login_field", "input[name='login']", "input[type='email']"], email)
    _fill_first(page, ["input#password", "input[name='password']", "input[type='password']"], password)
    _click_first(page, ["input[type='submit']", "button[type='submit']", "button:has-text('Sign in')"])


def _slug(email: str) -> str:
    base = email.split("@")[0].lower().replace(".", "-").replace("_", "-")
    suffix = secrets.token_hex(3)
    return f"{base}-{suffix}"[:39]  # GitHub username max 39 chars
