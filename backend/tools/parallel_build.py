"""Parallel coding agents for the technical specialist.

`spawn_parallel_coders` lets the technical agent build several independent modules
of a product AT THE SAME TIME instead of one sequential openclaude pass. Each module
is built by its own openclaude process in its own clone of the repo (so they can't
race on the git index / files), then their owned directories are merged back into the
main repo, package.json dependencies are unioned, and a single consolidated build
check + auto-fix runs before commit.

This is additive — the normal single-pass `run_mvp_loop` is unchanged.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def _phase(session_id: str, agent: str, text: str, **extra) -> None:
    try:
        from backend.core.events import publish_sync
        publish_sync(session_id, {"type": "agent_build", "agent": agent, "kind": "phase", "text": text, **extra})
    except Exception:
        pass


def _union_package_json(main_local: str, worker_dirs: list[str]) -> None:
    """Merge dependencies/devDependencies from every worker's package.json into main."""
    main_pkg = Path(main_local) / "frontend" / "package.json"
    if not main_pkg.exists():
        main_pkg = Path(main_local) / "package.json"
    if not main_pkg.exists():
        return
    try:
        base = json.loads(main_pkg.read_text())
    except Exception:
        return
    for wd in worker_dirs:
        wpkg = Path(wd) / main_pkg.relative_to(main_local)
        if not wpkg.exists():
            continue
        try:
            w = json.loads(wpkg.read_text())
        except Exception:
            continue
        for key in ("dependencies", "devDependencies"):
            base.setdefault(key, {})
            for dep, ver in (w.get(key) or {}).items():
                base[key].setdefault(dep, ver)  # keep main's pin if it already has one
    main_pkg.write_text(json.dumps(base, indent=2))


def _merge_owned(main_local: str, worker_dir: str, owns: str) -> int:
    """Copy a module's owned directory from its worker clone into the main repo.
    Returns the number of files merged."""
    src = Path(worker_dir) / owns
    if not src.exists():
        return 0
    dst = Path(main_local) / owns
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    return sum(1 for _ in dst.rglob("*") if _.is_file())


async def spawn_parallel_coders(
    repo_url: str,
    modules: list[dict],
    session_id: str = "default",
    context: str = "",
    founder_id: str = "",
    agent: str = "technical",
    worker_model: str = "",
    merge_model: str = "",
) -> dict:
    """Build several product modules concurrently, each with its own coding agent.

    repo_url: the existing repo (the web agent's landing repo) to build on top of.
    modules: list of {name, goal, owns} where:
        - name:  short module name (e.g. "dashboard")
        - goal:  what to build for it (real, specific)
        - owns:  the directory this module owns and may write (e.g. "frontend/app/dashboard").
                 Coders only merge files under their owns path, so modules must own
                 NON-OVERLAPPING directories.
    Returns {ok, modules_built, build_passes, repo_url, deploy_url?}.
    """
    from backend.config import settings
    from backend.tools.git_tools import (
        _get_workspace, _run_claude, _pull, _stage_all, _npm_build_passes,
        _build_doctor, _commit_and_push, _coder_model_for_agent,
    )
    light_worker_model = worker_model or getattr(settings, "technical_subagent_model", "") or getattr(settings, "or_light_model", "")
    medium_merge_model = merge_model or _coder_model_for_agent(agent)

    mods = [m for m in (modules or []) if isinstance(m, dict) and m.get("goal") and m.get("owns")]
    if len(mods) < 2:
        return {"ok": False, "error": "spawn_parallel_coders needs >=2 modules with {name, goal, owns}; use run_mvp_loop for a single build"}

    main_local, is_github = _get_workspace(repo_url, session_id)
    if is_github:
        _pull(main_local)
    _phase(
        session_id,
        agent,
        f"Spawning {len(mods)} coding agents in parallel: {', '.join(m['name'] for m in mods)}",
        worker_model=light_worker_model,
        merge_model=medium_merge_model,
    )

    # Give each coder its own clone of the repo so concurrent openclaude runs can't
    # race on the same git index / working tree.
    is_git_repo = (Path(main_local) / ".git").exists()
    worker_dirs: list[str] = []
    for i, m in enumerate(mods):
        wd = f"{main_local}_coder_{i}"
        shutil.rmtree(wd, ignore_errors=True)
        try:
            if is_git_repo:
                subprocess.run(["git", "clone", "--quiet", main_local, wd], check=True, timeout=180,
                               capture_output=True, text=True)
            else:
                # Local-only workspace (no git) — copy the tree so each coder still gets
                # its own isolated working dir. Skip node_modules/.git to keep it fast.
                shutil.copytree(main_local, wd, ignore=shutil.ignore_patterns("node_modules", ".git", ".next"))
            worker_dirs.append(wd)
        except Exception as e:
            logger.warning("parallel coder %s clone failed: %s", m.get("name"), e)
            worker_dirs.append("")

    def _build_one(idx: int, m: dict) -> dict:
        wd = worker_dirs[idx]
        if not wd:
            return {"name": m["name"], "ok": False, "error": "clone failed"}
        prompt = (
            f"You are ONE of several coding agents building a product in parallel. Build ONLY the "
            f"'{m['name']}' module:\n{m['goal']}\n\n"
            + (f"Shared product context:\n{context}\n\n" if context else "")
            + f"STRICT OWNERSHIP: write your module's code ONLY under the directory `{m['owns']}` "
            f"(create it). You MAY add npm dependencies to package.json. Do NOT edit files outside "
            f"`{m['owns']}` except package.json — other agents own those and your changes there will be "
            f"discarded. No stubs/TODOs — fully implement the module. Verify with `npx tsc --noEmit`."
        )
        _phase(session_id, agent, f"[{m['name']}] coding agent started → {m['owns']}")
        _run_claude(
            wd,
            prompt,
            timeout=1800,
            founder_id=founder_id,
            app_session_id=session_id,
            agent=agent,
            model=light_worker_model,
        )
        return {"name": m["name"], "ok": True, "owns": m["owns"]}

    # Run all coders concurrently (each openclaude is a blocking subprocess → thread it).
    results = await asyncio.gather(
        *[asyncio.to_thread(_build_one, i, m) for i, m in enumerate(mods)],
        return_exceptions=True,
    )
    built = []
    for r in results:
        if isinstance(r, dict) and r.get("ok"):
            built.append(r)
        else:
            logger.warning("parallel coder failed: %s", r)

    merged_files = 0
    passed = None
    deploy_url = ""
    try:
        # Merge each module's owned directory + union dependencies into the main repo.
        _phase(session_id, agent, f"Merging {len(built)} modules into the repo")
        for r in built:
            idx = next((i for i, m in enumerate(mods) if m["name"] == r["name"]), None)
            if idx is not None and worker_dirs[idx]:
                merged_files += _merge_owned(main_local, worker_dirs[idx], r["owns"])
        _union_package_json(main_local, [w for w in worker_dirs if w])

        # One consolidated build check + auto-fix on the merged tree.
        _phase(session_id, agent, "Consolidated build check on merged modules")
        _build_doctor(main_local)
        passed, out = _npm_build_passes(main_local)
        if passed is False:
            _phase(session_id, agent, "Merged build failed — running recovery pass")
            recovery = (
                "The merged product fails to build. Fix ALL compile/type/import errors across the "
                "modules so `npm run build` passes. Build output:\n" + (out or "")[:4000]
            )
            _run_claude(
                main_local,
                recovery,
                timeout=1200,
                founder_id=founder_id,
                app_session_id=session_id,
                agent=agent,
                model=medium_merge_model,
            )
            _build_doctor(main_local)
            passed, out = _npm_build_passes(main_local)

        _stage_all(main_local)
        _commit_and_push(main_local, f"feat: build {len(built)} modules in parallel ({', '.join(b['name'] for b in built)})")

        try:
            from backend.tools.local_preview import start_local_preview
            from backend.tools.git_tools import _root_session_id
            root_sid = _root_session_id(session_id)
            deploy_url = start_local_preview(main_local, root_sid, company_name=Path(main_local).name) or ""
            if deploy_url:
                from backend.core.events import publish_sync
                publish_sync(session_id, {"type": "agent_build", "agent": agent, "kind": "deploy", "url": deploy_url, "local": True})
        except Exception as e:
            logger.warning("parallel build deploy failed: %s", e)
    except Exception as e:
        # Merge/build/deploy can fail when a coder's worker tree or the external
        # claude-code CLI worktree vanishes mid-run. Don't discard the modules
        # that were already built — log and fall through to a partial result.
        logger.warning("parallel build merge/build phase failed: %s", e)
        _phase(session_id, agent, f"Merge/build phase hit an error ({type(e).__name__}); returning {len(built)} built modules")
    finally:
        # Always clean up worker clones, even if merge/build raised.
        for wd in worker_dirs:
            if wd:
                shutil.rmtree(wd, ignore_errors=True)

    _phase(session_id, agent, f"Parallel build done — {len(built)}/{len(mods)} modules, {merged_files} files, build {'OK' if passed else 'has errors'}")
    return {
        "ok": True,
        "modules_built": [b["name"] for b in built],
        "modules_failed": [m["name"] for m in mods if m["name"] not in [b["name"] for b in built]],
        "files_merged": merged_files,
        "build_passes": bool(passed),
        "repo_url": repo_url,
        "deploy_url": deploy_url,
    }
