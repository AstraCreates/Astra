from __future__ import annotations

from backend.tools import git_tools


def test_get_workspace_reuses_company_scoped_clone(monkeypatch):
    monkeypatch.setattr(git_tools.settings, "github_token", "ghs_test")
    calls: list[tuple[str, str | None]] = []

    def fake_clone(repo_url: str, session_id: str = "default", workspace_key: str | None = None) -> str:
        calls.append((session_id, workspace_key))
        return f"/tmp/{workspace_key or session_id}"

    monkeypatch.setattr(git_tools, "_ensure_clone", fake_clone)

    local, is_github = git_tools._get_workspace(
        "https://github.com/acme/app",
        "session_child",
        founder_id="founder_1",
        company_id="company_1",
    )

    assert is_github is True
    assert local == "/tmp/company-company_1"
    assert calls == [("session_child", "company-company_1")]


def test_stream_build_events_returns_and_publishes_stderr(monkeypatch):
    published: list[dict] = []

    class FakeProc:
        def __init__(self, *_args, **_kwargs):
            self.stdout = []
            self.stderr = ["Error: Detected 20.19.2. OpenClaude requires Node.js >=22.0.0.\n"]
            self.returncode = 1

        def kill(self):
            self.returncode = -9

        def wait(self, timeout: int | None = None):
            return self.returncode

    monkeypatch.setattr(git_tools.subprocess, "Popen", FakeProc)
    monkeypatch.setattr("backend.core.events.publish_sync", lambda _sid, event: published.append(event))
    monkeypatch.setattr(git_tools, "_record_build_usage", lambda *_args, **_kwargs: None)

    result = git_tools._stream_build_events(
        ["openclaude", "--print"],
        cwd="/tmp",
        timeout=1,
        env={},
        founder_id="founder_1",
        app_session_id="app_session_1",
        oc_session_id="oc_session_1",
        agent="technical",
    )

    assert "Node.js >=22.0.0" in result
    assert any(event.get("kind") == "error" and "Node.js >=22.0.0" in str(event.get("text", "")) for event in published)
    assert any(event.get("kind") == "done" and "Node.js >=22.0.0" in str(event.get("error", "")) for event in published)
