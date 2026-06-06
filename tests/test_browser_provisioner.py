from types import SimpleNamespace

from backend.provisioning import browser_provisioner as bp


class FakeLocator:
    def __init__(self, page, selector: str):
        self.page = page
        self.selector = selector
        self.first = self

    def count(self):
        return 1 if self.selector in self.page.available else 0

    def is_visible(self):
        return self.count() > 0

    def click(self, timeout=None):
        self.page.clicked.append(self.selector)

    def fill(self, value, timeout=None):
        self.page.filled.append((self.selector, value))


class FakePage:
    def __init__(self, *, url="https://example.com", content="", available=None, pages=None):
        self.url = url
        self._content = content
        self.available = set(available or [])
        self.clicked = []
        self.filled = []
        self.goto_calls = []
        self.waits = []
        self.context = SimpleNamespace(pages=pages or [self])

    def locator(self, selector):
        return FakeLocator(self, selector)

    def content(self):
        return self._content

    def goto(self, url, timeout=None):
        self.goto_calls.append(url)
        self.url = url

    def wait_for_timeout(self, ms):
        self.waits.append(ms)


def test_latest_page_prefers_new_popup_tab():
    first = FakePage(url="https://app.composio.dev/start")
    second = FakePage(url="https://accounts.google.com/o/oauth2/auth")
    first.context = SimpleNamespace(pages=[first, second])

    assert bp._latest_page(first) is second


def test_maybe_handle_email_challenge_fills_code(monkeypatch):
    page = FakePage(
        content="Check your email for a verification code",
        available={
            "input[autocomplete='one-time-code']",
            "button:has-text('Continue')",
        },
    )
    monkeypatch.setattr(
        "backend.testing.email_reader.wait_for_verification_code",
        lambda email, imap_password, service, timeout=90: "123456",
    )
    monkeypatch.setattr(
        "backend.testing.email_reader.wait_for_verification_url",
        lambda email, imap_password, service, timeout=90: None,
    )

    handled = bp._maybe_handle_email_challenge(page, "test@example.com", "pw", "notion")

    assert handled is True
    assert ("input[autocomplete='one-time-code']", "123456") in page.filled
    assert "button:has-text('Continue')" in page.clicked


def test_maybe_handle_email_challenge_throttles_repeat_attempts(monkeypatch):
    page = FakePage(
        url="https://www.notion.so/login",
        content="Check your email for a verification code",
        available={"input[autocomplete='one-time-code']"},
    )
    calls = {"code": 0, "link": 0}

    def fake_code(*args, **kwargs):
        calls["code"] += 1
        return None

    def fake_link(*args, **kwargs):
        calls["link"] += 1
        return None

    monkeypatch.setattr("backend.testing.email_reader.wait_for_verification_code", fake_code)
    monkeypatch.setattr("backend.testing.email_reader.wait_for_verification_url", fake_link)

    state = {}
    first = bp._maybe_handle_email_challenge(page, "test@example.com", "pw", "notion", deadline=bp.time.time() + 60, state=state)
    second = bp._maybe_handle_email_challenge(page, "test@example.com", "pw", "notion", deadline=bp.time.time() + 60, state=state)

    assert first is False
    assert second is False
    assert calls == {"code": 1, "link": 1}


def test_handle_google_login_can_pick_account_and_continue():
    page = FakePage(
        content="Choose an account",
        available={
            "text=user@gmail.com",
            "#identifierNext",
            "#passwordNext",
            "button:has-text('Continue')",
            "input[type='email']",
            "input[type='password']",
        },
    )

    bp._handle_google_login(page, "user@gmail.com", "secret")

    assert ("input[type='email']", "user@gmail.com") in page.filled
    assert ("input[type='password']", "secret") in page.filled
    assert "text=user@gmail.com" in page.clicked
    assert "button:has-text('Continue')" in page.clicked


def test_handle_notion_login_pushes_through_grant_access(monkeypatch):
    page = FakePage(
        content="Sign in to Notion",
        available={
            "text=Sign in",
            "input[type='email']",
            "button:has-text('Continue with email')",
            "input[type='password']",
            "button:has-text('Continue')",
            "button:has-text('Allow access')",
        },
    )
    monkeypatch.setattr(bp, "_maybe_handle_email_challenge", lambda *args, **kwargs: False)

    bp._handle_notion_login(page, "test@example.com", "secret", None)

    assert ("input[type='email']", "test@example.com") in page.filled
    assert ("input[type='password']", "secret") in page.filled
    assert "button:has-text('Allow access')" in page.clicked
