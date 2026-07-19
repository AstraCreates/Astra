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
  slack      — posts to a Slack incoming webhook URL. No OAuth needed.
  email      — sends via the founder's own connected SendGrid key (never a
               shared credential) — errors clearly if it isn't connected yet.
  gmail      — sends through the founder's connected Gmail account.
  slack_bot  — posts to Slack using the founder's connected bot token.
  github_issue — creates a GitHub issue in a connected repo.
  github_pr  — opens a GitHub pull request in a connected repo.
  linear_issue — creates a Linear issue in the connected workspace.
  notion_page — creates a Notion page in the connected workspace.
  stripe_payment_link — creates a Stripe product + payment link.
  switch     — routes to one of several named branches by matching a value
               against a list of cases (n8n-style Switch/Router); non-matching
               branches are marked "skipped", same as condition does for its
               single branch.
  code       — evaluates one restricted Python expression against `input`
               (upstream output, JSON-parsed if possible). Not a general
               script sandbox: single expression only (ast.parse mode="eval",
               so no statements/imports/loops are even parseable), builtins
               reduced to a small safe whitelist, and any dunder attribute
               access (the standard eval-sandbox escape route via
               __class__/__subclasses__/etc.) is rejected before compiling.

Execution is a topological walk — graphs are DAGs, condition/switch nodes
give branch/skip but there's no loop support. Each node's textual output
is available to downstream nodes via {{node_id.output}} substitution in
their config. Agent/prompt nodes can also request structured JSON output via
`output_schema` in their config — the executor appends a "respond with only
this JSON shape" instruction and validates the result parses as JSON.
"""
from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import logging
import re
from typing import Any, Awaitable, Callable

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


def _edge_key(e: dict) -> tuple[str, str, str | None]:
    return (e.get("source"), e.get("target"), e.get("source_handle"))


def _node_is_dead(node_id: str, edges: list[dict], skipped: set[str], dead_edges: set[tuple[str, str, str | None]]) -> bool:
    """A node is dead (should be skipped) once every incoming edge is either
    from an already-skipped node, or was itself the untaken branch of a
    switch/condition upstream — not just "any upstream skipped", since a
    switch node's other live branches must still run."""
    incoming = [e for e in edges if e.get("target") == node_id]
    if not incoming:
        return False
    return all(e.get("source") in skipped or _edge_key(e) in dead_edges for e in incoming)


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


def _execute_condition_equals_node(node: dict, upstream_text: str) -> dict:
    cfg = node.get("config") or {}
    expected = str(cfg.get("equals") or "")
    passed = upstream_text.strip() == expected.strip()
    return {"summary": upstream_text, "passed": passed}


def _execute_switch_node(node: dict, upstream_text: str) -> dict:
    cfg = node.get("config") or {}
    value = str(cfg.get("value") or upstream_text).strip().lower()
    cases = [str(c) for c in (cfg.get("cases") or [])]
    matched_handle = "default"
    for i, c in enumerate(cases):
        if c.strip() and c.strip().lower() == value:
            matched_handle = f"case_{i}"
            break
    return {"summary": upstream_text, "matched_handle": matched_handle}


_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _coerce_json_summary(result: dict) -> dict:
    """Post-processes an agent/prompt result when the node requested
    structured output (config.output_schema) — validates the model actually
    returned parseable JSON rather than trusting it blindly."""
    if not isinstance(result, dict) or result.get("error"):
        return result
    text = str(result.get("summary", "")).strip()
    fenced = _JSON_FENCE_RE.match(text)
    if fenced:
        text = fenced.group(1)
    try:
        parsed = json.loads(text)
    except Exception:
        result["json_error"] = "Model output was not valid JSON"
        return result
    result["summary"] = json.dumps(parsed)
    return result


class _UnsafeExpression(Exception):
    pass


_CODE_SAFE_CALLS = {
    "len", "str", "int", "float", "bool", "sorted", "sum", "min", "max",
    "round", "abs", "list", "dict", "set", "tuple", "json_dumps", "json_loads",
}


def _check_code_ast(tree: ast.AST) -> None:
    for child in ast.walk(tree):
        if isinstance(child, (ast.Import, ast.ImportFrom)):
            raise _UnsafeExpression("imports not allowed")
        if isinstance(child, ast.Attribute) and child.attr.startswith("__"):
            raise _UnsafeExpression("dunder attribute access not allowed")
        if isinstance(child, ast.Name) and child.id.startswith("__"):
            raise _UnsafeExpression("dunder names not allowed")
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id not in _CODE_SAFE_CALLS:
            raise _UnsafeExpression(f"call to '{child.func.id}' not allowed")


def _execute_code_node(node: dict, upstream_text: str) -> dict:
    """Evaluates one restricted Python expression — not a general script
    sandbox. See module docstring for exactly what's blocked and why."""
    cfg = node.get("config") or {}
    expr = str(cfg.get("expression") or "").strip()
    if not expr:
        return {"error": "No expression configured"}
    try:
        parsed_input: object = json.loads(upstream_text)
    except Exception:
        parsed_input = upstream_text
    try:
        tree = ast.parse(expr, mode="eval")
        _check_code_ast(tree)
        code = compile(tree, "<code_node>", "eval")
        safe_locals = {
            "input": parsed_input,
            "len": len, "str": str, "int": int, "float": float, "bool": bool,
            "sorted": sorted, "sum": sum, "min": min, "max": max, "round": round,
            "abs": abs, "list": list, "dict": dict, "set": set, "tuple": tuple,
            "json_dumps": json.dumps, "json_loads": json.loads,
        }
        # eval() is normally unsafe on arbitrary input, but this call is deliberately
        # hardened, not raw eval(user_string): (1) ast.parse(mode="eval") only accepts
        # a single expression — no statements, imports, loops, or assignments are even
        # parseable; (2) _check_code_ast rejects Import/ImportFrom, any dunder name or
        # attribute (blocks the classic __class__/__bases__/__subclasses__ sandbox
        # escape), and any call not in the small whitelist above; (3) __builtins__ is
        # explicitly emptied so nothing outside safe_locals is reachable at all.
        value = eval(code, {"__builtins__": {}}, safe_locals)
    except _UnsafeExpression as e:
        return {"error": f"Blocked: {e}"}
    except Exception as e:
        return {"error": f"Expression error: {e}"}
    return {"summary": value if isinstance(value, str) else json.dumps(value, default=str)}


def _execute_merge_node(node: dict, upstream_text: str) -> dict:
    cfg = node.get("config") or {}
    sep = cfg.get("separator", "\n\n")
    return {"summary": upstream_text or "", "separator": sep}


def _execute_json_extract_node(node: dict, upstream_text: str) -> dict:
    cfg = node.get("config") or {}
    path = str(cfg.get("path") or "").strip()
    try:
        data = json.loads(upstream_text)
    except Exception:
        return {"error": f"Upstream output isn't valid JSON: {upstream_text[:200]}"}
    current = data
    for part in [p for p in path.split(".") if p]:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            idx = int(part)
            current = current[idx] if 0 <= idx < len(current) else None
        else:
            current = None
        if current is None:
            break
    return {"summary": current if isinstance(current, str) else json.dumps(current, default=str)}


def _execute_text_transform_node(node: dict, upstream_text: str) -> dict:
    cfg = node.get("config") or {}
    op = str(cfg.get("operation") or "trim").lower()
    if op == "uppercase":
        out = upstream_text.upper()
    elif op == "lowercase":
        out = upstream_text.lower()
    else:
        out = upstream_text.strip()
    return {"summary": out}


def _execute_set_text_node(node: dict) -> dict:
    cfg = node.get("config") or {}
    return {"summary": cfg.get("text", "")}


def _execute_current_time_node() -> dict:
    return {"summary": automation_store.now()}


# ── Durable idempotency for automation-node external side effects ──────────
# PLAN.md invariant: "Every external side effect has an idempotency key and
# durable receipt before Temporal retries are enabled." Neither Slack
# incoming webhooks nor SendGrid's send endpoint have a native idempotency
# mechanism, so Astra's own durable action/receipt layer (run_automation_flow's
# own `run_id` + the node's id as step_id) is the only protection available.
# This module is already fully async, so no thread/asyncio.run bridging is
# needed (unlike the sync stripe_tools.py/gmail_api.py/resend_tools.py).
async def _execute_with_idempotency(
    *, run_id: str, step_id: str, tool: str, args: dict[str, Any],
    effect: Callable[[], Awaitable[dict]],
) -> dict:
    if not run_id:
        return await effect()

    from backend.control_plane.action_executor import (
        ExternalActionRequest,
        canonicalize_tool_args,
        execute_external_action,
        get_default_repo_bundle,
    )

    canonical_args = canonicalize_tool_args(args)
    action_id = hashlib.sha256(f"{run_id}::{step_id}::{tool}::{canonical_args}".encode("utf-8")).hexdigest()
    bundle = get_default_repo_bundle()

    async def _effect(_effect_args: dict, _idempotency_key: str) -> dict:
        return await effect()

    result = await execute_external_action(
        ExternalActionRequest(
            run_id=run_id,
            step_id=step_id or tool,
            action_id=action_id,
            tool=tool,
            args=args,
        ),
        action_repo=bundle.action_repo,
        receipt_repo=bundle.receipt_repo,
        approval_repo=bundle.approval_repo,
        execute_effect=_effect,
    )
    return dict(result.provider_result or {})


async def _execute_slack_node(node: dict, rendered_config: dict, run_id: str = "", node_id: str = "") -> dict:
    """Posts to a Slack incoming webhook — no OAuth needed, the founder just
    pastes the webhook URL Slack gives them, same as n8n/Zapier's Slack block."""
    from backend.tools.url_safety import validate_url
    import requests

    cfg = rendered_config
    webhook_url = cfg.get("webhook_url", "")
    message = cfg.get("message", "")

    async def _post() -> dict:
        validate_url(webhook_url)
        resp = await asyncio.to_thread(
            requests.post, webhook_url, json={"text": message}, timeout=15.0, allow_redirects=False,
        )
        if resp.status_code >= 400:
            return {"error": f"Slack webhook returned {resp.status_code}: {resp.text[:200]}"}
        return {"summary": f"Posted to Slack: {message[:100]}"}

    try:
        return await _execute_with_idempotency(
            run_id=run_id, step_id=node_id, tool="slack_webhook_post",
            args={"webhook_url": webhook_url, "message": message}, effect=_post,
        )
    except Exception as e:
        return {"error": str(e)}


async def _execute_email_node(node: dict, rendered_config: dict, founder_id: str, run_id: str = "", node_id: str = "") -> dict:
    """Sends email via the founder's own connected SendGrid key (set on the
    Integrations page) — never a shared/hardcoded credential."""
    from backend.provisioning.credentials_store import load_credentials
    import requests

    cfg = rendered_config
    to = cfg.get("to", "")
    subject = cfg.get("subject", "")
    body = cfg.get("body", "")
    creds = load_credentials(founder_id, "sendgrid")
    api_key = (creds or {}).get("api_key", "")
    if not api_key:
        return {"error": "SendGrid isn't connected — connect it on the Integrations page first."}
    payload = {
        "personalizations": [{"to": [{"email": to}]}],
        "from": {"email": cfg.get("from") or to},
        "subject": subject,
        "content": [{"type": "text/plain", "value": body}],
    }

    async def _post() -> dict:
        resp = await asyncio.to_thread(
            requests.post, "https://api.sendgrid.com/v3/mail/send",
            headers={"Authorization": f"Bearer {api_key}"}, json=payload, timeout=15.0,
        )
        if resp.status_code >= 300:
            return {"error": f"SendGrid returned {resp.status_code}: {resp.text[:200]}"}
        return {"summary": f"Emailed {to}: {subject}"}

    try:
        return await _execute_with_idempotency(
            run_id=run_id, step_id=node_id, tool="sendgrid_send_email",
            args={"to": to, "subject": subject, "body": body, "from": cfg.get("from") or to}, effect=_post,
        )
    except Exception as e:
        return {"error": str(e)}


async def _execute_gmail_node(rendered_config: dict, founder_id: str, run_id: str = "", node_id: str = "") -> dict:
    from backend.tools.gmail_api import gmail_send_email

    cfg = rendered_config
    to = str(cfg.get("to") or "").strip()
    subject = str(cfg.get("subject") or "").strip()
    body = str(cfg.get("body") or "").strip()
    if not to or not subject:
        return {"error": "Gmail node requires both 'to' and 'subject'."}
    return await asyncio.to_thread(gmail_send_email, founder_id, to, subject, body, run_id=run_id, step_id=node_id)


async def _execute_slack_bot_node(rendered_config: dict, founder_id: str) -> dict:
    import requests
    from backend.provisioning.credentials_store import load_credentials

    cfg = rendered_config
    channel = str(cfg.get("channel") or "").strip()
    message = str(cfg.get("message") or "").strip()
    if not channel or not message:
        return {"error": "Slack bot node requires both 'channel' and 'message'."}
    creds = load_credentials(founder_id, "slack") or {}
    token = str(creds.get("bot_token") or creds.get("token") or creds.get("access_token") or "").strip()
    if not token:
        return {"error": "Slack is not connected — connect it on the Integrations page first."}
    try:
        resp = await asyncio.to_thread(
            requests.post,
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
            json={"channel": channel, "text": message},
            timeout=15.0,
        )
        data = resp.json()
        if not data.get("ok"):
            return {"error": str(data.get("error") or "Slack API request failed")}
        return {"summary": f"Posted in Slack {channel}", "channel": channel, "ts": data.get("ts")}
    except Exception as e:
        return {"error": str(e)}


async def _execute_github_issue_node(rendered_config: dict, founder_id: str) -> dict:
    from backend.tools.composio_tools import composio_github_create_issue

    cfg = rendered_config
    repo = str(cfg.get("repo") or "").strip()
    title = str(cfg.get("title") or "").strip()
    body = str(cfg.get("body") or "").strip()
    owner = str(cfg.get("owner") or "").strip()
    if not repo or not title:
        return {"error": "GitHub issue node requires both 'repo' and 'title'."}
    return await asyncio.to_thread(composio_github_create_issue, founder_id, repo, title, body, owner)


async def _execute_github_pr_node(rendered_config: dict, founder_id: str) -> dict:
    from backend.tools.composio_tools import composio_github_create_pr

    cfg = rendered_config
    repo = str(cfg.get("repo") or "").strip()
    title = str(cfg.get("title") or "").strip()
    body = str(cfg.get("body") or "").strip()
    head = str(cfg.get("head") or "").strip()
    base = str(cfg.get("base") or "main").strip() or "main"
    owner = str(cfg.get("owner") or "").strip()
    if not repo or not title or not head:
        return {"error": "GitHub PR node requires 'repo', 'title', and 'head'."}
    return await asyncio.to_thread(composio_github_create_pr, founder_id, repo, title, body, head, base, owner)


async def _execute_linear_issue_node(rendered_config: dict, founder_id: str) -> dict:
    from backend.tools.composio_tools import composio_linear_create_issue

    cfg = rendered_config
    title = str(cfg.get("title") or "").strip()
    description = str(cfg.get("description") or cfg.get("body") or "").strip()
    if not title:
        return {"error": "Linear issue node requires a title."}
    return await asyncio.to_thread(composio_linear_create_issue, founder_id, title, description)


async def _execute_notion_page_node(rendered_config: dict, founder_id: str) -> dict:
    from backend.tools.composio_tools import composio_notion_create_page

    cfg = rendered_config
    title = str(cfg.get("title") or "").strip()
    parent_id = str(cfg.get("parent_id") or "").strip()
    if not title:
        return {"error": "Notion page node requires a title."}
    result = await asyncio.to_thread(composio_notion_create_page, founder_id, title, parent_id)
    body = str(cfg.get("body") or "").strip()
    if body and not result.get("error"):
        result["notes"] = body
    return result


async def _execute_stripe_payment_link_node(rendered_config: dict, founder_id: str) -> dict:
    from backend.tools.stripe_tools import create_product_with_payment_link

    cfg = rendered_config
    name = str(cfg.get("title") or "").strip()
    description = str(cfg.get("description") or "").strip()
    currency = str(cfg.get("currency") or "usd").strip().lower() or "usd"
    interval = str(cfg.get("interval") or "one_time").strip()
    amount_raw = cfg.get("amount")
    try:
        amount = int(float(amount_raw))
    except (TypeError, ValueError):
        return {"error": "Stripe payment link node requires a numeric amount."}
    if not name:
        return {"error": "Stripe payment link node requires a product name."}
    return await asyncio.to_thread(
        create_product_with_payment_link,
        name,
        description,
        amount,
        founder_id,
        "",
        currency,
        interval,
    )


async def _execute_integration_node(rendered_config: dict, founder_id: str) -> dict:
    """Dispatches to backend.tools.automation_blocks.INTEGRATION_BLOCKS — see
    that module for the full registry (Slack/Gmail/GitHub/Stripe/Twilio/etc).
    config: {block_key, params: {...}}."""
    from backend.tools.automation_blocks import INTEGRATION_BLOCKS

    block_key = rendered_config.get("block_key", "")
    block = INTEGRATION_BLOCKS.get(block_key)
    if block is None:
        return {"error": f"Unknown integration block '{block_key}'"}
    params = rendered_config.get("params") or {}
    try:
        return await asyncio.to_thread(block.run, params, founder_id)
    except Exception as e:
        return {"error": str(e)}


async def run_automation_flow(founder_id: str, flow_id: str, run_id: str, trigger_payload: dict | None = None) -> dict:
    """Executes a saved flow end-to-end, persisting + streaming per-node status.
    `run_id` must already exist (see automation_store.create_run) — the caller
    creates it up front so it can return the id to the client immediately,
    before this (usually backgrounded) execution starts. `trigger_payload` is
    set when the run was started by a webhook call — the trigger node's
    output becomes that JSON payload instead of the literal string "trigger"."""
    from backend.core.events import publish_sync

    flow = automation_store.get_flow(founder_id, flow_id)
    if not flow:
        raise ValueError(f"Flow '{flow_id}' not found")

    nodes = {n["id"]: n for n in flow.get("nodes", [])}
    edges = flow.get("edges", [])
    outputs: dict[str, str] = {}
    skipped: set[str] = set()
    dead_edges: set[tuple[str, str, str | None]] = set()

    publish_sync(run_id, {"type": "automation_run_started", "run_id": run_id, "flow_id": flow_id})

    try:
        order = _topo_order(list(nodes.values()), edges)
        for node_id in order:
            node = nodes.get(node_id)
            if node is None:
                continue

            if _node_is_dead(node_id, edges, skipped, dead_edges):
                skipped.add(node_id)
                automation_store.set_node_result(founder_id, run_id, node_id, {"status": "skipped", "output": {}})
                publish_sync(run_id, {"type": "node_status", "node_id": node_id, "status": "skipped"})
                continue

            publish_sync(run_id, {"type": "node_status", "node_id": node_id, "status": "running"})

            # Only follow live edges — a switch node's non-matching branches stay out
            # of upstream_text even though the switch node itself isn't "skipped".
            live_upstream = [
                e["source"] for e in edges
                if e.get("target") == node_id and e.get("source") not in skipped and _edge_key(e) not in dead_edges
            ]
            upstream_text = "\n\n".join(f"[{uid}]: {outputs.get(uid, '')}" for uid in live_upstream)
            cfg = node.get("config") or {}
            merged_outputs = dict(outputs)
            node_type = node.get("type")

            try:
                if node_type == "agent":
                    instruction = _render(cfg.get("instruction", ""), merged_outputs) or upstream_text
                    schema = cfg.get("output_schema")
                    if schema:
                        instruction = f"{instruction}\n\nRespond with ONLY valid JSON matching this shape (no prose, no code fences):\n{schema}"
                    result = await _execute_agent_node(node, instruction, founder_id, run_id)
                    if schema:
                        result = _coerce_json_summary(result)
                elif node_type == "prompt":
                    instruction = _render(cfg.get("instruction", ""), merged_outputs) or upstream_text
                    schema = cfg.get("output_schema")
                    if schema:
                        instruction = f"{instruction}\n\nRespond with ONLY valid JSON matching this shape (no prose, no code fences):\n{schema}"
                    result = await _execute_prompt_node(node, instruction, founder_id, run_id)
                    if schema:
                        result = _coerce_json_summary(result)
                elif node_type == "action":
                    rendered_cfg = _render_any(cfg, merged_outputs)
                    result = await _execute_action_node(node, rendered_cfg, founder_id)
                elif node_type == "delay":
                    result = await _execute_delay_node(node)
                elif node_type == "condition":
                    result = _execute_condition_node(node, upstream_text)
                elif node_type == "slack":
                    rendered_cfg = _render_any(cfg, merged_outputs)
                    result = await _execute_slack_node(node, rendered_cfg, run_id=run_id, node_id=node_id)
                elif node_type == "email":
                    rendered_cfg = _render_any(cfg, merged_outputs)
                    result = await _execute_email_node(node, rendered_cfg, founder_id, run_id=run_id, node_id=node_id)
                elif node_type == "gmail":
                    rendered_cfg = _render_any(cfg, merged_outputs)
                    result = await _execute_gmail_node(rendered_cfg, founder_id, run_id=run_id, node_id=node_id)
                elif node_type == "slack_bot":
                    rendered_cfg = _render_any(cfg, merged_outputs)
                    result = await _execute_slack_bot_node(rendered_cfg, founder_id)
                elif node_type == "github_issue":
                    rendered_cfg = _render_any(cfg, merged_outputs)
                    result = await _execute_github_issue_node(rendered_cfg, founder_id)
                elif node_type == "github_pr":
                    rendered_cfg = _render_any(cfg, merged_outputs)
                    result = await _execute_github_pr_node(rendered_cfg, founder_id)
                elif node_type == "linear_issue":
                    rendered_cfg = _render_any(cfg, merged_outputs)
                    result = await _execute_linear_issue_node(rendered_cfg, founder_id)
                elif node_type == "notion_page":
                    rendered_cfg = _render_any(cfg, merged_outputs)
                    result = await _execute_notion_page_node(rendered_cfg, founder_id)
                elif node_type == "stripe_payment_link":
                    rendered_cfg = _render_any(cfg, merged_outputs)
                    result = await _execute_stripe_payment_link_node(rendered_cfg, founder_id)
                elif node_type == "integration":
                    rendered_cfg = _render_any(cfg, merged_outputs)
                    result = await _execute_integration_node(rendered_cfg, founder_id)
                elif node_type == "merge":
                    result = _execute_merge_node(node, upstream_text)
                elif node_type == "json_extract":
                    result = _execute_json_extract_node(node, upstream_text)
                elif node_type == "text_transform":
                    result = _execute_text_transform_node(node, upstream_text)
                elif node_type == "condition_equals":
                    result = _execute_condition_equals_node(node, upstream_text)
                elif node_type == "set_text":
                    result = _execute_set_text_node(node)
                elif node_type == "current_time":
                    result = _execute_current_time_node()
                elif node_type == "switch":
                    rendered_cfg = _render_any(cfg, merged_outputs)
                    result = _execute_switch_node({**node, "config": rendered_cfg}, upstream_text)
                elif node_type == "code":
                    result = _execute_code_node(node, upstream_text)
                elif node_type == "trigger":
                    result = {"summary": json.dumps(trigger_payload) if trigger_payload else "trigger", "status": "ok"}
                else:
                    result = {"error": f"Unknown node type '{node_type}'"}
            except Exception as e:
                logger.exception("automation node %s failed", node_id)
                result = {"error": str(e)}

            if node_type in ("condition", "condition_equals") and result.get("passed") is False:
                skipped.add(node_id)
                outputs[node_id] = result.get("summary", "")
                automation_store.set_node_result(founder_id, run_id, node_id, {"status": "skipped", "output": result})
                publish_sync(run_id, {"type": "node_status", "node_id": node_id, "status": "skipped", "output": "condition not met"})
                continue

            if node_type == "switch":
                matched_handle = result.get("matched_handle", "default")
                for e in edges:
                    if e.get("source") == node_id and e.get("source_handle") not in (None, matched_handle):
                        dead_edges.add(_edge_key(e))

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
