"""Run a built MVP locally on the server as a fallback when Vercel deploy fails.

Starts the app (Next.js `npm run dev`, or a static/python server) on a free port
in a published range and returns a public URL: http://<host>:<port>. Bounded to a
small pool of ports; starting a new preview for a session replaces the old one.

Teardown (`stop_local_preview`) kills the whole process group AND anything still
bound to the port, then frees it — so a killed/deleted session leaves no live site
and no port leak. A sidecar registry (`_REGISTRY`) maps session→port on disk so
teardown still works after the backend process restarts (the in-memory `_previews`
dict is lost on restart, but the detached preview servers keep running).
"""
from __future__ import annotations

import json
import logging
import os
import signal
import socket
import subprocess
import threading
from pathlib import Path
from urllib.parse import urlparse

from backend.config import settings

logger = logging.getLogger(__name__)

# Ports must also be published by the backend container (see docker-compose.yml).
_PORT_RANGE = range(
    int(os.environ.get("ASTRA_PREVIEW_PORT_START", "4000")),
    int(os.environ.get("ASTRA_PREVIEW_PORT_END", "4010")),
)
_previews: dict[str, tuple[int, subprocess.Popen]] = {}
_lock = threading.Lock()

# Survives backend restarts so we can still tear down a detached preview server
# whose Popen handle we no longer hold.
_REGISTRY = Path(os.environ.get("ASTRA_PREVIEW_REGISTRY", "/tmp/astra_previews.json"))


def _registry_load() -> dict[str, int]:
    try:
        return {str(k): int(v) for k, v in json.loads(_REGISTRY.read_text()).items()}
    except Exception:
        return {}


def _registry_set(session_id: str, port: int) -> None:
    try:
        reg = _registry_load()
        reg[session_id] = port
        _REGISTRY.write_text(json.dumps(reg))
    except Exception as e:
        logger.debug("preview registry write failed: %s", e)


def _registry_pop(session_id: str) -> int | None:
    try:
        reg = _registry_load()
        port = reg.pop(session_id, None)
        _REGISTRY.write_text(json.dumps(reg))
        return port
    except Exception:
        return None


def _public_host() -> str:
    host = os.environ.get("ASTRA_PUBLIC_HOST", "")
    if host:
        return host
    # Do not infer or expose the underlying machine hostname/IP here. Keep the
    # preview URL generic unless the deploy environment explicitly sets a public
    # host.
    return "localhost"


def _port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


def _alloc_port() -> int | None:
    in_use = {p for p, _ in _previews.values()}
    for port in _PORT_RANGE:
        if port not in in_use and _port_is_free(port):
            return port
    return None


def _kill_proc_group(proc: subprocess.Popen) -> None:
    """SIGTERM then SIGKILL the process *group* (the dev server's children too)."""
    if proc is None:
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(os.getpgid(proc.pid), sig)
        except ProcessLookupError:
            return
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
            return


def _kill_port(port: int) -> None:
    """Kill whatever is still bound to ``port`` (covers sudo-detached children whose
    process group we don't own). Best-effort across fuser/lsof."""
    if not port:
        return
    try:
        subprocess.run(["fuser", "-k", f"{port}/tcp"], capture_output=True, timeout=10)
        return
    except Exception:
        pass
    try:
        out = subprocess.run(["lsof", "-t", f"-i:{port}"], capture_output=True, text=True, timeout=10)
        for pid in out.stdout.split():
            try:
                os.kill(int(pid), signal.SIGKILL)
            except Exception:
                pass
    except Exception:
        pass


def stop_local_preview(session_id: str) -> bool:
    """Stop the preview for a session: kill the server, free its port, drop the
    registry entry. Returns True if anything was torn down. Restart-safe — works
    even when the in-memory Popen handle is gone."""
    with _lock:
        entry = _previews.pop(session_id, None)
    port = None
    if entry:
        port, proc = entry
        _kill_proc_group(proc)
    reg_port = _registry_pop(session_id)
    if port is None:
        port = reg_port
    if port:
        _kill_port(port)
        logger.info("Stopped local preview for %s (port %s freed)", session_id, port)
        return True
    return bool(entry)


def start_local_preview(local: str, session_id: str) -> str | None:
    """Start the MVP locally and return its public URL, or None if not possible."""
    pkg = Path(local) / "package.json"
    deps: dict = {}
    if pkg.exists():
        try:
            deps = json.loads(pkg.read_text()).get("dependencies", {}) or {}
        except Exception:
            deps = {}
    is_node = pkg.exists()
    is_next = "next" in deps

    # Tear down any prior preview for this session (kills its server + frees port).
    stop_local_preview(session_id)

    with _lock:
        port = _alloc_port()
        if not port:
            logger.warning("No free preview port for session %s", session_id)
            return None

        if is_next:
            run = f"npm run dev -- -p {port} -H 0.0.0.0"
        elif is_node:
            # generic node app honoring $PORT
            run = "npm start"
        else:
            return None

        env = os.environ.copy()
        env["PORT"] = str(port)
        env["HOST"] = "0.0.0.0"
        npm_cache = os.environ.get("ASTRA_NPM_CACHE", "/data/npm-cache")
        log = f"/tmp/preview_{session_id[:8]}_{port}.log"
        # Install deps only if missing (the build pass already populated node_modules
        # in this same workspace — skip the redundant install for a faster preview),
        # then start the dev server detached. As the astra user when running as root.
        inner = (f"cd {local!r} && ([ -d node_modules ] || "
                 f"npm install --no-audit --no-fund --prefer-offline) >{log} 2>&1; {run} >>{log} 2>&1")
        if os.getuid() == 0:
            subprocess.run(["chmod", "-R", "777", local], capture_output=True)
            cmd = ["sudo", "-u", "astra", "env", f"PORT={port}", "HOST=0.0.0.0", "HOME=/home/astra",
                   f"npm_config_cache={npm_cache}", "npm_config_prefer_offline=true",
                   "sh", "-c", inner]
        else:
            cmd = ["sh", "-c", inner]
        try:
            # start_new_session=True → own process group so stop_local_preview can
            # SIGKILL the whole tree (sh → npm → next), not just the shell.
            proc = subprocess.Popen(
                cmd, env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as e:
            logger.warning("Failed to start local preview: %s", e)
            return None
        _previews[session_id] = (port, proc)
        _registry_set(session_id, port)

    url = f"http://{_public_host()}:{port}"
    logger.info("Local preview for %s starting at %s (installing deps; ready in ~1-2 min)", session_id, url)
    return url
