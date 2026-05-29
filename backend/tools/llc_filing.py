"""
NWRA LLC filing — live browser streaming via Playwright CDP screencasting.

The NWRA form is a single-page wizard where ALL fields are in the DOM from
the start. Continue validates/scrolls to the next section. Steps:
  1. Formation      — select state (Vue Multiselect, data-testid="company-state-select-group")
  2. Company Name   — name + designator (Vue Multiselect placeholder="Select Designator")
  3. Business Details — textarea name="companyInformation.businessPurpose"
  4. Account        — personal info (FOUNDER INTERACTION)
  5. Management     — member first/last name
  6. Recommended    — skip (just Continue)
  7. Payment        — Astra card (hidden from founder)
"""
import asyncio
import logging

logger = logging.getLogger(__name__)

NWRA_URL = "https://www.northwestregisteredagent.com/incorporation-service-signup"

STEPS = ["Formation", "Company Name", "Business Details", "Account",
         "Management", "Recommended", "Payment"]

FOUNDER_FIELDS = [
    {"name": "first_name", "label": "First Name",     "type": "text",     "required": True},
    {"name": "last_name",  "label": "Last Name",      "type": "text",     "required": True},
    {"name": "email",      "label": "Email Address",  "type": "email",    "required": True},
    {"name": "phone",      "label": "Phone Number",   "type": "tel",      "required": True},
    {"name": "password",   "label": "Create Password","type": "password", "required": True},
]

EIN_FIELDS = [
    {
        "name": "has_ssn",
        "label": "Do you have a U.S. Social Security Number (SSN)?",
        "type": "select",
        "options": [
            {"value": "yes", "label": "Yes — I have an SSN", "description": "$50 · faster processing"},
            {"value": "no",  "label": "No SSN",              "description": "$200 · alternative process"},
        ],
        "required": True,
        "default": "yes",
    },
    {
        "name": "ssn",
        "label": "Social Security Number",
        "type": "password",
        "placeholder": "XXX-XX-XXXX",
        "required": False,
        "show_if": "yes",   # only shown when has_ssn = yes
    },
    {
        "name": "_disclaimer",
        "label": "🔒 Astra does not collect, store, or have access to your SSN. It is entered directly into the Northwest Registered Agent secure form.",
        "type": "disclaimer",
        "required": False,
    },
]

MANAGEMENT_FIELDS = [
    {
        "name": "management_type",
        "label": "Management Type",
        "type": "select",
        "options": [
            {"value": "member_managed",  "label": "Member Managed",  "description": "All members run the company (most common for small LLCs)"},
            {"value": "manager_managed", "label": "Manager Managed", "description": "Designated managers run the company (good for passive investors)"},
        ],
        "required": True,
        "default": "member_managed",
    }
]



async def _ack(client, session_id_val: int) -> None:
    try:
        await client.send("Page.screencastFrameAck", {"sessionId": session_id_val})
    except Exception:
        pass


async def _step(send_message, step_name: str) -> None:
    idx = STEPS.index(step_name) + 1 if step_name in STEPS else 0
    await send_message({"type": "status", "step": step_name, "step_num": idx, "total": len(STEPS)})


async def _nav(page, timeout: int = 10000) -> None:
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=timeout)
    except Exception:
        pass
    await asyncio.sleep(0.8)


async def _continue(page) -> None:
    """Click the Continue button and wait briefly."""
    try:
        await page.click("button:has-text('Continue')", timeout=8000)
        await asyncio.sleep(1.2)
    except Exception as e:
        logger.warning("Continue click failed: %s", e)


async def _select_vue(page, data_testid: str | None, placeholder: str, option_text: str) -> bool:
    """Open a Vue Multiselect dropdown and pick an option.
    Must click the outer container (not the hidden inner input).
    """
    try:
        if data_testid:
            container = page.locator(f"[data-testid='{data_testid}']").first
        else:
            container = page.locator(f".multiselect:has(input[placeholder='{placeholder}'])").first

        await container.click(timeout=8000)
        await asyncio.sleep(0.4)

        # Inner input becomes active — type to filter
        inp = container.locator("input").first
        await inp.fill(option_text)
        await asyncio.sleep(0.6)

        # Click the matching option span inside the dropdown list
        option = page.locator(f".multiselect__option span:text-is('{option_text}')").first
        await option.click(timeout=5000)
        await asyncio.sleep(0.4)
        logger.info("Vue select: '%s' → '%s'", placeholder, option_text)
        return True
    except Exception as e:
        logger.error("Vue select failed ('%s' → '%s'): %s", placeholder, option_text, e)
        return False


async def file_llc_live(
    founder_id: str,
    company_name: str,
    state: str,
    send_message,   # async callable(dict)
    wait_input,     # async callable() -> dict | None
) -> dict:
    from backend.config import settings

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        await send_message({"type": "error",
                            "message": "playwright not installed — run: pip install playwright && playwright install chromium"})
        return {"error": "playwright not installed"}

    result: dict = {}

    async with async_playwright() as pw:
        # headless=False is required — Cloudflare blocks headless Chromium.
        # Window is positioned far off-screen so it never appears on the user's display.
        browser = await pw.chromium.launch(
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--window-position=-32000,0",
                "--window-size=1280,800",
            ],
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        # Mask automation fingerprints so Cloudflare doesn't block
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            window.chrome = {runtime: {}};
        """)
        page = await context.new_page()

        # ── CDP screencasting ─────────────────────────────────────────────────
        client = await context.new_cdp_session(page)


        async def on_frame(params):
            try:
                await _ack(client, params["sessionId"])
                await send_message({"type": "frame", "data": params["data"]})
            except Exception:
                pass

        client.on("Page.screencastFrame", lambda p: asyncio.ensure_future(on_frame(p)))
        await client.send("Page.startScreencast", {
            "format": "jpeg", "quality": 70,
            "maxWidth": 1280, "maxHeight": 800, "everyNthFrame": 2,
        })

        try:
            # ── Step 1: Formation ─────────────────────────────────────────────
            await _step(send_message, "Formation")
            await page.goto(NWRA_URL, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)

            # Select state via Vue Multiselect (data-testid="company-state-select-group")
            ok = await _select_vue(page, "company-state-select-group", "Select State", state)
            if not ok:
                logger.error("State selection failed — bot cannot continue")
                await send_message({"type": "error", "message": f"Could not select state '{state}'."})
                return {"error": "state_select_failed"}

            await _continue(page)

            # ── Step 2: Company Name ──────────────────────────────────────────
            await _step(send_message, "Company Name")
            await asyncio.sleep(0.5)
            try:
                await page.fill("input[name='companyInformation.companyName']", company_name, timeout=5000)
            except Exception as e:
                logger.warning("Company name fill: %s", e)

            await _select_vue(page, None, "Select Designator", "LLC")

            # Enable EIN filing service (toggle it on via its label)
            try:
                await page.locator("label[for='taxIdParentBool_checkbox']").click(timeout=5000)
                await asyncio.sleep(0.6)
                logger.info("EIN service enabled")
            except Exception as e:
                logger.warning("EIN toggle: %s", e)

            # Ask founder for SSN choice
            await send_message({
                "type": "interaction_needed",
                "step": "EIN Filing",
                "message": "Astra will file your EIN (Tax ID). We need one piece of information:",
                "fields": EIN_FIELDS,
            })
            ein_data = await wait_input() or {}
            await send_message({"type": "bot_filling", "step": "EIN Filing"})

            has_ssn = ein_data.get("has_ssn", "yes")
            ssn_val = ein_data.get("ssn", "")

            # Click the appropriate SSN radio
            try:
                if has_ssn == "yes":
                    await page.locator("label[for='taxIdSsn_radio']").click(timeout=5000)
                else:
                    await page.locator("label[for='taxIdNoSsn_radio']").click(timeout=5000)
                await asyncio.sleep(0.6)
            except Exception as e:
                logger.warning("EIN SSN radio: %s", e)

            # Fill SSN if provided and field is visible
            if ssn_val and has_ssn == "yes":
                try:
                    ssn_input = page.locator("input[name='taxIdSsn'], input[placeholder*='SSN'], input[placeholder*='Social']").first
                    await ssn_input.fill(ssn_val, timeout=4000)
                except Exception as e:
                    logger.warning("SSN field: %s", e)

            await _continue(page)

            # ── Step 3: Business Details ──────────────────────────────────────
            await _step(send_message, "Business Details")
            await asyncio.sleep(0.5)
            # The textarea is disabled until "use generic purpose" checkbox is checked.
            # Checking it pre-fills with a generic description and disables the field.
            try:
                cb = page.locator("input[name='useGenericBusinessPurpose']")
                if not await cb.is_checked(timeout=3000):
                    await cb.check()
                    await asyncio.sleep(0.3)
            except Exception as e:
                logger.warning("Generic business purpose checkbox: %s", e)
            await _continue(page)

            # ── Step 4: Account — FOUNDER INTERACTION ─────────────────────────
            await _step(send_message, "Account")
            await asyncio.sleep(0.8)

            await send_message({
                "type": "interaction_needed",
                "step": "Account",
                "message": "Fill in your personal info to create your Northwest Registered Agent account.",
                "fields": FOUNDER_FIELDS,
            })

            founder_data = await wait_input()
            if not founder_data:
                await send_message({"type": "error", "message": "Timed out waiting for personal info."})
                return {"error": "timeout"}

            await send_message({"type": "bot_filling", "step": "Account"})

            # Fill account + contact fields (all in DOM with exact names)
            try:
                await page.fill("input[name='contactInformation.firstName']",
                                founder_data.get("first_name", ""))
                await page.fill("input[name='contactInformation.lastName']",
                                founder_data.get("last_name", ""))
                await page.fill("input[name='contactInformation.phone']",
                                founder_data.get("phone", ""))
                await page.fill("input[name='accountInformation.email']",
                                founder_data.get("email", ""))
                pw_val = founder_data.get("password", "")
                await page.fill("input[name='accountInformation.password']", pw_val)
                await page.fill("input[name='accountInformation.passwordConfirm']", pw_val)
                logger.info("Account fields filled")
            except Exception as e:
                logger.error("Account fill error: %s", e)

            await _continue(page)

            # ── Step 5: Management ────────────────────────────────────────────
            await _step(send_message, "Management")
            try:
                await page.wait_for_selector(
                    "input[name='formationDetails.llc.members.0.firstName']",
                    state="visible", timeout=12000,
                )
            except Exception:
                pass
            await asyncio.sleep(0.5)

            # Ask founder for management type choice
            await send_message({
                "type": "interaction_needed",
                "step": "Management",
                "message": "How will your LLC be managed?",
                "fields": MANAGEMENT_FIELDS,
            })
            mgmt_data = await wait_input() or {}
            await send_message({"type": "bot_filling", "step": "Management"})

            # Select management type on the form
            mgmt_type = mgmt_data.get("management_type", "member_managed")
            if mgmt_type == "manager_managed":
                try:
                    await page.locator("label:has-text('Manager Managed')").click(timeout=4000)
                except Exception as e:
                    logger.warning("Manager Managed radio: %s", e)
            # else Member Managed is already pre-selected

            # Fill member name (re-use founder's name from Step 4)
            try:
                await page.fill("input[name='formationDetails.llc.members.0.firstName']",
                                founder_data.get("first_name", ""))
                await page.fill("input[name='formationDetails.llc.members.0.lastName']",
                                founder_data.get("last_name", ""))
            except Exception as e:
                logger.warning("Management fill: %s", e)
            await _continue(page)

            # ── Step 6: Recommended — skip all add-ons ───────────────────────
            await _step(send_message, "Recommended")
            await asyncio.sleep(0.8)
            await _continue(page)

            # ── Step 7: Payment ───────────────────────────────────────────────
            await _step(send_message, "Payment")
            # Wait for payment fields to become visible
            try:
                await page.wait_for_selector(
                    "input[placeholder='____-____-____-____']",
                    state="visible", timeout=12000,
                )
            except Exception:
                pass
            await send_message({"type": "payment_filling",
                                "message": "Filling payment securely with Astra card…"})
            await asyncio.sleep(0.8)

            if not settings.nwra_card_number:
                result = {"status": "pending_payment",
                          "message": "Reached payment — NWRA_CARD_NUMBER not set in .env"}
                await send_message({"type": "done", **result})
                return result

            name_parts = settings.nwra_card_name.split()
            try:
                await page.fill("input[placeholder='____-____-____-____']",
                                settings.nwra_card_number)
                await page.fill("input[name='paymentInformation.first_name']",
                                name_parts[0] if name_parts else "")
                await page.fill("input[name='paymentInformation.last_name']",
                                " ".join(name_parts[1:]) if len(name_parts) > 1 else "")
                await page.fill("input[name='paymentInformation.cvc']",
                                settings.nwra_card_cvv)
                await _select_vue(page, None, "Month", settings.nwra_card_expiry_month)
                await _select_vue(page, None, "Year", settings.nwra_card_expiry_year)
                await page.fill("input[name='paymentInformation.line1']",
                                settings.nwra_billing_address)
                await page.fill("input[name='paymentInformation.city']",
                                settings.nwra_billing_city)
                await page.fill("input[name='paymentInformation.zip']",
                                settings.nwra_billing_zip)
                # Billing state — second "Select State" multiselect on the page
                state_inputs = page.locator("input[placeholder='Select State']")
                if await state_inputs.count() >= 2:
                    billing_container = page.locator(
                        ".multiselect:has(input[placeholder='Select State'])"
                    ).nth(1)
                    await billing_container.click(timeout=5000)
                    await asyncio.sleep(0.4)
                    await billing_container.locator("input").first.fill(settings.nwra_billing_state)
                    await asyncio.sleep(0.5)
                    await page.locator(
                        f".multiselect__option span:text-is('{settings.nwra_billing_state}')"
                    ).first.click(timeout=4000)
                logger.info("Payment fields filled")
            except Exception as e:
                logger.error("Payment fill error: %s", e)

            try:
                await page.click("button:has-text('Submit Order')", timeout=10000)
                await _nav(page, timeout=20000)
                result = {"status": "submitted", "confirmation_url": page.url}
            except Exception as e:
                result = {"status": "payment_filled", "note": str(e)}

            await send_message({"type": "done", **result})

        except Exception as e:
            logger.error("LLC filing error: %s", e, exc_info=True)
            await send_message({"type": "error", "message": str(e)})
            result = {"status": "error", "error": str(e)}
        finally:
            try:
                await client.send("Page.stopScreencast")
            except Exception:
                pass
            await browser.close()

    return result
