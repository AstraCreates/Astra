from __future__ import annotations

from backend.tools.web_tasks.base import WebTaskAdapter, WebTaskContext
from backend.tools.web_tasks.models import WebTaskResult, WebTaskState


class VercelAdapter(WebTaskAdapter):
    service = "vercel"
    supported_task_types = ("login_or_signup", "retrieve_deploy_token", "github_connect_check")

    async def _ensure_logged_in(self, ctx: WebTaskContext) -> WebTaskResult | None:
        page = await ctx.page()
        await ctx.goto("https://vercel.com/login", WebTaskState.LOGIN)
        if "/login" in page.url:
            maybe = await self._require_login_credentials(ctx)
            if maybe:
                return maybe
            await self._submit_login_form(
                ctx,
                "input[type='email'], input[name='email']",
                "input[type='password'], input[name='password']",
                "button[type='submit'], button:has-text('Continue')",
            )
        blocker = await ctx.detect_human_blocker()
        if blocker:
            return await ctx.needs_user(blocker.kind, blocker.message, blocker.fields)
        page = await self._latest_page(ctx)
        if "/login" in page.url:
            return await ctx.block("Vercel login did not complete successfully.")
        await ctx.set_state(WebTaskState.DASHBOARD, "Authenticated Vercel session.")
        await ctx.add_check("vercel_authenticated")
        return None

    async def run(self, ctx: WebTaskContext) -> WebTaskResult:
        ensured = await self._ensure_logged_in(ctx)
        if ensured:
            return ensured
        page = await ctx.page()
        if ctx.request.task_type == "login_or_signup":
            return await ctx.complete({"vercel": {"authenticated": True, "account_url": page.url}})
        if ctx.request.task_type == "github_connect_check":
            await ctx.goto("https://vercel.com/account/login-connections", WebTaskState.SETTINGS)
            text = (await page.inner_text("body")).lower()
            connected = "github" in text and ("connected" in text or "disconnect" in text)
            if connected:
                await ctx.add_check("github_connected")
                return await ctx.complete({"vercel": {"github_connected": True}})
            return await ctx.block("GitHub is not connected in Vercel login connections.")

        await ctx.goto("https://vercel.com/account/tokens", WebTaskState.API_KEYS)
        try:
            await page.click("button:has-text('Create'), button:has-text('Create Token')", timeout=8_000)
        except Exception:
            pass
        for selector in ("input[placeholder='Token Name']", "input[name='name']", "input[placeholder='Name']"):
            try:
                await page.fill(selector, "Astra", timeout=4_000)
                break
            except Exception:
                continue
        try:
            await page.click("button:has-text('Create Token'), button[type='submit']", timeout=8_000)
        except Exception:
            pass
        token = ""
        for selector in ("input[readonly]", "input[value]", "[data-testid='token-value']", "code", ".copyable"):
            try:
                el = await page.query_selector(selector)
                if el:
                    token = ((await el.get_attribute("value")) or (await el.inner_text()) or "").strip()
                    if len(token) > 10:
                        break
            except Exception:
                continue
        if not token:
            return await ctx.block("Could not extract Vercel deploy token.")
        ctx.persist_credentials("vercel", {"token": token})
        await ctx.add_check("deploy_token_extracted")
        return await ctx.complete({"vercel": {"token": token, "account_url": page.url}})
