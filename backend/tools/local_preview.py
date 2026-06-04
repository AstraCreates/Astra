"""Run a built MVP locally on the server as a fallback when Vercel deploy fails.

Starts the app (Next.js `npm run dev`, or a static/python server) on a free port
in a published range and returns a public URL: http://<host>:<port>. Bounded to a
small pool of ports; starting a new preview for a session replaces the old one.
"""
from __future__ import annotations

import json
import logging
import os
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


def _public_host() -> str:
    host = os.environ.get("ASTRA_PUBLIC_HOST", "")
    if host:
        return host
    url = getattr(settings, "nextauth_url", "") or os.environ.get("NEXTAUTH_URL", "")
    if url:
        h = urlparse(url).hostname
        if h:
            return h
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

    with _lock:
        old = _previews.pop(session_id, None)
        if old:
            try:
                old[1].terminate()
            except Exception:
                pass
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
        log = f"/tmp/preview_{session_id[:8]}_{port}.log"
        # Install deps (quietly) then start the dev server, detached. As the astra
        # user when running as root (npm/next dislike running as root in some setups).
        inner = f"cd {local!r} && npm install --no-audit --no-fund >{log} 2>&1; {run} >>{log} 2>&1"
        if os.getuid() == 0:
            subprocess.run(["chmod", "-R", "777", local], capture_output=True)
            cmd = ["sudo", "-u", "astra", "env", f"PORT={port}", "HOST=0.0.0.0", "HOME=/home/astra", "sh", "-c", inner]
        else:
            cmd = ["sh", "-c", inner]
        try:
            proc = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            logger.warning("Failed to start local preview: %s", e)
            return None
        _previews[session_id] = (port, proc)

    url = f"http://{_public_host()}:{port}"
    logger.info("Local preview for %s starting at %s (installing deps; ready in ~1-2 min)", session_id, url)
    return url
