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

import hashlib
import json
import logging
import os
import re
import signal
import socket
import subprocess
import threading
import time
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
# Slug registry: maps company slug → port for subdomain routing
_SLUG_REGISTRY = Path(os.environ.get("ASTRA_PREVIEW_SLUG_REGISTRY", "/tmp/astra_preview_slugs.json"))
# In-memory slug→port map (populated on start + recovered from disk on miss)
_slug_to_port: dict[str, int] = {}

# Concurrency cap for node/Next builds (CPU+RAM heavy)
_NODE_BUILD_SEM = threading.Semaphore(int(os.environ.get("ASTRA_PREVIEW_BUILD_CONCURRENCY", "2")))
_BUILD_TIMEOUT_S = int(os.environ.get("ASTRA_PREVIEW_BUILD_TIMEOUT", "300"))

# Idle eviction: kill previews inactive longer than TTL
_PREVIEW_TTL = int(os.environ.get("ASTRA_PREVIEW_TTL", "1800"))  # 30 min default
_last_access: dict[str, float] = {}


def _eviction_loop() -> None:
    while True:
        time.sleep(60)
        now = time.time()
        with _lock:
            stale = [sid for sid, ts in list(_last_access.items()) if now - ts > _PREVIEW_TTL]
        for sid in stale:
            logger.info("Evicting idle preview %s (idle >%ss)", sid, _PREVIEW_TTL)
            stop_local_preview(sid)


threading.Thread(target=_eviction_loop, daemon=True, name="preview-eviction").start()


def _slug_registry_load() -> dict[str, int]:
    try:
        return {str(k): int(v) for k, v in json.loads(_SLUG_REGISTRY.read_text()).items()}
    except Exception:
        return {}


def _registry_save(reg: dict[str, int]) -> None:
    try:
        _REGISTRY.write_text(json.dumps(reg))
    except Exception as e:
        logger.debug("preview registry write failed: %s", e)


def _slug_registry_save(reg: dict[str, int]) -> None:
    try:
        _SLUG_REGISTRY.write_text(json.dumps(reg))
    except Exception as e:
        logger.debug("slug registry write failed: %s", e)


def _prune_dead_registry_entries() -> tuple[dict[str, int], dict[str, int]]:
    reg = _registry_load()
    slug_reg = _slug_registry_load()
    live_ports = {port for port in set(reg.values()) | set(slug_reg.values()) if not _port_is_free(port)}
    clean_reg = {sid: port for sid, port in reg.items() if port in live_ports}
    clean_slug_reg = {slug: port for slug, port in slug_reg.items() if port in live_ports}
    if clean_reg != reg:
        _registry_save(clean_reg)
    if clean_slug_reg != slug_reg:
        _slug_registry_save(clean_slug_reg)
    _slug_to_port.clear()
    _slug_to_port.update(clean_slug_reg)
    return clean_reg, clean_slug_reg


def _clear_port_conflicts(port: int, keep_session_id: str = "", keep_slug: str = "") -> None:
    reg, slug_reg = _prune_dead_registry_entries()
    clean_reg = {
        sid: mapped_port
        for sid, mapped_port in reg.items()
        if mapped_port != port or sid == keep_session_id
    }
    clean_slug_reg = {
        slug: mapped_port
        for slug, mapped_port in slug_reg.items()
        if mapped_port != port or slug == keep_slug
    }
    if keep_session_id:
        clean_reg[keep_session_id] = port
    if keep_slug:
        clean_slug_reg[keep_slug] = port
    _registry_save(clean_reg)
    _slug_registry_save(clean_slug_reg)
    _slug_to_port.clear()
    _slug_to_port.update(clean_slug_reg)


def _slug_registry_set(slug: str, port: int) -> None:
    with _lock:
        _clear_port_conflicts(port, keep_slug=slug)


def get_port_for_slug(slug: str) -> int | None:
    """Return the preview port for a company slug, or None if not running."""
    if slug in _slug_to_port:
        port = _slug_to_port[slug]
        if not _port_is_free(port):
            return port
        _slug_to_port.pop(slug, None)
    # Fall back to disk registry (survives backend restart)
    _, reg = _prune_dead_registry_entries()
    port = reg.get(slug)
    if port:
        _slug_to_port[slug] = port
    return port


def _make_slug(company_name: str, fallback: str, session_id: str = "") -> str:
    """Sanitize company name + session suffix into a unique URL-safe subdomain slug."""
    raw = (company_name or fallback).lower()
    raw = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    raw = re.sub(r"-{2,}", "-", raw)
    base = raw[:28] or "preview"
    # 4-char session hash ensures slugs are unique per session (no cross-tenant collision)
    suffix = hashlib.sha256(session_id.encode()).hexdigest()[:4] if session_id else "0000"
    return f"{base}-{suffix}"


def _registry_load() -> dict[str, int]:
    try:
        return {str(k): int(v) for k, v in json.loads(_REGISTRY.read_text()).items()}
    except Exception:
        return {}


def _registry_set(session_id: str, port: int) -> None:
    _clear_port_conflicts(port, keep_session_id=session_id)


def _registry_pop(session_id: str) -> int | None:
    try:
        reg, _ = _prune_dead_registry_entries()
        port = reg.pop(session_id, None)
        _registry_save(reg)
        return port
    except Exception:
        return None


def _public_host() -> str:
    return os.environ.get("ASTRA_PUBLIC_HOST", "localhost")


def _preview_url(slug: str, port: int) -> str:
    """Return the public URL for a preview. Subdomain if ASTRA_PUBLIC_HOST is set, else port-based."""
    host = _public_host()
    if host and host != "localhost":
        return f"http://{slug}.{host}"
    return f"http://{host}:{port}"


def _port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


def _alloc_port() -> int | None:
    reg, _ = _prune_dead_registry_entries()
    in_use = {p for p, _ in _previews.values()} | set(reg.values())
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
        _last_access.pop(session_id, None)
    port = None
    if entry:
        port, proc = entry
        _kill_proc_group(proc)
    reg_port = _registry_pop(session_id)
    if port is None:
        port = reg_port
    if port:
        _kill_port(port)
        # Remove slug entries that pointed to this port
        dead_slugs = [s for s, p in list(_slug_to_port.items()) if p == port]
        for s in dead_slugs:
            _slug_to_port.pop(s, None)
        if dead_slugs:
            with _lock:
                reg = _slug_registry_load()
                for s in dead_slugs:
                    reg.pop(s, None)
                _slug_registry_save(reg)
        logger.info("Stopped local preview for %s (port %s freed)", session_id, port)
        return True
    return bool(entry)


def start_local_preview(local: str, session_id: str, company_name: str = "") -> str | None:
    """Start the MVP locally and return its public URL, or None if not possible.

    Next.js: runs `next build` (blocking, capped by semaphore) then `next start`
    (near-zero persistent RAM vs ~1 GB for `npm run dev`).
    """
    pkg = Path(local) / "package.json"
    deps: dict = {}
    if pkg.exists():
        try:
            deps = json.loads(pkg.read_text()).get("dependencies", {}) or {}
        except Exception:
            deps = {}
    is_node = pkg.exists()
    is_next = is_node and "next" in deps

    if not is_node:
        return None

    stop_local_preview(session_id)

    with _lock:
        port = _alloc_port()
        if not port:
            logger.warning("No free preview port for session %s", session_id)
            return None
        # Reserve the port immediately so concurrent allocs don't pick the same one.
        _previews[session_id] = (port, None)  # type: ignore[assignment]

    env = os.environ.copy()
    env["PORT"] = str(port)
    env["HOST"] = "0.0.0.0"
    env["NODE_OPTIONS"] = "--max-old-space-size=2048"
    npm_cache = os.environ.get("ASTRA_NPM_CACHE", "/data/npm-cache")
    log = f"/tmp/preview_{session_id[:8]}_{port}.log"

    def _wrap(inner_sh: str) -> list[str]:
        if os.getuid() == 0:
            subprocess.run(["chmod", "-R", "777", local], capture_output=True)
            return [
                "sudo", "-u", "astra", "env",
                f"PORT={port}", "HOST=0.0.0.0", "HOME=/home/astra",
                "NODE_OPTIONS=--max-old-space-size=2048",
                f"npm_config_cache={npm_cache}", "npm_config_prefer_offline=true",
                "sh", "-c", inner_sh,
            ]
        return ["sh", "-c", inner_sh]

    if is_next:
        build_sh = (
            f"cd {local!r} && "
            f"([ -d node_modules ] || npm install --no-audit --no-fund --prefer-offline >>{log} 2>&1) && "
            f"npx next build >>{log} 2>&1"
        )
        logger.info("Building Next.js preview for %s (capped at %d concurrent)", session_id, _NODE_BUILD_SEM._value)
        acquired = _NODE_BUILD_SEM.acquire(timeout=_BUILD_TIMEOUT_S)
        if not acquired:
            logger.warning("Build semaphore timeout for %s", session_id)
            with _lock:
                _previews.pop(session_id, None)
            return None
        try:
            r = subprocess.run(_wrap(build_sh), timeout=_BUILD_TIMEOUT_S, capture_output=True)
            if r.returncode != 0:
                logger.warning("next build failed for %s (exit %s)", session_id, r.returncode)
                with _lock:
                    _previews.pop(session_id, None)
                return None
        except subprocess.TimeoutExpired:
            logger.warning("next build timed out for %s", session_id)
            with _lock:
                _previews.pop(session_id, None)
            return None
        except Exception as e:
            logger.warning("next build error for %s: %s", session_id, e)
            with _lock:
                _previews.pop(session_id, None)
            return None
        finally:
            _NODE_BUILD_SEM.release()

        start_sh = f"cd {local!r} && npx next start -p {port} -H 0.0.0.0 >>{log} 2>&1"
    else:
        start_sh = (
            f"cd {local!r} && "
            f"([ -d node_modules ] || npm install --no-audit --no-fund --prefer-offline >>{log} 2>&1); "
            f"npm start >>{log} 2>&1"
        )

    try:
        proc = subprocess.Popen(
            _wrap(start_sh), env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as e:
        logger.warning("Failed to start local preview server: %s", e)
        with _lock:
            _previews.pop(session_id, None)
        return None

    slug = _make_slug(company_name, Path(local).name, session_id)
    with _lock:
        _previews[session_id] = (port, proc)
        _last_access[session_id] = time.time()
        _slug_to_port.update({slug: port})
    _registry_set(session_id, port)
    _slug_registry_set(slug, port)

    url = _preview_url(slug, port)
    logger.info("Local preview for %s at %s (slug=%s; static)", session_id, url, slug)
    return url
