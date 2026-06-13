from __future__ import annotations

import re

from backend.config import settings
from backend.tools.web_tasks.base import WebTaskAdapter, WebTaskContext
from backend.tools.web_tasks.models import WebTaskResult, WebTaskState


class YelpAdapter(WebTaskAdapter):
    service = "yelp"
    supported_task_types = ("login_or_signup", "retrieve_api_key")

    async def _ensure_logged_in(self, ctx: WebTaskContext) -> WebTaskResult | None:
        await ctx.goto("https://fusion.yelp.com/", WebTaskState.LOGIN)
        page = await ctx.page()
        blocker = await ctx.detect_human_blocker()
        if blocker:
            return await ctx.needs_user(blocker.kind, blocker.message, blocker.fields)
        page = await self._latest_page(ctx)
        if "login" in page.url and "fusion.yelp.com" not in page.url:
            maybe = await self._require_login_credentials(ctx)
            if maybe:
                return maybe
        if "fusion.yelp.com" not in page.url and "yelp.com/developers" not in page.url:
            return await ctx.block("Yelp login did not complete successfully.")
        await ctx.set_state(WebTaskState.DASHBOARD, "Authenticated Yelp Fusion session.")
        await ctx.add_check("yelp_authenticated")
        return None

    async def run(self, ctx: WebTaskContext) -> WebTaskResult:
        ensured = await self._ensure_logged_in(ctx)
        if ensured:
            return ensured
        page = await ctx.page()
        if ctx.request.task_type == "login_or_signup":
            return await ctx.complete({"yelp": {"authenticated": True, "account_url": page.url}})
        await ctx.goto("https://www.yelp.com/developers/v3/manage_app", WebTaskState.API_KEYS)
        try:
            create_btn = await page.query_selector("a:has-text('Create New App'), button:has-text('Create App')")
            if create_btn:
                await create_btn.click()
                for selector in ("input[name='app_name']", "input[placeholder='App Name']"):
                    try:
                        await page.fill(selector, "Astra", timeout=3_000)
                        break
                    except Exception:
                        continue
                try:
                    await page.select_option("select[name='industry_name']", index=1, timeout=3_000)
                except Exception:
                    pass
                try:
                    email = getattr(settings, "test_email_base", "") or ""
                    if email:
                        await page.fill("input[name='contact_email'], input[type='email']", email, timeout=3_000)
                except Exception:
                    pass
                try:
                    await page.check("input[type='checkbox']", timeout=3_000)
                except Exception:
                    pass
                try:
                    await page.click("button[type='submit'], button:has-text('Submit')", timeout=6_000)
                except Exception:
                    pass
        except Exception:
            pass
        api_key = ""
        for selector in (
            "input[name='api_key']",
            "input[readonly][value]",
            "code",
            ".api-key",
            "[data-testid='api-key']",
            "p:has-text('API Key') + code",
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
            try:
                content = await page.content()
                matches = re.findall(r"[A-Za-z0-9_-]{40,}", content)
                api_key = matches[0] if matches else ""
            except Exception:
                api_key = ""
        if not api_key:
            return await ctx.block("Could not extract Yelp API key.")
        ctx.persist_credentials("yelp", {"api_key": api_key})
        await ctx.add_check("api_key_extracted")
        return await ctx.complete({"yelp": {"api_key": api_key, "account_url": page.url}})
