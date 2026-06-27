"""Interactive openclaude takeover terminals.

Spawns an INTERACTIVE openclaude (`--resume <session-id>`) inside a real PTY,
in the same workspace the technical/web agent built in, so the founder can
take over the agent's exact session and drive it by hand. Output bytes are
pushed to a registered callback (the WebSocket); keystrokes are written back
to the PTY master.

Security: this runs openclaude with --dangerously-skip-permissions and is
reachable over a WebSocket → it is remote code execution as the `astra` user.
The WS endpoint MUST authenticate the founder and verify session ownership
before calling open_takeover(). See backend/api/routes.py terminal endpoint.
"""
from __future__ import annotations

import fcntl
import logging
import os
import pty
import signal
import struct
import subprocess
import termios
import threading
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

_lock = threading.Lock()


class PtyTerm:
    """One live PTY-backed openclaude session, keyed by app session id."""

    def __init__(self, app_session_id: str, master_fd: int, proc: subprocess.Popen, oc_session_id: str, workspace: str):
        self.app_session_id = app_session_id
        self.master_fd = master_fd
        self.proc = proc
        self.oc_session_id = oc_session_id
        self.workspace = workspace
        self.cols = 120
        self.rows = 32
        self._on_output: Callable[[bytes], None] | None = None
        self._alive = True
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def set_output(self, cb: Callable[[bytes], None] | None) -> None:
        self._on_output = cb

    def _read_loop(self) -> None:
        while self._alive:
            try:
                data = os.read(self.master_fd, 65536)
            except OSError:
                break
            if not data:
                break
            cb = self._on_output
            if cb:
                try:
                    cb(data)
                except Exception:
                    pass
        self._alive = False

    def write(self, data: bytes) -> None:
        if not self._alive:
            return
        try:
            os.write(self.master_fd, data)
        except OSError:
            self._alive = False

    def resize(self, cols: int, rows: int) -> None:
        self.cols, self.rows = cols, rows
        try:
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)
        except OSError:
            pass

    @property
    def alive(self) -> bool:
        return self._alive and (self.proc.poll() is None)

    def close(self) -> None:
        self._alive = False
        try:
            # Kill the whole process group (openclaude + children).
            os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
        except Exception:
            try:
                self.proc.terminate()
            except Exception:
                pass
        try:
            os.close(self.master_fd)
        except OSError:
            pass


_terminals: dict[str, PtyTerm] = {}


def get_terminal(app_session_id: str) -> PtyTerm | None:
    with _lock:
        term = _terminals.get(app_session_id)
        if term and not term.alive:
            _terminals.pop(app_session_id, None)
            return None
        return term


def open_takeover(app_session_id: str, cols: int = 120, rows: int = 32) -> PtyTerm:
    """Spawn (or return the existing) interactive openclaude PTY for this run.

    Resolves the run's build workspace, reads the persisted openclaude session
    id (.oc_session_id) and resumes it interactively. If no prior session id
    exists, starts a fresh interactive session in the workspace.
    """
    with _lock:
        existing = _terminals.get(app_session_id)
        if existing and existing.alive:
            existing.resize(cols, rows)
            return existing
        if existing:
            _terminals.pop(app_session_id, None)

    from backend.tools.git_tools import (
        OPENCLAUDE_BIN,
        _get_workspace,
        _root_session_id,
        _make_env,
        WORKSPACE_ROOT,
    )
    from backend.config import settings

    root_sid = _root_session_id(app_session_id)
    local, _is_github = _get_workspace("", root_sid)
    workspace = str(local)
    try:
        resolved_workspace = Path(workspace).resolve()
        resolved_root = WORKSPACE_ROOT.resolve()
        if not (resolved_workspace == resolved_root or resolved_root in resolved_workspace.parents):
            raise ValueError(f"refusing takeover outside workspace root: {resolved_workspace}")
    except Exception as exc:
        raise RuntimeError(str(exc))

    oc_session_id = ""
    try:
        oc_session_id = (Path(workspace) / ".oc_session_id").read_text().strip()
    except Exception:
        oc_session_id = ""

    env = _make_env()
    env["TERM"] = "xterm-256color"
    model = env.get("OPENAI_MODEL", "") or getattr(settings, "mvp_build_model", "") or "tencent/hy3-preview"
    is_caveman = getattr(settings, "code_agent", "caveman") == "caveman"

    if is_caveman:
        # Interactive caveman TUI resuming the build's session file (no -p).
        oc_args = [OPENCLAUDE_BIN, "--provider", "openrouter", "--model", model]
        cave_session = Path(workspace) / ".cave_session.json"
        if cave_session.exists():
            oc_args += ["--session", str(cave_session)]
    else:
        oc_args = [
            OPENCLAUDE_BIN,
            "--provider", "openai",
            "--model", model,
            "--allow-dangerously-skip-permissions",
            "--dangerously-skip-permissions",
        ]
        if oc_session_id:
            oc_args += ["--resume", oc_session_id]

    # The build runs the agent as the `astra` user (workspace is astra-owned, and
    # openclaude blocks --dangerously-skip-permissions as root). Mirror that: hand the
    # workspace to astra, drop privileges via sudo, passing creds through explicitly
    # (sudo resets the environment).
    if os.getuid() == 0:
        try:
            subprocess.run(["chown", "-R", "astra:astra", workspace], capture_output=True, timeout=120)
            subprocess.run(["chmod", "-R", "u+rwX", workspace], capture_output=True, timeout=120)
        except Exception:
            pass
        if is_caveman:
            passthrough = {
                "OPENROUTER_API_KEY": env.get("OPENROUTER_API_KEY", ""),
                "HOME": "/home/astra",
                "TERM": "xterm-256color",
                "npm_config_cache": env.get("npm_config_cache", ""),
            }
        else:
            passthrough = {
                "OPENAI_API_KEY": env.get("OPENAI_API_KEY", ""),
                "OPENAI_BASE_URL": env.get("OPENAI_BASE_URL", ""),
                "OPENAI_MODEL": model,
                "HOME": "/home/astra",
                "TERM": "xterm-256color",
                "npm_config_cache": env.get("npm_config_cache", ""),
            }
        env_pairs = [f"{k}={v}" for k, v in passthrough.items() if v]
        cmd = ["sudo", "-u", "astra", "env"] + env_pairs + oc_args
    else:
        cmd = oc_args

    master_fd, slave_fd = pty.openpty()
    # Set the initial window size on the slave before openclaude renders.
    try:
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, winsize)
    except OSError:
        pass

    proc = subprocess.Popen(
        cmd,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        cwd=workspace,
        env=env,
        start_new_session=True,  # own process group/session → killable, owns the tty
        close_fds=True,
    )
    os.close(slave_fd)  # parent keeps only the master

    term = PtyTerm(app_session_id, master_fd, proc, oc_session_id, workspace)
    term.cols, term.rows = cols, rows
    with _lock:
        _terminals[app_session_id] = term
    logger.info("PTY takeover opened for %s (oc_session=%s, ws=%s)", app_session_id, oc_session_id or "(fresh)", workspace)
    return term


def close_takeover(app_session_id: str) -> None:
    with _lock:
        term = _terminals.pop(app_session_id, None)
    if term:
        term.close()
        logger.info("PTY takeover closed for %s", app_session_id)
