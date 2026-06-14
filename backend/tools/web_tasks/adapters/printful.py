from __future__ import annotations

from backend.tools.web_tasks.base import WebTaskAdapter, WebTaskContext
from backend.tools.web_tasks.models import WebTaskResult, WebTaskState


class PrintfulAdapter(WebTaskAdapter):
    service = "printful"
    supported_task_types = ("login_or_signup", "retrieve_api_key")

    async def _ensure_logged_in(self, ctx: WebTaskContext) -> WebTaskResult | None:
        await ctx.goto("https://www.printful.com/auth/login", WebTaskState.LOGIN)
        page = await ctx.page()
        if "/auth/login" in page.url:
            maybe = await self._require_login_credentials(ctx)
            if maybe:
                return maybe
            await self._submit_login_form(
                ctx,
                "input[type='email'], input[name='email']",
                "input[type='password'], input[name='password']",
                "button[type='submit'], input[type='submit']",
            )
        blocker = await ctx.detect_human_blocker()
        if blocker:
            return await ctx.needs_user(blocker.kind, blocker.message, blocker.fields)
        page = await self._latest_page(ctx)
        if "/auth/login" in page.url:
            return await ctx.block("Printful login did not complete successfully.")
        await ctx.set_state(WebTaskState.DASHBOARD, "Authenticated Printful session.")
        await ctx.add_check("printful_authenticated")
        return None

    async def run(self, ctx: WebTaskContext) -> WebTaskResult:
        ensured = await self._ensure_logged_in(ctx)
        if ensured:
            return ensured
        page = await ctx.page()
        if ctx.request.task_type == "login_or_signup":
            return await ctx.complete({"printful": {"authenticated": True, "account_url": page.url}})
        await ctx.goto("https://www.printful.com/dashboard/settings/api", WebTaskState.API_KEYS)
        try:
            await page.click("button:has-text('Enable API Access'), button:has-text('Generate')", timeout=8_000)
        except Exception:
            pass
        api_key = ""
        for selector in (
            "input[type='text'][readonly]",
            "input[readonly]",
            "code",
            ".api-key",
            "[data-testid='api-key']",
        ):
            try:
                el = await page.query_selector(selector)
                if el:
                    api_key = ((await el.get_attribute("value")) or (await el.inner_text()) or "").strip()
                    if len(api_key) > 10:
                        break
            except Exception:
                continue
        if not api_key:
            return await ctx.block("Could not extract Printful API key.")
        ctx.persist_credentials("printful", {"api_key": api_key})
        await ctx.add_check("api_key_extracted")
        return await ctx.complete({"printful": {"api_key": api_key, "account_url": page.url}})
