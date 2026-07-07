from __future__ import annotations

import os
from types import SimpleNamespace

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


def test_run_claude_sudo_command_does_not_put_secret_in_argv(monkeypatch, tmp_path):
    secret = "sk-openai-secret-value"
    seen: dict[str, object] = {}
    fake_bin = tmp_path / "openclaude"
    fake_bin.write_text("#!/bin/sh\n")
    fake_bin.chmod(0o755)

    monkeypatch.setattr(git_tools.settings, "code_agent", "openclaude", raising=False)
    monkeypatch.setattr(git_tools, "OPENCLAUDE_BIN", str(fake_bin))
    monkeypatch.setattr(git_tools.os, "getuid", lambda: 0)
    monkeypatch.setattr(
        git_tools,
        "_make_env",
        lambda: {
            "OPENAI_API_KEY": secret,
            "OPENAI_BASE_URL": "https://openrouter.example/api",
            "OPENAI_MODEL": "test/model",
            "npm_config_cache": "/tmp/npm-cache",
        },
    )
    monkeypatch.setattr(
        git_tools.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    def fake_stream(cmd, *_args, **_kwargs):
        seen["cmd"] = cmd
        env_file = cmd[cmd.index("astra-env") + 1]
        seen["env_file"] = env_file
        seen["env_mode"] = os.stat(env_file).st_mode & 0o777
        seen["env_text"] = open(env_file).read()
        return "ok"

    monkeypatch.setattr(git_tools, "_stream_build_events", fake_stream)

    assert git_tools._run_claude(str(tmp_path), "build it", app_session_id="app_session") == "ok"

    cmd = seen["cmd"]
    assert isinstance(cmd, list)
    assert all(secret not in arg for arg in cmd)
    assert "OPENAI_API_KEY=" not in " ".join(cmd)
    assert seen["env_mode"] == 0o600
    assert f"OPENAI_API_KEY={secret}" in seen["env_text"]
    assert not os.path.exists(str(seen["env_file"]))


def test_run_caveman_sudo_command_does_not_put_secret_in_argv(monkeypatch, tmp_path):
    secret = "sk-openrouter-secret-value"
    seen: dict[str, object] = {}
    fake_bin = tmp_path / "caveman"
    fake_bin.write_text("#!/bin/sh\n")
    fake_bin.chmod(0o755)

    monkeypatch.setattr(git_tools, "OPENCLAUDE_BIN", str(fake_bin))
    monkeypatch.setattr(git_tools.os, "getuid", lambda: 0)
    monkeypatch.setattr(
        git_tools,
        "_make_env",
        lambda: {
            "OPENROUTER_API_KEY": secret,
            "OPENAI_MODEL": "test/model",
            "npm_config_cache": "/tmp/npm-cache",
        },
    )
    monkeypatch.setattr(
        git_tools.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    def fake_stream(cmd, *_args, **_kwargs):
        seen["cmd"] = cmd
        env_file = cmd[cmd.index("astra-env") + 1]
        seen["env_file"] = env_file
        seen["env_mode"] = os.stat(env_file).st_mode & 0o777
        seen["env_text"] = open(env_file).read()
        return "ok"

    monkeypatch.setattr(git_tools, "_stream_caveman_events", fake_stream)

    assert git_tools._run_caveman(str(tmp_path), "build it") == "ok"

    cmd = seen["cmd"]
    assert isinstance(cmd, list)
    assert all(secret not in arg for arg in cmd)
    assert "OPENROUTER_API_KEY=" not in " ".join(cmd)
    assert seen["env_mode"] == 0o600
    assert f"OPENROUTER_API_KEY={secret}" in seen["env_text"]
    assert not os.path.exists(str(seen["env_file"]))


def test_make_env_prepends_rtk_shim_path_when_flag_enabled(monkeypatch):
    monkeypatch.setenv("ASTRA_CAVEMAN_RTK_SHIM", "true")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(git_tools.settings, "openrouter_base_url", "https://openrouter.example/api", raising=False)
    monkeypatch.setattr(git_tools.settings, "mvp_build_model", "test/model", raising=False)
    monkeypatch.setattr("backend.core.key_rotator.get_openrouter_key", lambda: "or-key")

    env = git_tools._make_env()

    assert env["PATH"] == "/opt/rtk-shims:/usr/bin:/bin"


def test_make_env_leaves_path_unchanged_when_rtk_shim_flag_disabled(monkeypatch):
    monkeypatch.delenv("ASTRA_CAVEMAN_RTK_SHIM", raising=False)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(git_tools.settings, "openrouter_base_url", "https://openrouter.example/api", raising=False)
    monkeypatch.setattr(git_tools.settings, "mvp_build_model", "test/model", raising=False)
    monkeypatch.setattr("backend.core.key_rotator.get_openrouter_key", lambda: "or-key")

    env = git_tools._make_env()

    assert env["PATH"] == "/usr/bin:/bin"
