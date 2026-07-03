"""Natural-language automation drafting for Astra-native flows.

This is intentionally deterministic and product-shaped, not a best-effort
LLM abstraction. We map common founder requests onto the canvas node types
Astra already knows how to execute — service-specific actions go through
the "integration" node type + registry (backend/tools/automation_blocks.py),
matching whatever the canvas itself produces when a founder builds a flow
by hand.
"""
from __future__ import annotations

import re
from typing import Any


def _slug(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return cleaned[:48] or "automation"


def _node(node_id: str, node_type: str, config: dict[str, Any], x: int, y: int) -> dict[str, Any]:
    return {"id": node_id, "type": node_type, "position": {"x": x, "y": y}, "config": config}


def _integration_node(node_id: str, block_key: str, params: dict[str, Any], x: int, y: int) -> dict[str, Any]:
    return _node(node_id, "integration", {"block_key": block_key, "params": params}, x, y)


def _edge(source: str, target: str) -> dict[str, str]:
    return {"source": source, "target": target}


def draft_flow_from_prompt(prompt: str) -> dict[str, Any]:
    text = (prompt or "").strip()
    lowered = text.lower()
    title = text[:80].strip() or "Untitled automation"

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []

    trigger_id = "trigger_1"
    nodes.append(_node(trigger_id, "trigger", {}, 80, 140))
    previous = trigger_id
    x = 320

    def add(node_type: str, config: dict[str, Any]) -> str:
        nonlocal previous, x
        node_id = f"{node_type}_{len(nodes) + 1}"
        nodes.append(_node(node_id, node_type, config, x, 140))
        edges.append(_edge(previous, node_id))
        previous = node_id
        x += 260
        return node_id

    def add_integration(block_key: str, params: dict[str, Any]) -> str:
        nonlocal previous, x
        node_id = f"integration_{len(nodes) + 1}"
        nodes.append(_integration_node(node_id, block_key, params, x, 140))
        edges.append(_edge(previous, node_id))
        previous = node_id
        x += 260
        return node_id

    if any(word in lowered for word in ("summarize", "triage", "review", "classify", "analyze", "digest", "route")):
        instruction = text
        if "upstream" not in instruction and "{{" not in instruction:
            instruction = f"{text}\n\nUse any upstream context to produce the next best action."
        add("prompt", {"instruction": instruction})

    has_prompt = len(nodes) > 1 and nodes[1]["type"] == "prompt"
    upstream_ref = "{{prompt_2.output}}" if has_prompt else text

    email_match = re.search(r"\bemail\s+([^\s,;]+@[^\s,;]+)", text, re.I)
    github_repo_match = re.search(r"\bgithub\b.*?\b(?:repo|repository)\s+([A-Za-z0-9_.-]+)", text, re.I)

    if "gmail" in lowered:
        add_integration("gmail_send", {"to": email_match.group(1) if email_match else "", "subject": "Astra automation update", "body": upstream_ref})
    elif "email" in lowered:
        add_integration("sendgrid_send", {"to": email_match.group(1) if email_match else "", "subject": "Astra automation update", "body": upstream_ref})

    if "slack" in lowered:
        add_integration("slack_webhook_post", {"webhook_url": "", "message": upstream_ref})

    if "linear" in lowered:
        add_integration("linear_create_issue", {"title": "Astra follow-up", "description": upstream_ref})

    if "notion" in lowered:
        add_integration("notion_create_page", {"title": "Astra automation note", "body": upstream_ref, "parent_id": ""})

    if "github" in lowered:
        add_integration("github_create_issue", {
            "repo": github_repo_match.group(1) if github_repo_match else "",
            "owner": "", "title": "Astra automation follow-up", "body": upstream_ref,
        })

    if "stripe" in lowered or "payment link" in lowered or "checkout" in lowered:
        add_integration("stripe_payment_link", {"title": "Astra offer", "description": upstream_ref, "amount": "99", "currency": "usd", "interval": "one_time"})

    if len(nodes) == 1:
        add("prompt", {"instruction": text})

    return {
        "name": _slug(title).replace("_", " ").title(),
        "nodes": nodes,
        "edges": edges,
        "explanation": "Drafted from natural language using Astra-native block heuristics.",
    }
