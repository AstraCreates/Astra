from __future__ import annotations

from backend.tools.web_tasks.base import WebTaskAdapter, WebTaskContext
from backend.tools.web_tasks.models import WebTaskResult, WebTaskState


class SquareSandboxAdapter(WebTaskAdapter):
    service = "square_sandbox"
    supported_task_types = ("login_or_signup", "retrieve_api_key")

    async def _ensure_logged_in(self, ctx: WebTaskContext) -> WebTaskResult | None:
        await ctx.goto("https://developer.squareup.com/apps", WebTaskState.LOGIN)
        page = await ctx.page()
        if "login" in page.url:
            maybe = await self._require_login_credentials(ctx)
            if maybe:
                return maybe
            await self._submit_login_form(
                ctx,
                "input[type='email'], input[name='email']",
                "input[type='password'], input[name='password']",
                "button[type='submit'], button:has-text('Sign in')",
            )
        blocker = await ctx.detect_human_blocker()
        if blocker:
            return await ctx.needs_user(blocker.kind, blocker.message, blocker.fields)
        page = await self._latest_page(ctx)
        if "login" in page.url:
            return await ctx.block("Square Developer login did not complete successfully.")
        await ctx.set_state(WebTaskState.DASHBOARD, "Authenticated Square developer session.")
        await ctx.add_check("square_authenticated")
        return None

    async def run(self, ctx: WebTaskContext) -> WebTaskResult:
        ensured = await self._ensure_logged_in(ctx)
        if ensured:
            return ensured
        page = await ctx.page()
        if ctx.request.task_type == "login_or_signup":
            return await ctx.complete({"square": {"authenticated": True, "dashboard_url": page.url}})
        await ctx.goto("https://developer.squareup.com/apps", WebTaskState.API_KEYS)
        try:
            new_app = await page.query_selector("button:has-text('Create Your First Application'), a:has-text('New Application')")
            if new_app:
                await new_app.click()
                try:
                    await page.fill("input[name='applicationName'], input[placeholder*='name']", "Astra", timeout=3_000)
                except Exception:
                    pass
                try:
                    await page.click("button:has-text('Save'), button[type='submit']", timeout=5_000)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            app_link = await page.query_selector("a[href*='/apps/']")
            if app_link:
                href = await app_link.get_attribute("href")
                if href:
                    await ctx.goto(f"https://developer.squareup.com{href}/overview", WebTaskState.API_KEYS)
        except Exception:
            pass
        token = ""
        for selector in ("input[id*='sandbox'][readonly]", "input[value^='EAAAlb']", "input[readonly]", "code"):
            try:
                el = await page.query_selector(selector)
                if el:
                    token = ((await el.get_attribute("value")) or (await el.inner_text()) or "").strip()
                    if len(token) > 20:
                        break
            except Exception:
                continue
        if not token:
            return await ctx.block("Could not extract Square sandbox access token.")
        ctx.persist_credentials("square", {"access_token": token, "environment": "sandbox"})
        await ctx.add_check("sandbox_token_extracted")
        return await ctx.complete({"square": {"access_token": token, "environment": "sandbox", "dashboard_url": page.url}})
