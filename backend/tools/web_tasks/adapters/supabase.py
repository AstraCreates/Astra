from __future__ import annotations

from backend.tools.supabase_tools import supabase_create_project
from backend.tools.web_tasks.base import WebTaskAdapter, WebTaskContext
from backend.tools.web_tasks.models import WebTaskResult, WebTaskState


class SupabaseAdapter(WebTaskAdapter):
    service = "supabase"
    supported_task_types = ("login_or_signup", "create_project", "retrieve_project_keys")

    async def _ensure_logged_in(self, ctx: WebTaskContext) -> WebTaskResult | None:
        await ctx.goto("https://app.supabase.com/sign-in", WebTaskState.LOGIN)
        page = await ctx.page()
        if "sign-in" in page.url or "signin" in page.url:
            maybe = await self._require_login_credentials(ctx)
            if maybe:
                return maybe
            try:
                await self._submit_login_form(
                    ctx,
                    "input[type='email'], input[name='email']",
                    "input[type='password'], input[name='password']",
                    "button[type='submit'], button:has-text('Sign in')",
                )
            except Exception:
                return await ctx.block("Supabase login form could not be submitted.")
        blocker = await ctx.detect_human_blocker()
        if blocker:
            return await ctx.needs_user(blocker.kind, blocker.message, blocker.fields)
        if await ctx.maybe_handle_email_verification():
            await ctx.add_check("email_verified")
        page = await self._latest_page(ctx)
        if "sign-in" in page.url or "signin" in page.url:
            return await ctx.block("Supabase login did not complete successfully.")
        await ctx.set_state(WebTaskState.DASHBOARD, "Authenticated Supabase session.")
        await ctx.add_check("supabase_authenticated")
        return None

    async def run(self, ctx: WebTaskContext) -> WebTaskResult:
        if ctx.request.task_type == "create_project":
            project_name = (
                ctx.request.metadata.get("project_name")
                or ctx.request.metadata.get("company_name")
                or "astra-app"
            )
            result = supabase_create_project(project_name=project_name)
            if not result.get("project_ref"):
                # Fall back to browser login if management token is unavailable.
                ensured = await self._ensure_logged_in(ctx)
                if ensured:
                    return ensured
                await ctx.goto("https://app.supabase.com/projects", WebTaskState.RESOURCE_CREATE)
                return await ctx.needs_user(
                    "manual_project_creation",
                    "Supabase project creation needs either a management token or manual dashboard completion.",
                    [],
                )
            artifacts = {
                "supabase": {
                    "project_ref": result.get("project_ref"),
                    "anon_key": result.get("anon_key"),
                    "service_role_key": result.get("service_role_key"),
                    "dashboard_url": result.get("dashboard_url"),
                }
            }
            if result.get("dashboard_url"):
                ctx.snapshot.current_url = result["dashboard_url"]
                ctx.snapshot.evidence.final_url = result["dashboard_url"]
            await ctx.add_check("project_created")
            await ctx.add_check("project_keys_extracted")
            return await ctx.complete(artifacts)

        ensured = await self._ensure_logged_in(ctx)
        if ensured:
            return ensured
        page = await ctx.page()
        if ctx.request.task_type == "login_or_signup":
            return await ctx.complete({"supabase": {"authenticated": True, "dashboard_url": page.url}})

        await ctx.goto(
            ctx.request.start_url or ctx.request.metadata.get("project_url") or "https://app.supabase.com/projects",
            WebTaskState.API_KEYS,
        )
        page_text = (await page.inner_text("body")).lower()
        found = {}
        if "anon" in page_text or "service role" in page_text:
            found = {
                key: value
                for key, value in ctx.snapshot.artifacts.get("supabase", {}).items()
                if key in {"anon_key", "service_role_key"}
            }
            found.update({})
        scanned = {}
        try:
            scanned = await page.evaluate(
                """() => {
                    const values = Array.from(document.querySelectorAll('input, code, pre'))
                      .map((el) => (el.value || el.innerText || '').trim())
                      .filter(Boolean);
                    const out = {};
                    for (const value of values) {
                      if (!out.anon_key && value.startsWith('ey') && value.length > 80) out.anon_key = value;
                      if (!out.project_url && value.startsWith('https://') && value.includes('supabase.co')) out.project_url = value;
                    }
                    return out;
                }"""
            )
        except Exception:
            scanned = {}
        artifacts = {"supabase": scanned}
        if scanned.get("anon_key"):
            await ctx.add_check("project_keys_extracted")
            return await ctx.complete(artifacts)
        return await ctx.block("Could not extract Supabase project keys from the dashboard.")
