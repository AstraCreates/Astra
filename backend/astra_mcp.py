"""Astra MCP Server — exposes the full Astra agent-stack system as MCP tools.

Implements the MCP JSON-RPC stdio protocol so Claude (or any MCP client)
can launch agent stacks, monitor sessions, retrieve artifacts, chat with
agents, and steer running runs.

Usage (stdio transport):
  python -m backend.astra_mcp

Claude Desktop config  (~/.claude/claude_desktop_config.json):
  {
    "mcpServers": {
      "astra": {
        "command": "python",
        "args": ["-m", "backend.astra_mcp"],
        "env": {
          "ASTRA_API_URL": "http://167.235.151.204",
          "ASTRA_FOUNDER_ID": "<your_clerk_user_id>"
        }
      }
    }
  }

Claude Code MCP config  (~/.claude.json  →  mcpServers):
  "astra": {
    "type": "stdio",
    "command": "python",
    "args": ["-m", "backend.astra_mcp"],
    "env": {
      "ASTRA_API_URL": "http://167.235.151.204",
      "ASTRA_FOUNDER_ID": "<your_clerk_user_id>"
    }
  }
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

SERVER_INFO = {"name": "astra", "version": "1.1.0"}

# ── Config ────────────────────────────────────────────────────────────────────

def _api_url() -> str:
    return os.environ.get("ASTRA_API_URL", "http://localhost:8000").rstrip("/")

import contextvars as _contextvars
_FOUNDER_OVERRIDE: "_contextvars.ContextVar[str | None]" = _contextvars.ContextVar("astra_mcp_founder", default=None)


def set_founder_override(founder_id: str | None):
    """In-process callers (e.g. the copilot) run these tools AS a specific founder
    instead of the env default. Returns a token; pass it to reset_founder_override."""
    return _FOUNDER_OVERRIDE.set(founder_id or None)


def reset_founder_override(token) -> None:
    try:
        _FOUNDER_OVERRIDE.reset(token)
    except Exception:
        pass


def call_tool(name: str, arguments: dict, founder_id: str | None = None) -> Any:
    """Invoke an MCP tool by name in-process, as `founder_id`. Returns the raw
    handler payload (not MCP-wrapped). Raises on unknown tool."""
    if name in _LEGACY_MCP_TOOLS:
        raise ValueError("This MCP run/session tool was removed. Use Company OS tools instead.")
    fn = _DISPATCH.get(name)
    if fn is None:
        raise ValueError(f"Unknown tool: {name}")
    token = set_founder_override(founder_id) if founder_id else None
    try:
        return fn(arguments or {})
    finally:
        if token is not None:
            reset_founder_override(token)


def _founder_id() -> str:
    return _FOUNDER_OVERRIDE.get() or os.environ.get("ASTRA_FOUNDER_ID", "founder_001")

# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _headers() -> dict[str, str]:
    # Authenticate as the configured founder so auth-gated endpoints (brain, goals,
    # credits) accept the call regardless of server auth mode.
    return {"Content-Type": "application/json", "x-astra-user-id": _founder_id()}

def _get(path: str, params: dict | None = None, timeout: int = 15) -> Any:
    url = _api_url() + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    req = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

def _post(path: str, body: dict, timeout: int = 20) -> Any:
    url = _api_url() + path
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=_headers(), method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

# ── Tool schema builder ───────────────────────────────────────────────────────

def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required or [], "additionalProperties": False}

# ── Tool definitions ──────────────────────────────────────────────────────────

TOOLS: list[dict[str, Any]] = [
    {
        "name": "astra_submit_goal",
        "description": (
            "Launch an Astra agent-stack run. Describe any business goal in plain English — "
            "Astra will decompose it and dispatch specialist agents (research, legal, web, "
            "technical, marketing, ops, sales, design) to execute in parallel. "
            "Returns a session_id you can use to monitor progress and retrieve results."
        ),
        "inputSchema": _schema({
            "goal": {"type": "string", "description": "Plain-English description of what to build or achieve."},
            "stack_id": {
                "type": "string",
                "description": "Agent stack preset to use. Options: idea_to_revenue, sales, marketing, founder_ops, support, product, custom. Defaults to idea_to_revenue.",
                "default": "idea_to_revenue",
            },
            "agents": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Only for stack_id=custom: list of agent IDs to include (e.g. ['research','web','technical']). research is always included.",
            },
            "company_name": {"type": "string", "description": "Company or product name (optional, improves output quality)."},
            "founder_id": {"type": "string", "description": "Founder/user ID. Defaults to ASTRA_FOUNDER_ID env var."},
        }, ["goal"]),
    },
    {
        "name": "astra_session_status",
        "description": (
            "Get the current status of an Astra session — which agents are running/done, "
            "overall completion percentage, errors, and a short digest of what's been produced so far."
        ),
        "inputSchema": _schema({
            "session_id": {"type": "string", "description": "Session ID returned by astra_submit_goal."},
            "founder_id": {"type": "string", "description": "Founder/user ID."},
        }, ["session_id"]),
    },
    {
        "name": "astra_session_digest",
        "description": (
            "Get a comprehensive digest of a completed or in-progress Astra session: "
            "key findings, decisions, artifacts produced, agent summaries, and next steps."
        ),
        "inputSchema": _schema({
            "session_id": {"type": "string", "description": "Session ID."},
            "founder_id": {"type": "string", "description": "Founder/user ID."},
        }, ["session_id"]),
    },
    {
        "name": "astra_session_artifacts",
        "description": (
            "Retrieve all artifacts produced in an Astra session — landing page URLs, "
            "legal documents, research briefs, marketing copy, codebase links, financial models, etc."
        ),
        "inputSchema": _schema({
            "session_id": {"type": "string", "description": "Session ID."},
            "founder_id": {"type": "string", "description": "Founder/user ID."},
        }, ["session_id"]),
    },
    {
        "name": "astra_chat_agent",
        "description": (
            "Send a question or instruction directly to a specific Astra specialist agent "
            "within a session context. The agent responds with expertise grounded in the "
            "session's research, goals, and company context."
        ),
        "inputSchema": _schema({
            "agent": {
                "type": "string",
                "description": "Agent ID to talk to. Options: research, legal, web, technical, marketing, ops, sales, design, research_market, research_financial, legal_docs, marketing_content, marketing_seo, technical_scaffold, etc.",
            },
            "question": {"type": "string", "description": "Question or instruction for the agent."},
            "session_id": {"type": "string", "description": "Session ID for context (optional but recommended)."},
            "company_name": {"type": "string", "description": "Company name for context."},
            "founder_id": {"type": "string", "description": "Founder/user ID."},
        }, ["agent", "question"]),
    },
    {
        "name": "astra_steer",
        "description": (
            "Broadcast a steering instruction to ALL running agents in a session — "
            "redirect, add constraints, change priorities, inject information mid-run."
        ),
        "inputSchema": _schema({
            "session_id": {"type": "string", "description": "Session ID of the running session."},
            "message": {"type": "string", "description": "Steering instruction to inject into the running session."},
            "founder_id": {"type": "string", "description": "Founder/user ID."},
        }, ["session_id", "message"]),
    },
    {
        "name": "astra_message_agent",
        "description": (
            "Send a directive directly to ONE specific named agent in a running session. "
            "Only that agent receives the instruction. Use when you want to talk to a specific "
            "agent as a manager would to an employee (e.g. tell only the web agent to redesign, "
            "or only the sales agent to focus on enterprise leads)."
        ),
        "inputSchema": _schema({
            "session_id": {"type": "string", "description": "Session ID of the running session."},
            "agent": {"type": "string", "description": "Agent name to target: web, technical, sales, design, research, marketing, ops, legal, etc."},
            "message": {"type": "string", "description": "Directive for the agent."},
            "founder_id": {"type": "string", "description": "Founder/user ID."},
        }, ["session_id", "agent", "message"]),
    },
    {
        "name": "astra_stop_agent",
        "description": (
            "Instantly STOP one running agent by name — it halts at its next step. Unlike "
            "astra_message_agent (which only asks the agent to change course), this enforces a "
            "hard stop while the rest of the run keeps going. Use for 'stop/halt/kill the X agent'."
        ),
        "inputSchema": _schema({
            "session_id": {"type": "string", "description": "Session ID of the running session."},
            "agent": {"type": "string", "description": "Agent name to stop: web, technical, sales, design, research, marketing, ops, legal, etc."},
            "founder_id": {"type": "string", "description": "Founder/user ID."},
        }, ["session_id", "agent"]),
    },
    {
        "name": "astra_list_stacks",
        "description": (
            "List all available Astra agent stack presets with their descriptions, "
            "expected outputs, and which agents they use."
        ),
        "inputSchema": _schema({}),
    },
    {
        "name": "astra_list_agents",
        "description": "List all available Astra specialist agents with their capabilities and what they produce.",
        "inputSchema": _schema({}),
    },
    {
        "name": "astra_recommend_stack",
        "description": (
            "Given a goal description, Astra recommends the best agent stack preset "
            "and explains why. Use this before astra_submit_goal if unsure which stack to pick."
        ),
        "inputSchema": _schema({
            "goal": {"type": "string", "description": "Plain-English goal to get a stack recommendation for."},
        }, ["goal"]),
    },
    {
        "name": "astra_approve",
        "description": (
            "Approve a pending safe-run gate in an Astra session. Some agent actions "
            "(deploying to Vercel, sending emails, publishing legal docs) require founder "
            "approval before execution. Use this to approve them."
        ),
        "inputSchema": _schema({
            "session_id": {"type": "string"},
            "action_key": {"type": "string", "description": "The approval gate key (e.g. 'public_deploy', 'send_outbound')."},
            "request_id": {"type": "string", "description": "Exact pending approval request ID from the session approval ledger."},
            "expected_action_digest": {"type": "string", "description": "Exact action_digest from that same pending request."},
            "founder_id": {"type": "string"},
        }, ["session_id", "action_key", "request_id", "expected_action_digest"]),
    },
    {
        "name": "astra_session_workboard",
        "description": "Get the current task workboard for a session — all tasks, their status, assignees, and blockers.",
        "inputSchema": _schema({
            "session_id": {"type": "string"},
            "founder_id": {"type": "string"},
        }, ["session_id"]),
    },
    # ── Company brain (GraphRAG) ──
    {
        "name": "astra_ask_brain",
        "description": (
            "Ask the company brain a question. Returns a synthesized, cited answer grounded in "
            "the founder's accumulated company knowledge (research, agent outputs, connected "
            "sources) via GraphRAG retrieval. Use for 'what do we know about X', 'what's our "
            "ICP/pricing/positioning', 'what did the team produce', etc."
        ),
        "inputSchema": _schema({
            "question": {"type": "string", "description": "The question to answer from company knowledge."},
            "limit": {"type": "integer", "description": "Max records to ground on (default 8).", "default": 8},
            "founder_id": {"type": "string"},
        }, ["question"]),
    },
    {
        "name": "astra_search_brain",
        "description": "Search the company brain for matching records (GraphRAG). Returns ranked records with snippets. Use to find specific facts/sources rather than a synthesized answer.",
        "inputSchema": _schema({
            "query": {"type": "string", "description": "Search query."},
            "limit": {"type": "integer", "default": 8},
            "founder_id": {"type": "string"},
        }, ["query"]),
    },
    {
        "name": "astra_brain_graph",
        "description": "Get the GraphRAG entity map of the company brain — nodes (entities), edges (relationships), and communities — for visualization or structural inspection.",
        "inputSchema": _schema({"founder_id": {"type": "string"}}),
    },
    # ── Company goals (the operating loop) ──
    {
        "name": "astra_company_goal",
        "description": (
            "Get the founder's company operating state: the north star, the current goal and "
            "its tasks (with status + per-task owner agents), any PROPOSED next goal awaiting "
            "approval, completed goals, recent operating sub-runs, and credits spent per goal."
        ),
        "inputSchema": _schema({"founder_id": {"type": "string"}}),
    },
    {
        "name": "astra_approve_next_goal",
        "description": (
            "Approve or reject the planner's PROPOSED next company goal. approved=true puts the "
            "team on it (it dispatches); approved=false drops it and the planner proposes another. "
            "Use after astra_company_goal shows a goal with status 'proposed'."
        ),
        "inputSchema": _schema({
            "approved": {"type": "boolean", "description": "true to approve & start, false to reject.", "default": True},
            "founder_id": {"type": "string"},
        }),
    },
    {
        "name": "astra_run_cycle",
        "description": "Run the current (already-approved) company goal now — dispatches the team on its open tasks in a child operating run. Returns the parent session id.",
        "inputSchema": _schema({"founder_id": {"type": "string"}}),
    },
    # ── Credits ──
    {
        "name": "astra_credits",
        "description": "Get the founder's credit balance and usage (1 credit = $0.005). Returns balance, total granted, total used.",
        "inputSchema": _schema({"founder_id": {"type": "string"}}),
    },
    {
        "name": "astra_company_os_context",
        "description": "Read the local-first Company OS snapshot: initiatives, squads, missions, tasks, approvals, artifacts, and Company Brain references. Never creates a legacy session.",
        "inputSchema": _schema({"company_id": {"type": "string"}, "founder_id": {"type": "string"}}, ["company_id"]),
    },
    {
        "name": "astra_company_research",
        "description": "Run cited web research for a Company OS mission. This is internal research only; it creates no external side effect.",
        "inputSchema": _schema({"company_id": {"type": "string"}, "subject": {"type": "string"}, "focus": {"type": "string", "default": "market"}, "founder_id": {"type": "string"}}, ["company_id", "subject"]),
    },
]

# The old MCP actions were session/run commands. Phase 3 keeps only tools that
# operate on Company OS or bounded shared services; clients receive a removal
# error rather than accidentally starting legacy work.
_LEGACY_MCP_TOOLS = {
    "astra_submit_goal", "astra_session_status", "astra_session_digest",
    "astra_session_artifacts", "astra_chat_agent", "astra_steer",
    "astra_message_agent", "astra_stop_agent", "astra_approve",
    "astra_session_workboard", "astra_company_goal", "astra_approve_next_goal",
    "astra_run_cycle",
}
TOOLS = [tool for tool in TOOLS if tool["name"] not in _LEGACY_MCP_TOOLS]

# ── Tool implementations ──────────────────────────────────────────────────────

def _submit_goal(args: dict) -> dict:
    founder_id = args.get("founder_id") or _founder_id()
    stack_id = args.get("stack_id") or "idea_to_revenue"
    constraints: dict[str, Any] = {}
    if args.get("company_name"):
        constraints["company_name"] = args["company_name"]
    if stack_id == "custom" and args.get("agents"):
        constraints["agents"] = args["agents"]
    payload = {
        "founder_id": founder_id,
        "instruction": args["goal"],
        "stack_id": stack_id,
        "constraints": constraints,
    }
    result = _post("/goal", payload, timeout=15)
    return {
        "ok": True,
        "session_id": result.get("session_id"),
        "status": result.get("status"),
        "message": f"Session started. Use astra_session_status(session_id='{result.get('session_id')}') to monitor progress.",
        "monitor_url": f"{_api_url()}/stream/{result.get('session_id')}",
    }

def _session_status(args: dict) -> dict:
    session_id = args["session_id"]
    founder_id = args.get("founder_id") or _founder_id()
    try:
        state = _get(f"/sessions/{session_id}/state", {"founder_id": founder_id})
    except Exception as e:
        return {"ok": False, "error": str(e)}
    agents = state.get("agents", {})
    done_count = sum(1 for a in agents.values() if a.get("status") == "done")
    total = len(agents)
    return {
        "ok": True,
        "session_id": session_id,
        "done": state.get("done", False),
        "agents_done": done_count,
        "agents_total": total,
        "completion_pct": round(done_count / total * 100) if total else 0,
        "agents": {k: {"status": v.get("status"), "current_tool": v.get("currentTool")} for k, v in agents.items()},
        "errors": [k for k, v in agents.items() if v.get("status") == "error"],
    }

def _session_digest(args: dict) -> dict:
    session_id = args["session_id"]
    founder_id = args.get("founder_id") or _founder_id()
    try:
        digest = _get(f"/sessions/{session_id}/digest", {"founder_id": founder_id})
        return {"ok": True, "session_id": session_id, **digest}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _session_artifacts(args: dict) -> dict:
    session_id = args["session_id"]
    founder_id = args.get("founder_id") or _founder_id()
    try:
        state = _get(f"/sessions/{session_id}/state", {"founder_id": founder_id})
        artifacts = state.get("artifacts", [])
        return {"ok": True, "session_id": session_id, "artifact_count": len(artifacts), "artifacts": artifacts}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _chat_agent(args: dict) -> dict:
    agent = args["agent"]
    founder_id = args.get("founder_id") or _founder_id()
    payload = {
        "target_agent": agent,
        "question": args["question"],
        "founder_id": founder_id,
        "session_id": args.get("session_id"),
        "company_name": args.get("company_name"),
    }
    try:
        result = _post(f"/chat/{agent}", payload)
        return {"ok": True, "agent": agent, "response": result.get("response", result)}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _steer(args: dict) -> dict:
    session_id = args["session_id"]
    try:
        _post(f"/steer/{session_id}", {"message": args["message"]})
        return {"ok": True, "session_id": session_id, "message": "Steering instruction delivered."}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _message_agent(args: dict) -> dict:
    session_id = args["session_id"]
    agent_name = str(args.get("agent", "")).strip().lower()
    message = str(args.get("message", "")).strip()
    try:
        _post(f"/steer/{session_id}", {"message": message, "agent_name": agent_name})
        return {"ok": True, "session_id": session_id, "target_agent": agent_name, "delivered": message}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _stop_agent(args: dict) -> dict:
    session_id = args["session_id"]
    agent_name = str(args.get("agent", "")).strip().lower()
    try:
        _post(f"/sessions/{session_id}/stop-agent/{agent_name}", {})
        return {"ok": True, "session_id": session_id, "stopped": agent_name}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _list_stacks(_args: dict) -> dict:
    try:
        data = _get("/stacks")
        stacks = data.get("stacks", [])
        return {
            "ok": True,
            "stacks": [
                {"id": s["stack_id"], "name": s["name"], "target_user": s["target_user"],
                 "primary_outcome": s["primary_outcome"], "agent_count": len(s.get("tasks", []))}
                for s in stacks
            ],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _list_agents(_args: dict) -> dict:
    try:
        data = _get("/agents/catalog")
        return {"ok": True, "agents": data.get("agents", [])}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _recommend_stack(args: dict) -> dict:
    try:
        result = _post("/stacks/recommend", {"instruction": args["goal"]})
        stack = result.get("stack", {})
        return {
            "ok": True,
            "recommended_stack_id": stack.get("stack_id"),
            "recommended_stack_name": stack.get("name"),
            "confidence": result.get("confidence"),
            "reason": result.get("reason"),
            "matched_signals": result.get("matched_signals", []),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _approve(args: dict) -> dict:
    session_id = args["session_id"]
    founder_id = args.get("founder_id") or _founder_id()
    gate_key = str(args.get("action_key") or args.get("gate_key") or "").strip()
    request_id = str(args.get("request_id") or args.get("approval_id") or "").strip()
    expected_action_digest = str(args.get("expected_action_digest") or "").strip()
    if not gate_key:
        return {"ok": False, "error": "action_key (approval gate key) is required"}
    if not request_id or not expected_action_digest:
        return {"ok": False, "error": "request_id and expected_action_digest are required; fetch the pending approval request first"}
    try:
        result = _post("/stack/approval", {
            "session_id": session_id,
            # The public MCP tool historically called this action_key, while
            # the API and durable ledger use gate_key and "approved".
            "gate_key": gate_key,
            "decision": "approved",
            "founder_id": founder_id,
            "request_id": request_id,
            "expected_action_digest": expected_action_digest,
        })
        return result if isinstance(result, dict) else {"ok": True, "result": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _workboard(args: dict) -> dict:
    session_id = args["session_id"]
    founder_id = args.get("founder_id") or _founder_id()
    try:
        result = _get(f"/sessions/{session_id}/workboard", {"founder_id": founder_id})
        return {"ok": True, "session_id": session_id, **result}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _ask_brain(args: dict) -> dict:
    founder_id = args.get("founder_id") or _founder_id()
    try:
        return {"ok": True, **_post(f"/brain/{founder_id}/ask", {"question": args["question"], "limit": int(args.get("limit") or 8)})}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _search_brain(args: dict) -> dict:
    founder_id = args.get("founder_id") or _founder_id()
    try:
        return {"ok": True, **_get(f"/brain/{founder_id}/search", {"q": args["query"], "limit": int(args.get("limit") or 8)})}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _brain_graph(args: dict) -> dict:
    founder_id = args.get("founder_id") or _founder_id()
    try:
        return {"ok": True, **_get(f"/brain/{founder_id}/graph-rag")}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _company_goal(args: dict) -> dict:
    founder_id = args.get("founder_id") or _founder_id()
    try:
        return {"ok": True, **_get("/missions/company-goal", {"founder_id": founder_id})}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _approve_next_goal(args: dict) -> dict:
    founder_id = args.get("founder_id") or _founder_id()
    approved = args.get("approved")
    approved = True if approved is None else bool(approved)
    try:
        return {"ok": True, **_post("/missions/company-goal/approve-next", {"founder_id": founder_id, "approved": approved})}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _run_cycle(args: dict) -> dict:
    founder_id = args.get("founder_id") or _founder_id()
    try:
        return {"ok": True, **_post(f"/missions/company-goal/run?founder_id={urllib.parse.quote(founder_id)}", {})}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _credits(args: dict) -> dict:
    founder_id = args.get("founder_id") or _founder_id()
    try:
        return {"ok": True, **_get("/credits", {"founder_id": founder_id})}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def _company_os_context(args: dict) -> dict:
    from backend.company_os import get_company_os
    company = get_company_os(str(args["company_id"]))
    if not company:
        return {"ok": False, "error": "Company not found"}
    if company.get("founder_id") != (args.get("founder_id") or _founder_id()):
        return {"ok": False, "error": "Company not found"}
    return {"ok": True, "company": company}

def _company_research(args: dict) -> dict:
    from backend.company_os import get_company_os
    from backend.tools.browser_research import run_comparison_research, run_research_pipeline
    company = get_company_os(str(args["company_id"]))
    if not company or company.get("founder_id") != (args.get("founder_id") or _founder_id()):
        return {"ok": False, "error": "Company not found"}
    subject = str(args["subject"])
    evidence = run_comparison_research(subject) if "compare" in subject.lower() else run_research_pipeline(subject, focus=str(args.get("focus") or "market"), max_results_each=6)
    return {"ok": not bool(evidence.get("error")), **evidence}

_DISPATCH: dict[str, Any] = {
    "astra_submit_goal": _submit_goal,
    "astra_session_status": _session_status,
    "astra_session_digest": _session_digest,
    "astra_session_artifacts": _session_artifacts,
    "astra_chat_agent": _chat_agent,
    "astra_steer": _steer,
    "astra_message_agent": _message_agent,
    "astra_stop_agent": _stop_agent,
    "astra_list_stacks": _list_stacks,
    "astra_list_agents": _list_agents,
    "astra_recommend_stack": _recommend_stack,
    "astra_approve": _approve,
    "astra_session_workboard": _workboard,
    "astra_ask_brain": _ask_brain,
    "astra_search_brain": _search_brain,
    "astra_brain_graph": _brain_graph,
    "astra_company_goal": _company_goal,
    "astra_approve_next_goal": _approve_next_goal,
    "astra_run_cycle": _run_cycle,
    "astra_credits": _credits,
    "astra_company_os_context": _company_os_context,
    "astra_company_research": _company_research,
}

# ── JSON-RPC handler ──────────────────────────────────────────────────────────

def _tool_result(payload: dict) -> dict:
    is_error = not payload.get("ok", True)
    return {
        "content": [{"type": "text", "text": json.dumps(payload, indent=2, sort_keys=True)}],
        "structuredContent": payload,
        "isError": is_error,
    }

def handle_request(request: dict) -> dict | None:
    request_id = request.get("id")
    method = request.get("method")
    params = request.get("params") or {}
    if request_id is None:
        return None
    try:
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "serverInfo": SERVER_INFO,
                "capabilities": {"tools": {}},
            }
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments") or {}
            fn = _DISPATCH.get(name)
            if fn is None:
                raise ValueError(f"Unknown tool: {name}")
            result = _tool_result(fn(arguments))
        else:
            raise ValueError(f"Unsupported method: {method}")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except Exception as exc:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32000, "message": str(exc)}}

# ── Stdio server ──────────────────────────────────────────────────────────────

def serve(stdin=None, stdout=None) -> None:
    in_ = stdin or sys.stdin
    out = stdout or sys.stdout
    for line in in_:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}
        else:
            response = handle_request(request)
        if response is not None:
            out.write(json.dumps(response, separators=(",", ":")) + "\n")
            out.flush()

def main() -> None:
    serve()

if __name__ == "__main__":
    main()
