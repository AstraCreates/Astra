"""
Headed/headless browser session for agent computer use.
Each agent run gets one persistent session — actions share state across the full run.
"""
import asyncio
import base64
import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    from playwright.async_api import async_playwright, Page, Browser
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False
    logger.warning("playwright not installed — browser actions disabled")

try:
    from playwright_stealth import stealth_async as _stealth
    _STEALTH_AVAILABLE = True
except ImportError:
    _STEALTH_AVAILABLE = False

_STEALTH_ARGS = [
    "--no-sandbox",
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars",
    "--disable-dev-shm-usage",
    "--disable-extensions",
]
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class BrowserSession:
    def __init__(self, headless: bool = True):
        self.headless = headless
        self._pw = None
        self._browser: "Browser | None" = None
        self._page: "Page | None" = None
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        if not _PLAYWRIGHT_AVAILABLE:
            raise RuntimeError("playwright not installed. Run: pip install playwright && playwright install chromium")
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=self.headless,
            args=_STEALTH_ARGS,
        )
        self._page = await self._browser.new_page(
            viewport={"width": 1280, "height": 800},
            user_agent=_USER_AGENT,
        )
        if _STEALTH_AVAILABLE:
            await _stealth(self._page)
        self._started = True

    async def stop(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()
        self._started = False

    async def page_state(self) -> dict:
        """Text summary of current page — URL, title, body text (2000 chars)."""
        p = self._page
        if p is None:
            return {}
        try:
            title = await p.title()
            body = await p.inner_text("body")
        except Exception:
            body = ""
            title = ""
        return {
            "url": p.url,
            "title": title,
            "body_text": body[:2000],
        }

    async def execute_action(self, action: dict) -> dict:
        """
        Execute one browser action. Returns result dict.
        Actions:
          navigate  — {"action": "navigate", "url": "..."}
          click     — {"action": "click", "selector": "css"} or {"x": px, "y": px}
          type      — {"action": "type", "selector": "css", "text": "..."}
          scroll    — {"action": "scroll", "delta_x": 0, "delta_y": 200}
          key       — {"action": "key", "key": "Enter"}
          wait      — {"action": "wait", "ms": 1000}
          get_text  — {"action": "get_text", "selector": "css"} (defaults to body)
          screenshot — {"action": "screenshot"}
        """
        if not self._started:
            await self.start()

        p = self._page
        act = action.get("action", action.get("type", ""))

        try:
            if act == "navigate":
                await p.goto(action["url"], wait_until="domcontentloaded", timeout=30_000)
                # Extra wait for JS-heavy pages
                try:
                    await p.wait_for_load_state("networkidle", timeout=5_000)
                except Exception:
                    pass
                return {"ok": True, "url": p.url}

            elif act == "click":
                if "selector" in action:
                    await p.click(action["selector"], timeout=10_000)
                else:
                    await p.mouse.click(action["x"], action["y"])
                # Wait for any triggered navigation
                try:
                    await p.wait_for_load_state("domcontentloaded", timeout=5_000)
                except Exception:
                    pass
                return {"ok": True}

            elif act == "type":
                if "selector" in action:
                    await p.fill(action["selector"], action["text"])
                else:
                    await p.keyboard.type(action["text"])
                return {"ok": True}

            elif act == "scroll":
                await p.mouse.wheel(action.get("delta_x", 0), action.get("delta_y", 200))
                return {"ok": True}

            elif act == "key":
                await p.keyboard.press(action["key"])
                try:
                    await p.wait_for_load_state("domcontentloaded", timeout=5_000)
                except Exception:
                    pass
                return {"ok": True}

            elif act == "wait":
                await asyncio.sleep(action.get("ms", 1000) / 1000)
                return {"ok": True}

            elif act == "get_text":
                selector = action.get("selector", "body")
                try:
                    text = await p.inner_text(selector)
                except Exception:
                    text = await p.content()
                return {"text": text[:3000]}

            elif act == "screenshot":
                png = await p.screenshot(type="png")
                return {"screenshot_b64": base64.b64encode(png).decode()}

            elif act == "find_elements":
                # Returns text+selector hints for interactive elements
                elements = await p.evaluate("""() => {
                    const els = document.querySelectorAll('a, button, input, select, textarea, [role="button"]');
                    return Array.from(els).slice(0, 30).map(el => ({
                        tag: el.tagName.toLowerCase(),
                        type: el.type || '',
                        text: (el.innerText || el.value || el.placeholder || '').slice(0, 80),
                        id: el.id || '',
                        name: el.name || '',
                    }));
                }""")
                return {"elements": elements}

            else:
                return {"error": f"unknown action: {act}"}

        except Exception as e:
            return {"error": str(e)}
