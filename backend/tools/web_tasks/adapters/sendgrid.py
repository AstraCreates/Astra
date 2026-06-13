from __future__ import annotations

from backend.tools.web_tasks.base import WebTaskAdapter, WebTaskContext
from backend.tools.web_tasks.models import WebTaskResult, WebTaskState


class SendGridAdapter(WebTaskAdapter):
    service = "sendgrid"
    supported_task_types = ("login_or_signup", "retrieve_api_key")

    async def _ensure_logged_in(self, ctx: WebTaskContext) -> WebTaskResult | None:
        await ctx.goto("https://app.sendgrid.com/login", WebTaskState.LOGIN)
        page = await ctx.page()
        if "/login" in page.url:
            maybe = await self._require_login_credentials(ctx)
            if maybe:
                return maybe
            await self._submit_login_form(
                ctx,
                "input[type='email'], input[name='username'], input[name='email']",
                "input[type='password'], input[name='password']",
                "button[type='submit'], input[type='submit']",
            )
        blocker = await ctx.detect_human_blocker()
        if blocker:
            return await ctx.needs_user(blocker.kind, blocker.message, blocker.fields)
        page = await self._latest_page(ctx)
        if "/login" in page.url:
            return await ctx.block("SendGrid login did not complete successfully.")
        await ctx.set_state(WebTaskState.DASHBOARD, "Authenticated SendGrid session.")
        await ctx.add_check("sendgrid_authenticated")
        return None

    async def run(self, ctx: WebTaskContext) -> WebTaskResult:
        ensured = await self._ensure_logged_in(ctx)
        if ensured:
            return ensured
        page = await ctx.page()
        if ctx.request.task_type == "login_or_signup":
            return await ctx.complete({"sendgrid": {"authenticated": True, "account_url": page.url}})
        await ctx.goto("https://app.sendgrid.com/settings/api_keys", WebTaskState.API_KEYS)
        try:
            await page.click("button:has-text('Create API Key')", timeout=8_000)
        except Exception:
            pass
        try:
            await page.fill("input[placeholder*='API Key Name' i], input[name='name']", "Astra", timeout=5_000)
        except Exception:
            pass
        try:
            await page.click("label:has-text('Full Access')", timeout=4_000)
        except Exception:
            pass
        try:
            await page.click("button:has-text('Create & View'), button:has-text('Create API Key'), button[type='submit']", timeout=6_000)
        except Exception:
            pass
        api_key = ""
        for selector in (
            "[data-key-value]",
            ".api-key-copy",
            "input[readonly]",
            "code",
            ".clipboard-key",
        ):
            try:
                el = await page.query_selector(selector)
                if el:
                    api_key = ((await el.get_attribute("value")) or (await el.get_attribute("data-key-value")) or (await el.inner_text()) or "").strip()
                    if api_key.startswith("SG.") and len(api_key) > 20:
                        break
            except Exception:
                continue
        if not (api_key.startswith("SG.") and len(api_key) > 20):
            return await ctx.block("Could not extract SendGrid API key.")
        ctx.persist_credentials("sendgrid", {"api_key": api_key})
        await ctx.add_check("api_key_extracted")
        return await ctx.complete({"sendgrid": {"api_key": api_key, "account_url": page.url}})
