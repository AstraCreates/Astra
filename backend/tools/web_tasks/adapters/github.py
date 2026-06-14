from __future__ import annotations

from backend.tools.web_tasks.base import WebTaskAdapter, WebTaskContext
from backend.tools.web_tasks.models import WebTaskResult, WebTaskState


class GitHubAdapter(WebTaskAdapter):
    service = "github"
    supported_task_types = ("login_or_signup", "oauth_connect", "repo_ready_check", "retrieve_api_key")

    async def run(self, ctx: WebTaskContext) -> WebTaskResult:
        page = await ctx.page()
        if ctx.request.task_type == "repo_ready_check":
            await ctx.goto("https://github.com/settings/profile", WebTaskState.DASHBOARD)
            if "github.com/login" in page.url:
                maybe = await self._require_login_credentials(ctx)
                if maybe:
                    return maybe
                await self._submit_login_form(ctx, "#login_field", "#password", "input[type='submit']")
            await ctx.add_check("github_authenticated")
            return await ctx.complete({"github": {"authenticated": "github.com/login" not in page.url}})

        await ctx.goto("https://github.com/login", WebTaskState.LOGIN)
        page = await self._latest_page(ctx)
        if "github.com/login" in page.url:
            maybe = await self._require_login_credentials(ctx)
            if maybe:
                return maybe
            await self._submit_login_form(ctx, "#login_field", "#password", "input[type='submit']")
            page = await self._latest_page(ctx)
        blocker = await ctx.detect_human_blocker()
        if blocker:
            return await ctx.needs_user(blocker.kind, blocker.message, blocker.fields)
        if "github.com/login" in page.url:
            return await ctx.block("GitHub login did not complete successfully.")
        await ctx.set_state(WebTaskState.DASHBOARD, "Authenticated GitHub session.")
        await ctx.add_check("github_authenticated")
        if ctx.request.task_type == "retrieve_api_key":
            await ctx.goto(
                "https://github.com/settings/tokens/new?description=Astra&scopes=repo,workflow,read:org",
                WebTaskState.API_KEYS,
            )
            try:
                await page.select_option("select#token_expiration", "0", timeout=4_000)
            except Exception:
                pass
            try:
                await page.click("button:has-text('Generate token'), input[type='submit']", timeout=8_000)
            except Exception:
                return await ctx.block("Could not submit the GitHub token creation form.")
            token = ""
            for selector in (
                "#new-oauth-token",
                "code#new-oauth-token",
                "input[aria-label='Token']",
                "input[value^='github_pat_']",
                ".token",
                "div.flash-full code",
            ):
                try:
                    el = await page.query_selector(selector)
                    if el:
                        token = ((await el.inner_text()) or (await el.get_attribute("value")) or "").strip()
                        if token.startswith("github_pat_") or token.startswith("ghp_"):
                            break
                except Exception:
                    continue
            if not (token.startswith("github_pat_") or token.startswith("ghp_")):
                return await ctx.block("Could not extract a valid GitHub personal access token.")
            ctx.persist_credentials("github", {"token": token})
            await ctx.add_check("github_token_extracted")
            return await ctx.complete({"github": {"token": token, "account_url": page.url}})
        if ctx.request.task_type == "oauth_connect":
            await ctx.add_check("github_oauth_ready")
        return await ctx.complete({"github": {"authenticated": True, "account_url": page.url}})
