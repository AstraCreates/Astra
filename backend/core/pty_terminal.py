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

    def __init__(self, app_session_id: str, master_fd: int, proc: subprocess.Popen, oc_session_id: str, workspace: str, *, shared: bool = False):
        self.app_session_id = app_session_id
        self.master_fd = master_fd
        self.proc = proc
        self.oc_session_id = oc_session_id
        self.workspace = workspace
        self.cols = 120
        self.rows = 32
        self.shared = shared
        self.started_at = __import__("time").time()
        self._subscribers: dict[int, Callable[[bytes], None]] = {}
        self._next_subscriber = 1
        self._transcript = bytearray()
        self._transcript_limit = 512 * 1024
        # Persist the rolling transcript beside the workspace.  The PTY itself
        # cannot survive a backend restart, but founders can still inspect what
        # the original agent did instead of being offered a fake recovery shell.
        self.transcript_path = Path(workspace) / ".astra-terminal-transcript.log"
        try:
            self.transcript_path.write_bytes(b"")
        except OSError:
            pass
        self._alive = True
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def subscribe(self, cb: Callable[[bytes], None]) -> int:
        with _lock:
            token = self._next_subscriber
            self._next_subscriber += 1
            self._subscribers[token] = cb
            return token

    def unsubscribe(self, token: int) -> None:
        with _lock:
            self._subscribers.pop(token, None)

    def set_output(self, cb: Callable[[bytes], None] | None) -> None:
        """Compatibility shim for the legacy one-viewer takeover path."""
        with _lock:
            self._subscribers.pop(0, None)
            if cb:
                self._subscribers[0] = cb

    def transcript(self) -> bytes:
        with _lock:
            return bytes(self._transcript)

    @property
    def state(self) -> str:
        if self.alive:
            return "live"
        # A PTY master reports EIO when the slave closes, which can precede the
        # parent observing the child exit code. Treat that terminal-close state as
        # completed unless a non-zero status has actually been reaped.
        return "failed" if self.proc.returncode not in (None, 0) else "completed"

    def _read_loop(self) -> None:
        while self._alive:
            try:
                data = os.read(self.master_fd, 65536)
            except OSError:
                break
            if not data:
                break
            with _lock:
                self._transcript.extend(data)
                if len(self._transcript) > self._transcript_limit:
                    del self._transcript[:-self._transcript_limit]
                subscribers = list(self._subscribers.values())
            try:
                with self.transcript_path.open("ab") as transcript_file:
                    transcript_file.write(data)
            except OSError:
                pass
            for cb in subscribers:
                try:
                    cb(data)
                except Exception:
                    pass
        self._alive = False

    def write(self, data: bytes) -> bool:
        if not self._alive:
            return False
        try:
            os.write(self.master_fd, data)
            return True
        except OSError:
            self._alive = False
            return False

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
        return _terminals.get(app_session_id)


def durable_transcript(app_session_id: str) -> bytes:
    """Return the latest persisted transcript after a backend restart."""
    try:
        from backend.core.session_store import get_session_meta
        meta = get_session_meta(app_session_id) or {}
        # Company OS coding workspaces use the task ID as the directory name.
        root = Path(os.environ.get("ASTRA_WORKSPACE_ROOT", "/data/astra-workspaces"))
        candidate = root / app_session_id / "mvp" / ".astra-terminal-transcript.log"
        if candidate.is_file():
            return candidate.read_bytes()[-512 * 1024:]
    except OSError:
        pass
    return b""


def spawn_shared_process(app_session_id: str, cmd: list[str], *, cwd: str, env: dict[str, str], workspace: str) -> PtyTerm:
    """Start the original coding command in a PTY shared by progress parsing and viewers."""
    with _lock:
        existing = _terminals.get(app_session_id)
        if existing and existing.alive:
            raise RuntimeError(f"terminal already live for {app_session_id}")
        if existing:
            _terminals.pop(app_session_id, None)
    master_fd, slave_fd = pty.openpty()
    try:
        proc = subprocess.Popen(cmd, stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
                                cwd=cwd, env=env, start_new_session=True, close_fds=True)
    finally:
        os.close(slave_fd)
    term = PtyTerm(app_session_id, master_fd, proc, "", workspace, shared=True)
    with _lock:
        _terminals[app_session_id] = term
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
