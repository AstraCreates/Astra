from __future__ import annotations

from backend.tools.web_tasks.base import WebTaskContext, default_login_fields
from backend.tools.web_tasks.models import WebTaskResult, WebTaskState
from backend.tools.web_navigator_tools import _goal_requests_secret, _scan_for_keys


def _looks_authenticated(text: str, url: str) -> bool:
    lowered = text.lower()
    url_lower = url.lower()
    return any(
        marker in lowered or marker in url_lower
        for marker in (
            "dashboard",
            "settings",
            "api key",
            "developer",
            "account",
            "workspace",
            "/dashboard",
            "/settings",
        )
    )


def _criteria_matched(criteria: list[str], text: str, url: str) -> list[str]:
    lowered = text.lower()
    url_lower = url.lower()
    return [criterion for criterion in criteria if criterion.lower() in lowered or criterion.lower() in url_lower]


async def run_generic_web_task(ctx: WebTaskContext) -> WebTaskResult:
    if not ctx.request.start_url:
        return await ctx.block("Generic web tasks require a start_url.")
    await ctx.goto(ctx.request.start_url, WebTaskState.START)
    page = await ctx.page()
    used_vision = False
    for _ in range(8):
        blocker = await ctx.detect_human_blocker()
        if blocker:
            return await ctx.needs_user(blocker.kind, blocker.message, blocker.fields)
        await ctx.maybe_handle_email_verification()
        text = ""
        try:
            text = (await page.inner_text("body")).lower()
        except Exception:
            text = ""
        page_url = getattr(page, "url", "") or ""
        if _goal_requests_secret(ctx.request.goal):
            extracted = _scan_for_keys(text)
            if extracted:
                for key_type in extracted:
                    await ctx.add_check(key_type)
                return await ctx.complete({"generic": {"url": page_url, "extracted": extracted}})
        matched_criteria = _criteria_matched(ctx.request.success_criteria, text, page_url)
        if matched_criteria:
            for criterion in matched_criteria:
                await ctx.add_check(criterion)
            return await ctx.complete({"generic": {"url": page_url}})
        if not ctx.request.success_criteria and _looks_authenticated(text, page_url):
            await ctx.add_check("authenticated_state_detected")
            return await ctx.complete({"generic": {"url": page_url}})
        if any(word in text for word in ("sign in", "log in", "email", "password")):
            email = ctx.credentials.get("email") or ctx.credentials.get("username")
            password = ctx.credentials.get("password")
            if not (email and password):
                return await ctx.needs_user(
                    "missing_credentials",
                    "This website requires login credentials to continue.",
                    default_login_fields(),
                )
            try:
                await page.fill("input[type='email'], input[name='email']", str(email), timeout=5_000)
            except Exception:
                pass
            try:
                await page.fill("input[type='password'], input[name='password']", str(password), timeout=5_000)
            except Exception:
                pass
            try:
                await page.click("button[type='submit'], input[type='submit'], button:has-text('Continue')", timeout=5_000)
                await ctx.set_state(WebTaskState.LOGIN, "Submitted generic login form.")
                continue
            except Exception:
                pass
        if used_vision:
            break
        used_vision = await ctx.execute_vision_fallback(ctx.request.goal)
        if used_vision:
            await ctx.set_state(ctx.snapshot.state, "Used vision fallback for ambiguous page.")
            continue
    return await ctx.block("Could not complete the generic website flow with deterministic steps.")
