"""
Headed/headless browser session for agent computer use.
Each agent run gets one persistent session — actions share state across the full run.
"""
import asyncio
import base64
import logging
from pathlib import Path
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


def _launch_config() -> dict[str, Any]:
    from backend.config import settings

    args = list(_STEALTH_ARGS)
    headless = settings.browser_headless
    ext = (settings.capsolver_extension_path or "").strip()
    if ext and Path(ext).exists() and not headless:
        args.extend([
            f"--disable-extensions-except={ext}",
            f"--load-extension={ext}",
        ])
    proxy_server = (settings.browser_proxy_server or "").strip()
    proxy_username = (settings.browser_proxy_username or "").strip()
    proxy_password = (settings.browser_proxy_password or "").strip()
    config: dict[str, Any] = {"headless": headless, "args": args}
    if proxy_server:
        config["proxy"] = {
            "server": proxy_server,
            **({"username": proxy_username} if proxy_username else {}),
            **({"password": proxy_password} if proxy_password else {}),
        }
    return config


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
        launch = _launch_config()
        if self.headless is not None:
            launch["headless"] = self.headless
        self._browser = await self._pw.chromium.launch(**launch)
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
        """Clean summary of current page — URL, title, text, forms, and interactive elements."""
        p = self._page
        if p is None:
            return {}
        title = ""
        body = ""
        links: list = []
        forms: list = []
        elements: list = []
        try:
            title = await p.title()
            html = await p.content()
            from backend.tools.page_fetcher import _extract
            body, _, links = _extract(html, base_url=p.url)
        except Exception:
            try:
                body = await p.inner_text("body")
            except Exception:
                body = ""
        try:
            forms = await p.evaluate("""() => {
                return Array.from(document.querySelectorAll('input,textarea,select')).slice(0,20).map(el => ({
                    tag: el.tagName.toLowerCase(),
                    type: el.type || '',
                    name: el.name || '',
                    id: el.id || '',
                    placeholder: el.placeholder || '',
                    label: el.getAttribute('aria-label') || el.getAttribute('autocomplete') || '',
                }));
            }""")
        except Exception:
            forms = []
        try:
            elements = await p.evaluate("""() => {
                const els = Array.from(document.querySelectorAll(
                    'a,button,[role="button"],input[type="submit"],input[type="button"]'
                )).slice(0,30);
                return els.map(el => ({
                    tag: el.tagName.toLowerCase(),
                    text: (el.innerText||el.value||el.getAttribute('aria-label')||'').trim().slice(0,80),
                    id: el.id||'',
                    href: el.href||'',
                })).filter(el => el.text||el.id||el.href);
            }""")
        except Exception:
            elements = []
        return {
            "url": p.url,
            "title": title,
            "body_text": body[:8000],
            "links_on_page": links[:10],
            "form_fields": forms,
            "interactive_elements": elements[:20],
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
                    return Array.from(els).slice(0, 50).map((el, i) => ({
                        tag: el.tagName.toLowerCase(),
                        type: el.type || '',
                        text: (el.innerText || el.value || el.placeholder || '').slice(0, 100).trim(),
                        id: el.id || '',
                        name: el.name || '',
                        href: el.href || '',
                        index: i,
                    })).filter(el => el.text.length > 0);
                }""")
                return {"elements": elements}

            elif act == "read_page":
                # Extract clean readable content from current page (strips ads/nav/footer)
                html = await p.content()
                from backend.tools.page_fetcher import _extract
                text, title, links = _extract(html, base_url=p.url)
                return {
                    "url": p.url,
                    "title": title,
                    "text": text[:6000],
                    "links": links[:15],
                    "truncated": len(text) > 6000,
                }

            elif act == "scroll_to":
                # Scroll until element matching text is visible
                target_text = action.get("text", "")
                selector = action.get("selector", "")
                if selector:
                    await p.scroll_into_view_if_needed(selector, timeout=5000)
                    return {"ok": True, "scrolled_to": selector}
                elif target_text:
                    # Find element containing text and scroll to it
                    el = await p.get_by_text(target_text).first.element_handle()
                    if el:
                        await el.scroll_into_view_if_needed()
                        return {"ok": True, "scrolled_to": target_text}
                    return {"ok": False, "error": f"Text not found: {target_text}"}
                else:
                    await p.mouse.wheel(0, action.get("delta_y", 500))
                    return {"ok": True}

            elif act == "extract_table":
                tables = await p.evaluate("""() => {
                    return Array.from(document.querySelectorAll('table')).slice(0, 3).map(table => {
                        const headers = Array.from(table.querySelectorAll('th')).map(th => th.innerText.trim());
                        const rows = Array.from(table.querySelectorAll('tr')).slice(1).map(tr =>
                            Array.from(tr.querySelectorAll('td')).map(td => td.innerText.trim())
                        ).filter(row => row.some(cell => cell.length > 0));
                        return { headers, rows: rows.slice(0, 20) };
                    });
                }""")
                return {"tables": tables}

            elif act == "select_option":
                # Select a dropdown option by value or label
                selector = action.get("selector", "select")
                value = action.get("value")
                label = action.get("label")
                if value is not None:
                    await p.select_option(selector, value=value, timeout=8_000)
                elif label is not None:
                    await p.select_option(selector, label=label, timeout=8_000)
                else:
                    return {"error": "select_option requires 'value' or 'label'"}
                return {"ok": True}

            elif act == "hover":
                # Hover over element to reveal dropdown menus
                selector = action.get("selector")
                if selector:
                    await p.hover(selector, timeout=8_000)
                else:
                    await p.mouse.move(action.get("x", 0), action.get("y", 0))
                await asyncio.sleep(0.4)
                return {"ok": True}

            elif act == "clear":
                # Clear an input field before typing
                selector = action.get("selector", "input:focus")
                await p.fill(selector, "", timeout=8_000)
                return {"ok": True}

            elif act == "get_attribute":
                # Get an HTML attribute from an element (useful for hidden values, hrefs, data-*)
                selector = action.get("selector")
                attr = action.get("attribute", "value")
                if not selector:
                    return {"error": "get_attribute requires 'selector'"}
                el = await p.query_selector(selector)
                if not el:
                    return {"error": f"No element found: {selector}"}
                val = await el.get_attribute(attr) or await el.inner_text()
                return {"value": val.strip() if val else ""}

            elif act == "eval_js":
                # Execute arbitrary JS and return the result — for complex extractions
                script = action.get("script", "")
                if not script:
                    return {"error": "eval_js requires 'script'"}
                result = await p.evaluate(script)
                return {"result": result}

            elif act == "wait_for_text":
                # Wait until specific text appears on the page
                text = action.get("text", "")
                timeout_ms = action.get("timeout_ms", 15_000)
                try:
                    await p.wait_for_selector(f"text={text}", timeout=timeout_ms)
                    return {"ok": True, "found": text}
                except Exception:
                    return {"ok": False, "error": f"Text not found within {timeout_ms}ms: {text}"}

            elif act == "wait_for_url":
                # Wait until URL contains a substring — useful for OAuth redirects
                contains = action.get("contains", "")
                timeout_ms = action.get("timeout_ms", 30_000)
                try:
                    await p.wait_for_url(f"**{contains}**", timeout=timeout_ms)
                    return {"ok": True, "url": p.url}
                except Exception:
                    return {"ok": False, "current_url": p.url, "error": f"URL never contained '{contains}'"}

            elif act == "upload_file":
                # Set a file input to a local path
                selector = action.get("selector", "input[type=file]")
                file_path = action.get("file_path", "")
                await p.set_input_files(selector, file_path, timeout=8_000)
                return {"ok": True}

            elif act == "check":
                # Check or uncheck a checkbox/radio
                selector = action.get("selector")
                checked = action.get("checked", True)
                if not selector:
                    return {"error": "check requires 'selector'"}
                if checked:
                    await p.check(selector, timeout=8_000)
                else:
                    await p.uncheck(selector, timeout=8_000)
                return {"ok": True}

            elif act == "new_tab":
                # Open a new tab and navigate to a URL
                new_page = await p._browser.new_page()  # type: ignore[attr-defined]
                self._page = new_page
                if _STEALTH_AVAILABLE:
                    await _stealth(new_page)
                url = action.get("url")
                if url:
                    await new_page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                return {"ok": True, "url": new_page.url}

            else:
                return {"error": (
                    f"unknown action: {act}. Valid: navigate, click, type, scroll, key, wait, "
                    "get_text, screenshot, find_elements, read_page, scroll_to, extract_table, "
                    "select_option, hover, clear, get_attribute, eval_js, wait_for_text, "
                    "wait_for_url, upload_file, check, new_tab"
                )}

        except Exception as e:
            return {"error": str(e)}
