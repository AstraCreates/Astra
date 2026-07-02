"""Executes automation canvas graphs (nodes + edges) natively in Astra.

Node types:
  agent      — invokes one Astra specialist via Agent.run(ctx), same primitive
               `rerun_agent` uses standalone (backend/api/routes.py). Full
               tool access, normal credit tracking (built into Agent._call_llm).
  prompt     — a direct LLM completion, implemented as an ephemeral no-tools
               Agent so it reuses the exact same credit-tracking path instead
               of hand-rolling token counting for a separate code path.
  action     — HTTP request (SSRF-guarded via backend.tools.url_safety) or a
               named Windmill flow (backend.tools.automation_runtime), for the
               classes of automation Windmill is actually good at.
  delay      — pauses N seconds before continuing.
  condition  — gates the branch: if the upstream output doesn't contain the
               configured text, this node and everything downstream of it are
               marked "skipped" instead of running.

Execution is a topological walk — graphs are DAGs, condition nodes give one
level of branch/skip but there's no loop support. Each node's textual output
is available to downstream nodes via {{node_id.output}} substitution in
their config.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re

from backend.core import automation_store

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_-]+)\.output\s*\}\}")


def _render(template: str, outputs: dict[str, str]) -> str:
    def _sub(m: re.Match) -> str:
        return outputs.get(m.group(1), "")
    return _TOKEN_RE.sub(_sub, template or "")


def _render_any(value, outputs: dict[str, str]):
    if isinstance(value, str):
        return _render(value, outputs)
    if isinstance(value, dict):
        return {k: _render_any(v, outputs) for k, v in value.items()}
    if isinstance(value, list):
        return [_render_any(v, outputs) for v in value]
    return value


def _topo_order(nodes: list[dict], edges: list[dict]) -> list[str]:
    node_ids = [n["id"] for n in nodes]
    incoming: dict[str, set[str]] = {nid: set() for nid in node_ids}
    for e in edges:
        if e.get("target") in incoming and e.get("source") in incoming:
            incoming[e["target"]].add(e["source"])

    order: list[str] = []
    remaining = set(node_ids)
    while remaining:
        ready = sorted(nid for nid in remaining if not (incoming[nid] & remaining))
        if not ready:
            # Cycle — bail out with whatever's left in a stable order rather than hang.
            order.extend(sorted(remaining))
            break
        order.extend(ready)
        remaining -= set(ready)
    return order


def _upstream_ids(node_id: str, edges: list[dict]) -> list[str]:
    return [e["source"] for e in edges if e.get("target") == node_id]


def _extract_text(result: dict) -> str:
    if not isinstance(result, dict):
        return str(result)
    if result.get("error"):
        return f"ERROR: {result['error']}"
    summary = result.get("summary")
    if isinstance(summary, str) and summary:
        return summary
    return json.dumps(result, default=str)[:4000]


async def _execute_agent_node(node: dict, instruction: str, founder_id: str, run_id: str) -> dict:
    from backend.core.agent import AgentContext
    from backend.core.factory import get_orchestrator

    agent_name = (node.get("config") or {}).get("agent_name", "")
    orch = get_orchestrator()
    agent = orch.specialists.get(agent_name)
    if agent is None:
        return {"error": f"Unknown agent '{agent_name}'. Available: {sorted(orch.specialists.keys())}"}
    ctx = AgentContext(goal=instruction, founder_id=founder_id, session_id=run_id)
    return await agent.run(ctx)


def _respond_tool(answer: str = "") -> dict:
    """Provide your final answer text. Call this once, then call done."""
    return {"answer": answer}


async def _execute_prompt_node(node: dict, instruction: str, founder_id: str, run_id: str) -> dict:
    from backend.core.agent import Agent, AgentContext

    cfg = node.get("config") or {}
    # Agent._run_loop requires at least 1 tool call before it accepts "done"
    # (defaults to 1 for any agent name not in _MIN_CALLS_BY_AGENT) — a
    # genuinely tools-less agent gets stuck in an infinite loop being told
    # to call a tool that doesn't exist. Give it exactly one trivial tool
    # so a plain "answer this prompt" call can actually finish.
    agent = Agent(
        name=f"prompt_{node['id']}",
        role=cfg.get(
            "system_prompt",
            "You are a helpful assistant. Answer directly and concisely. "
            'First call the "respond" tool with your answer, then call done '
            'with {"action":"done","output":{"summary":"<your answer>"}}.',
        ),
        tools={"respond": _respond_tool},
    )
    ctx = AgentContext(goal=instruction, founder_id=founder_id, session_id=run_id)
    return await agent.run(ctx)


async def _execute_action_node(node: dict, rendered_config: dict, founder_id: str) -> dict:
    cfg = rendered_config
    windmill_path = cfg.get("windmill_flow_path")
    if windmill_path:
        from backend.tools.automation_runtime import automation_trigger_flow
        return await automation_trigger_flow(windmill_path, cfg.get("payload") or {}, founder_id=founder_id)

    from backend.tools.url_safety import safe_get, validate_url

    url = cfg.get("url", "")
    method = (cfg.get("method") or "GET").upper()
    headers = cfg.get("headers") or {}
    body = cfg.get("body")
    try:
        if method == "GET":
            resp = await asyncio.to_thread(safe_get, url, headers=headers, timeout=30.0)
        else:
            # safe_get is GET-only (wraps requests.get specifically) and revalidates
            # every redirect hop; non-GET actions are rarer and don't typically
            # redirect, so this checks the initial URL only, no redirect-following.
            import requests
            validate_url(url)
            resp = await asyncio.to_thread(
                requests.request, method, url,
                headers=headers, json=body if isinstance(body, dict) else None,
                timeout=30.0, allow_redirects=False,
            )
        content_type = (resp.headers.get("content-type") or "").lower()
        data = resp.json() if "application/json" in content_type else resp.text
        return {"summary": json.dumps(data, default=str)[:2000] if isinstance(data, (dict, list)) else str(data)[:2000], "status_code": resp.status_code}
    except Exception as e:
        return {"error": str(e)}


async def _execute_delay_node(node: dict) -> dict:
    cfg = node.get("config") or {}
    try:
        seconds = max(0.0, min(float(cfg.get("seconds", 0)), 3600.0))
    except (TypeError, ValueError):
        seconds = 0.0
    await asyncio.sleep(seconds)
    return {"summary": f"Waited {seconds:g}s"}


def _execute_condition_node(node: dict, upstream_text: str) -> dict:
    cfg = node.get("config") or {}
    needle = str(cfg.get("contains") or "").strip().lower()
    passed = (not needle) or (needle in upstream_text.lower())
    return {"summary": upstream_text, "passed": passed}


async def run_automation_flow(founder_id: str, flow_id: str, run_id: str) -> dict:
    """Executes a saved flow end-to-end, persisting + streaming per-node status.
    `run_id` must already exist (see automation_store.create_run) — the caller
    creates it up front so it can return the id to the client immediately,
    before this (usually backgrounded) execution starts."""
    from backend.core.events import publish_sync

    flow = automation_store.get_flow(founder_id, flow_id)
    if not flow:
        raise ValueError(f"Flow '{flow_id}' not found")

    nodes = {n["id"]: n for n in flow.get("nodes", [])}
    edges = flow.get("edges", [])
    outputs: dict[str, str] = {}
    skipped: set[str] = set()

    publish_sync(run_id, {"type": "automation_run_started", "run_id": run_id, "flow_id": flow_id})

    try:
        order = _topo_order(list(nodes.values()), edges)
        for node_id in order:
            node = nodes.get(node_id)
            if node is None:
                continue

            upstream = _upstream_ids(node_id, edges)
            if upstream and skipped.issuperset(upstream):
                skipped.add(node_id)
                automation_store.set_node_result(founder_id, run_id, node_id, {"status": "skipped", "output": {}})
                publish_sync(run_id, {"type": "node_status", "node_id": node_id, "status": "skipped"})
                continue

            publish_sync(run_id, {"type": "node_status", "node_id": node_id, "status": "running"})

            upstream_text = "\n\n".join(f"[{uid}]: {outputs.get(uid, '')}" for uid in upstream if uid not in skipped)
            cfg = node.get("config") or {}
            merged_outputs = dict(outputs)
            node_type = node.get("type")

            try:
                if node_type == "agent":
                    instruction = _render(cfg.get("instruction", ""), merged_outputs) or upstream_text
                    result = await _execute_agent_node(node, instruction, founder_id, run_id)
                elif node_type == "prompt":
                    instruction = _render(cfg.get("instruction", ""), merged_outputs) or upstream_text
                    result = await _execute_prompt_node(node, instruction, founder_id, run_id)
                elif node_type == "action":
                    rendered_cfg = _render_any(cfg, merged_outputs)
                    result = await _execute_action_node(node, rendered_cfg, founder_id)
                elif node_type == "delay":
                    result = await _execute_delay_node(node)
                elif node_type == "condition":
                    result = _execute_condition_node(node, upstream_text)
                elif node_type == "trigger":
                    result = {"summary": "trigger", "status": "ok"}
                else:
                    result = {"error": f"Unknown node type '{node_type}'"}
            except Exception as e:
                logger.exception("automation node %s failed", node_id)
                result = {"error": str(e)}

            if node_type == "condition" and result.get("passed") is False:
                skipped.add(node_id)
                outputs[node_id] = result.get("summary", "")
                automation_store.set_node_result(founder_id, run_id, node_id, {"status": "skipped", "output": result})
                publish_sync(run_id, {"type": "node_status", "node_id": node_id, "status": "skipped", "output": "condition not met"})
                continue

            text = _extract_text(result)
            outputs[node_id] = text
            automation_store.set_node_result(founder_id, run_id, node_id, {"status": "error" if result.get("error") else "done", "output": result})
            publish_sync(run_id, {"type": "node_status", "node_id": node_id, "status": "error" if result.get("error") else "done", "output": text})

            if result.get("error"):
                automation_store.update_run(founder_id, run_id, status="error", error=result["error"], finished_at=automation_store.now())
                publish_sync(run_id, {"type": "automation_run_error", "run_id": run_id, "node_id": node_id, "error": result["error"]})
                return automation_store.get_run(founder_id, run_id)

        automation_store.update_run(founder_id, run_id, status="done", finished_at=automation_store.now())
        publish_sync(run_id, {"type": "automation_run_done", "run_id": run_id})
    except Exception as e:
        logger.exception("automation flow %s failed", flow_id)
        automation_store.update_run(founder_id, run_id, status="error", error=str(e), finished_at=automation_store.now())
        publish_sync(run_id, {"type": "automation_run_error", "run_id": run_id, "error": str(e)})

    return automation_store.get_run(founder_id, run_id)
