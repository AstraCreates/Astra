from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any

from backend.computer_use.browser import BrowserSession
from backend.core.events import publish
from backend.provisioning.credentials_store import load_credentials, store_credentials
from backend.tools.page_fetcher import _extract
from backend.tools.web_navigator_tools import (
    _looks_like_email_verification,
    _scan_for_keys,
    _vision_next_action,
    check_email_for_verification,
)
from backend.tools.web_tasks.models import (
    WebTaskBlocker,
    WebTaskEvidence,
    WebTaskRequest,
    WebTaskResult,
    WebTaskSnapshot,
    WebTaskState,
)
from backend.tools.web_tasks.store import emit_task_event, save_screenshot, save_snapshot


@dataclass
class WebTaskContext:
    request: WebTaskRequest
    snapshot: WebTaskSnapshot
    browser: BrowserSession | None = None
    history: list[dict[str, Any]] = field(default_factory=list)

    async def emit(self, event_type: str, **payload: Any) -> None:
        event = {
            "type": event_type,
            "task_id": self.snapshot.task_id,
            "service": self.request.service,
            "task_type": self.request.task_type,
            "agent": self.request.agent,
            **payload,
        }
        await emit_task_event(self.snapshot.task_id, event)
        if self.request.session_id:
            await publish(self.request.session_id, event)

    @property
    def task_id(self) -> str:
        return self.snapshot.task_id

    @property
    def credentials(self) -> dict[str, Any]:
        return self.snapshot.credentials

    async def ensure_browser(self) -> BrowserSession:
        if self.browser is None:
            self.browser = BrowserSession(headless=True)
            await self.browser.start()
        return self.browser

    async def page(self):
        browser = await self.ensure_browser()
        return browser._page

    async def goto(self, url: str, state: WebTaskState | None = None) -> None:
        page = await self.page()
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        try:
            await page.wait_for_load_state("networkidle", timeout=5_000)
        except Exception:
            pass
        self.snapshot.current_url = page.url
        if state is not None:
            await self.set_state(state)

    async def set_state(self, state: WebTaskState, note: str = "") -> None:
        self.snapshot.state = state
        self.snapshot.evidence.state = state.value
        if note:
            self.snapshot.notes.append(note)
        await self.capture_page_summary()
        save_snapshot(self.snapshot)
        await self.emit(
            "web_task_state",
            state=state.value,
            note=note,
            url=self.snapshot.current_url,
        )

    async def capture_page_summary(self, screenshot_name: str = "") -> None:
        if self.browser is None:
            return
        try:
            page = await self.page()
        except Exception:
            return
        if page is None:
            return
        try:
            html = await page.content()
            text, title, _ = _extract(html, base_url=page.url)
            summary = f"{title}\n\n{text[:3000]}".strip()
        except Exception:
            try:
                summary = await page.inner_text("body")
            except Exception:
                summary = ""
        self.snapshot.current_url = getattr(page, "url", "") or self.snapshot.current_url
        self.snapshot.evidence.final_url = self.snapshot.current_url
        self.snapshot.evidence.page_summary = summary[:3000]
        if screenshot_name:
            try:
                png = await page.screenshot(type="png")
            except Exception:
                png = b""
            if png:
                screenshot_path = save_screenshot(
                    self.request.session_id,
                    self.task_id,
                    screenshot_name,
                    png,
                )
                if screenshot_path not in self.snapshot.evidence.screenshots:
                    self.snapshot.evidence.screenshots.append(screenshot_path)

    async def add_check(self, check: str) -> None:
        if check and check not in self.snapshot.evidence.checks_passed:
            self.snapshot.evidence.checks_passed.append(check)
            save_snapshot(self.snapshot)

    async def complete(self, artifacts: dict[str, Any] | None = None) -> WebTaskResult:
        missing_checks = [
            check
            for check in self.request.success_criteria
            if check and check not in self.snapshot.evidence.checks_passed
        ]
        if missing_checks:
            return await self.block(
                "Verification incomplete: missing checks "
                + ", ".join(sorted(missing_checks))
            )
        if artifacts:
            self.snapshot.artifacts.update(artifacts)
        self.snapshot.status = "completed"
        self.snapshot.state = WebTaskState.DONE
        await self.capture_page_summary(screenshot_name=f"{self.task_id}-done")
        save_snapshot(self.snapshot)
        result = WebTaskResult(
            status="completed",
            service=self.request.service,
            task_type=self.request.task_type,
            artifacts=dict(self.snapshot.artifacts),
            evidence=self.snapshot.evidence,
            blocker=WebTaskBlocker(),
            resume_token=self.task_id,
        )
        await self.emit("web_task_completed", result=result.to_dict())
        return result

    async def needs_user(
        self,
        kind: str,
        message: str,
        fields: list[dict[str, Any]] | None = None,
    ) -> WebTaskResult:
        self.snapshot.status = "needs_user"
        self.snapshot.state = WebTaskState.NEEDS_USER
        self.snapshot.blocker = WebTaskBlocker(kind=kind, message=message, fields=list(fields or []))
        await self.capture_page_summary(screenshot_name=f"{self.task_id}-needs-user")
        save_snapshot(self.snapshot)
        result = WebTaskResult(
            status="needs_user",
            service=self.request.service,
            task_type=self.request.task_type,
            artifacts=dict(self.snapshot.artifacts),
            evidence=self.snapshot.evidence,
            blocker=self.snapshot.blocker,
            resume_token=self.task_id,
        )
        await self.emit("web_task_needs_user", blocker=self.snapshot.blocker.to_dict(), result=result.to_dict())
        return result

    async def block(self, message: str) -> WebTaskResult:
        self.snapshot.status = "blocked"
        self.snapshot.state = WebTaskState.BLOCKED
        self.snapshot.blocker = WebTaskBlocker(kind="blocked", message=message, fields=[])
        await self.capture_page_summary(screenshot_name=f"{self.task_id}-blocked")
        save_snapshot(self.snapshot)
        result = WebTaskResult(
            status="blocked",
            service=self.request.service,
            task_type=self.request.task_type,
            artifacts=dict(self.snapshot.artifacts),
            evidence=self.snapshot.evidence,
            blocker=self.snapshot.blocker,
            resume_token=self.task_id,
        )
        await self.emit("web_task_failed", result=result.to_dict())
        return result

    async def fail(self, message: str) -> WebTaskResult:
        self.snapshot.status = "failed"
        self.snapshot.state = WebTaskState.FAILED
        self.snapshot.blocker = WebTaskBlocker(kind="failed", message=message, fields=[])
        await self.capture_page_summary(screenshot_name=f"{self.task_id}-failed")
        save_snapshot(self.snapshot)
        result = WebTaskResult(
            status="failed",
            service=self.request.service,
            task_type=self.request.task_type,
            artifacts=dict(self.snapshot.artifacts),
            evidence=self.snapshot.evidence,
            blocker=self.snapshot.blocker,
            resume_token=self.task_id,
        )
        await self.emit("web_task_failed", result=result.to_dict())
        return result

    def persist_credentials(self, service: str, creds: dict[str, Any]) -> None:
        if not self.request.founder_id or not creds:
            return
        store_credentials(self.request.founder_id, service, creds)

    def merge_credentials(self) -> None:
        stored = load_credentials(self.request.founder_id, self.request.service) or {}
        merged = dict(stored)
        merged.update(self.snapshot.credentials)
        merged.update(self.request.credentials)
        merged.update(self.snapshot.input_data)
        self.snapshot.credentials = merged

    async def detect_human_blocker(self) -> WebTaskBlocker | None:
        page = await self.page()
        text = ""
        try:
            text = await page.inner_text("body")
        except Exception:
            pass
        lowered = text.lower()
        if "captcha" in lowered or "turnstile" in lowered or "verify you are human" in lowered:
            return WebTaskBlocker(
                kind="captcha",
                message="This flow requires CAPTCHA or bot-verification.",
                fields=[],
            )
        if "two-factor" in lowered or "two factor" in lowered or "authenticator app" in lowered:
            return WebTaskBlocker(
                kind="2fa",
                message="This flow requires a two-factor authentication code.",
                fields=[{"key": "otp_code", "label": "2FA code", "type": "text"}],
            )
        if "phone number" in lowered and "verification" in lowered:
            return WebTaskBlocker(
                kind="phone_verification",
                message="This flow requires phone verification.",
                fields=[{"key": "phone_number", "label": "Phone number", "type": "tel"}],
            )
        if "payment" in lowered and ("card number" in lowered or "billing address" in lowered):
            return WebTaskBlocker(
                kind="payment_confirmation",
                message="This flow requires payment confirmation.",
                fields=[
                    {"key": "card_number", "label": "Card number", "type": "text"},
                    {"key": "cvv", "label": "CVV", "type": "password"},
                    {"key": "zip", "label": "ZIP", "type": "text"},
                ],
            )
        return None

    async def maybe_handle_email_verification(self) -> bool:
        page = await self.page()
        try:
            text = await page.inner_text("body")
        except Exception:
            text = ""
        if not _looks_like_email_verification(text):
            return False
        service_hint = self.request.service or self.request.goal
        verification = await check_email_for_verification(service_hint, timeout_seconds=45)
        link = verification.get("link", "")
        code = verification.get("code", "")
        if link:
            await page.goto(link, wait_until="domcontentloaded", timeout=30_000)
            await self.set_state(WebTaskState.VERIFY_EMAIL, "Opened email verification link.")
            return True
        if code:
            try:
                await page.fill("input[autocomplete='one-time-code'], input[name*='code' i], input[id*='code' i]", code, timeout=6_000)
            except Exception:
                await page.keyboard.type(code)
            try:
                await page.keyboard.press("Enter")
            except Exception:
                pass
            await self.set_state(WebTaskState.VERIFY_EMAIL, "Filled email verification code.")
            return True
        return False

    async def execute_vision_fallback(self, goal: str) -> bool:
        page = await self.page()
        import base64

        png = await page.screenshot(type="png")
        screenshot_b64 = base64.b64encode(png).decode()
        page_context = {
            "url": page.url,
            "title": await page.title(),
            "body_text": (await page.inner_text("body"))[:4000],
        }
        action = await asyncio.to_thread(
            _vision_next_action,
            screenshot_b64,
            goal,
            self.history,
            self.snapshot.credentials,
            page_context,
        )
        self.history.append({"action": action.get("action", ""), "url": page.url})
        act = action.get("action")
        if act == "need_input":
            return False
        if act == "navigate" and action.get("url"):
            await page.goto(action["url"], wait_until="domcontentloaded", timeout=30_000)
            return True
        if act == "click_text" and action.get("text"):
            try:
                await page.get_by_text(action["text"], exact=False).first.click(timeout=8_000)
                return True
            except Exception:
                return False
        if act == "click" and action.get("selector"):
            try:
                await page.click(action["selector"], timeout=8_000)
                return True
            except Exception:
                return False
        if act == "type_credential" and action.get("selector"):
            value = str(self.snapshot.credentials.get(action.get("credential_key", ""), ""))
            if not value:
                return False
            try:
                await page.fill(action["selector"], value, timeout=8_000)
                return True
            except Exception:
                return False
        if act == "type":
            value = str(action.get("text", ""))
            try:
                if action.get("selector"):
                    await page.fill(action["selector"], value, timeout=8_000)
                else:
                    await page.keyboard.type(value)
                return True
            except Exception:
                return False
        if act == "key" and action.get("key"):
            try:
                await page.keyboard.press(action["key"])
                return True
            except Exception:
                return False
        if act == "scroll":
            await page.mouse.wheel(0, int(action.get("delta_y", 300)))
            return True
        return False

    async def close(self) -> None:
        if self.browser and self.browser._started:
            await self.browser.stop()


def default_login_fields() -> list[dict[str, Any]]:
    return [
        {"key": "email", "label": "Email", "type": "email"},
        {"key": "password", "label": "Password", "type": "password"},
    ]


class WebTaskAdapter:
    service = ""
    supported_task_types: tuple[str, ...] = ()

    async def run(self, ctx: WebTaskContext) -> WebTaskResult:
        raise NotImplementedError

    def supports(self, task_type: str) -> bool:
        return task_type in self.supported_task_types

    async def _require_login_credentials(self, ctx: WebTaskContext) -> WebTaskResult | None:
        email = ctx.credentials.get("email") or ctx.credentials.get("username")
        password = ctx.credentials.get("password")
        if email and password:
            return None
        return await ctx.needs_user(
            kind="missing_credentials",
            message=f"{self.service} requires login credentials to continue.",
            fields=default_login_fields(),
        )

    async def _submit_login_form(
        self,
        ctx: WebTaskContext,
        email_selector: str,
        password_selector: str,
        submit_selector: str,
    ) -> None:
        page = await ctx.page()
        email = str(ctx.credentials.get("email") or ctx.credentials.get("username") or "")
        password = str(ctx.credentials.get("password") or "")
        await page.fill(email_selector, email, timeout=8_000)
        await page.fill(password_selector, password, timeout=8_000)
        await page.click(submit_selector, timeout=8_000)
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=10_000)
        except Exception:
            pass

    async def _latest_page(self, ctx: WebTaskContext):
        page = await ctx.page()
        try:
            pages = list(page.context.pages)
        except Exception:
            return page
        if not pages:
            return page
        latest = pages[-1]
        if latest is not page:
            ctx.browser._page = latest  # type: ignore[union-attr]
            try:
                await latest.wait_for_load_state("domcontentloaded", timeout=5_000)
            except Exception:
                pass
            return latest
        return page
