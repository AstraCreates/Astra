"""Generic automation runtime helpers backed by Windmill."""
from __future__ import annotations

import logging
from copy import deepcopy
from urllib.parse import quote

logger = logging.getLogger(__name__)

_TIMEOUT = 30


STARTER_AUTOMATIONS: dict[str, dict] = {
    "lead_follow_up": {
        "path": "u/admin/lead-follow-up",
        "title": "Lead follow-up",
        "summary": "Send a fast reply, route the lead, and create the next task automatically.",
        "description": "Astra-native starter automation for triaging inbound leads and suggesting the next action.",
        "default_payload": {
            "lead_name": "Alex Morgan",
            "email": "alex@example.com",
            "company": "Northstar Labs",
            "source": "website demo request",
            "message": "Looking for a fast walkthrough and pricing details this week.",
        },
        "flow": {
            "summary": "Lead follow-up",
            "description": "Classifies a lead, drafts a response, and proposes the next owner.",
            "schema": {
                "type": "object",
                "properties": {
                    "lead_name": {"type": "string"},
                    "email": {"type": "string"},
                    "company": {"type": "string"},
                    "source": {"type": "string"},
                    "message": {"type": "string"},
                    "founder_id": {"type": "string"},
                },
            },
            "value": {
                "modules": [
                    {
                        "id": "classify_lead",
                        "summary": "Classify the lead and suggest next actions",
                        "value": {
                            "type": "rawscript",
                            "language": "bun",
                            "input_transforms": {
                                "lead_name": {"type": "javascript", "expr": "flow_input.lead_name"},
                                "email": {"type": "javascript", "expr": "flow_input.email"},
                                "company": {"type": "javascript", "expr": "flow_input.company"},
                                "source": {"type": "javascript", "expr": "flow_input.source"},
                                "message": {"type": "javascript", "expr": "flow_input.message"},
                                "founder_id": {"type": "javascript", "expr": "flow_input.founder_id"},
                            },
                            "content": """export async function main({ lead_name, email, company, source, message, founder_id }) {\n  const warm = /demo|pricing|week|call|trial/i.test(message || \"\");\n  const priority = warm ? \"high\" : \"normal\";\n  const owner = warm ? \"sales\" : \"growth\";\n  return {\n    founder_id,\n    lead: { lead_name, email, company, source, message },\n    routing: { owner, priority, queue: warm ? \"founder_follow_up\" : \"lead_nurture\" },\n    draft_reply: `Hi ${lead_name || \"there\"}, thanks for reaching out about Astra. We can share a walkthrough and next steps based on ${company || \"your team\"}'s goals.`,\n    next_task: warm ? \"Book founder intro call within 24 hours\" : \"Send nurture sequence and track interest\",\n    status: \"triaged\"\n  };\n}""",
                        },
                    }
                ]
            },
        },
    },
    "support_triage": {
        "path": "u/admin/support-triage",
        "title": "Support triage",
        "summary": "Turn inbound issues into routed tickets with priority and owner rules.",
        "description": "Astra-native starter automation for classifying inbound support requests.",
        "default_payload": {
            "customer_email": "customer@example.com",
            "subject": "Billing page won't load",
            "body": "Our team can't access the billing page after logging in.",
            "severity_hint": "medium",
        },
        "flow": {
            "summary": "Support triage",
            "description": "Assigns support priority, owner, and a first-response draft.",
            "schema": {
                "type": "object",
                "properties": {
                    "customer_email": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                    "severity_hint": {"type": "string"},
                    "founder_id": {"type": "string"},
                },
            },
            "value": {
                "modules": [
                    {
                        "id": "triage_ticket",
                        "summary": "Create a support triage summary",
                        "value": {
                            "type": "rawscript",
                            "language": "bun",
                            "input_transforms": {
                                "customer_email": {"type": "javascript", "expr": "flow_input.customer_email"},
                                "subject": {"type": "javascript", "expr": "flow_input.subject"},
                                "body": {"type": "javascript", "expr": "flow_input.body"},
                                "severity_hint": {"type": "javascript", "expr": "flow_input.severity_hint"},
                                "founder_id": {"type": "javascript", "expr": "flow_input.founder_id"},
                            },
                            "content": """export async function main({ customer_email, subject, body, severity_hint, founder_id }) {\n  const critical = /outage|down|cannot login|can.t log in|payment failed/i.test(`${subject} ${body}`);\n  const priority = critical ? \"p1\" : (severity_hint || \"p2\");\n  const owner = critical ? \"engineering\" : \"support\";\n  return {\n    founder_id,\n    ticket: { customer_email, subject, body },\n    triage: { priority, owner, status: \"open\" },\n    response_draft: `Thanks for flagging this. We have routed your request to ${owner} and marked it ${priority.toUpperCase()}. We will follow up with the next update shortly.`,\n    internal_note: critical ? \"Escalate immediately and post incident check.\" : \"Handle in standard support queue.\"\n  };\n}""",
                        },
                    }
                ]
            },
        },
    },
    "weekly_founder_digest": {
        "path": "u/admin/weekly-founder-digest",
        "title": "Weekly founder digest",
        "summary": "Compile pipeline, blockers, and wins into one review-ready summary.",
        "description": "Astra-native starter automation for packaging a founder weekly review.",
        "default_payload": {
            "wins": ["Signed 2 design partners", "Shipped billing improvements"],
            "blockers": ["Need onboarding feedback", "Waiting on domain verification"],
            "priorities": ["Close first paid pilot", "Reduce onboarding drop-off"],
        },
        "flow": {
            "summary": "Weekly founder digest",
            "description": "Formats wins, blockers, and priorities into a compact weekly digest.",
            "schema": {
                "type": "object",
                "properties": {
                    "wins": {"type": "array", "items": {"type": "string"}},
                    "blockers": {"type": "array", "items": {"type": "string"}},
                    "priorities": {"type": "array", "items": {"type": "string"}},
                    "founder_id": {"type": "string"},
                },
            },
            "value": {
                "modules": [
                    {
                        "id": "compile_digest",
                        "summary": "Compile a founder digest",
                        "value": {
                            "type": "rawscript",
                            "language": "bun",
                            "input_transforms": {
                                "wins": {"type": "javascript", "expr": "flow_input.wins || []"},
                                "blockers": {"type": "javascript", "expr": "flow_input.blockers || []"},
                                "priorities": {"type": "javascript", "expr": "flow_input.priorities || []"},
                                "founder_id": {"type": "javascript", "expr": "flow_input.founder_id"},
                            },
                            "content": """export async function main({ wins = [], blockers = [], priorities = [], founder_id }) {\n  const bullet = (items) => (items.length ? items.map((x) => `- ${x}`).join(\"\\n\") : \"- None logged\");\n  return {\n    founder_id,\n    digest_markdown: `## Weekly founder digest\\n\\n### Wins\\n${bullet(wins)}\\n\\n### Blockers\\n${bullet(blockers)}\\n\\n### Next priorities\\n${bullet(priorities)}`,\n    counts: { wins: wins.length, blockers: blockers.length, priorities: priorities.length },\n    status: \"compiled\"\n  };\n}""",
                        },
                    }
                ]
            },
        },
    },
}


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


async def automation_trigger_flow(
    flow_path: str,
    payload: dict,
    founder_id: str = "",
) -> dict:
    """Trigger a flow in the configured automation runtime."""
    import httpx
    from backend.config import settings

    if (settings.automation_provider or "").strip().lower() != "windmill":
        return {"error": f"Unsupported automation provider: {settings.automation_provider}"}
    if not settings.automation_token:
        return {"error": "AUTOMATION_TOKEN not configured"}

    path = quote((flow_path or "").strip("/"), safe="/")
    base = settings.automation_base_url.rstrip("/")
    workspace = settings.automation_workspace.strip()
    url = f"{base}/w/{workspace}/jobs/run/f/{path}"

    body = dict(payload)
    if founder_id:
        body.setdefault("founder_id", founder_id)

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.post(url, json=body, headers=_headers(settings.automation_token))
            r.raise_for_status()
            return r.json() if r.content else {"ok": True}
    except Exception as e:
        logger.error("automation trigger_flow %s failed: %s", flow_path, e)
        return {"error": str(e)}


async def automation_list_flows(
    founder_id: str = "",
) -> dict:
    """List flows from the configured automation runtime."""
    import httpx
    from backend.config import settings

    if (settings.automation_provider or "").strip().lower() != "windmill":
        return {"error": f"Unsupported automation provider: {settings.automation_provider}"}
    if not settings.automation_token:
        return {"error": "AUTOMATION_TOKEN not configured"}

    base = settings.automation_base_url.rstrip("/")
    workspace = settings.automation_workspace.strip()
    url = f"{base}/w/{workspace}/flows/list"

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(url, headers=_headers(settings.automation_token))
            r.raise_for_status()
            data = r.json()
            if isinstance(data, list):
                return {"items": data}
            if isinstance(data, dict):
                return data
            return {"items": []}
    except Exception as e:
        logger.error("automation list_flows failed: %s", e)
        return {"error": str(e)}


async def automation_get_run(
    run_id: str,
    founder_id: str = "",
) -> dict:
    """Get a run/job from the configured automation runtime."""
    import httpx
    from backend.config import settings

    if (settings.automation_provider or "").strip().lower() != "windmill":
        return {"error": f"Unsupported automation provider: {settings.automation_provider}"}
    if not settings.automation_token:
        return {"error": "AUTOMATION_TOKEN not configured"}

    base = settings.automation_base_url.rstrip("/")
    workspace = settings.automation_workspace.strip()
    url = f"{base}/w/{workspace}/jobs_u/get/{quote(run_id, safe='')}"

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(url, headers=_headers(settings.automation_token))
            r.raise_for_status()
            return r.json() if r.content else {"ok": True}
    except Exception as e:
        logger.error("automation get_run %s failed: %s", run_id, e)
        return {"error": str(e)}


async def automation_create_flow(flow_def: dict) -> dict:
    import httpx
    from backend.config import settings

    if (settings.automation_provider or "").strip().lower() != "windmill":
        return {"error": f"Unsupported automation provider: {settings.automation_provider}"}
    if not settings.automation_token:
        return {"error": "AUTOMATION_TOKEN not configured"}

    base = settings.automation_base_url.rstrip("/")
    workspace = settings.automation_workspace.strip()
    url = f"{base}/w/{workspace}/flows/create"

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.post(url, json=flow_def, headers=_headers(settings.automation_token))
            r.raise_for_status()
            text = r.text.strip()
            return {"ok": True, "path": text or flow_def.get("path")}
    except Exception as e:
        logger.error("automation create_flow failed for %s: %s", flow_def.get("path"), e)
        return {"error": str(e)}


async def automation_update_flow(flow_path: str, flow_def: dict) -> dict:
    import httpx
    from backend.config import settings

    if (settings.automation_provider or "").strip().lower() != "windmill":
        return {"error": f"Unsupported automation provider: {settings.automation_provider}"}
    if not settings.automation_token:
        return {"error": "AUTOMATION_TOKEN not configured"}

    base = settings.automation_base_url.rstrip("/")
    workspace = settings.automation_workspace.strip()
    path = quote((flow_path or "").strip("/"), safe="/")
    url = f"{base}/w/{workspace}/flows/update/{path}"

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.post(url, json=flow_def, headers=_headers(settings.automation_token))
            r.raise_for_status()
            return {"ok": True, "path": flow_path}
    except Exception as e:
        logger.error("automation update_flow failed for %s: %s", flow_path, e)
        return {"error": str(e)}


def starter_automation_catalog() -> list[dict]:
    return [
        {
            "key": key,
            "path": value["path"],
            "title": value["title"],
            "summary": value["summary"],
            "description": value["description"],
        }
        for key, value in STARTER_AUTOMATIONS.items()
    ]


async def automation_install_starter(template_key: str) -> dict:
    template = STARTER_AUTOMATIONS.get(template_key)
    if not template:
        return {"error": f"Unknown starter automation: {template_key}"}

    existing = await automation_list_flows()
    items = existing.get("items") if isinstance(existing, dict) else []
    installed_paths = {
        str(item.get("path") or item.get("id") or "").strip("/")
        for item in items if isinstance(item, dict)
    }
    flow_payload = deepcopy(template["flow"])
    flow_payload["path"] = template["path"]

    if template["path"].strip("/") in installed_paths:
        result = await automation_update_flow(template["path"], flow_payload)
    else:
        result = await automation_create_flow(flow_payload)

    if result.get("error"):
        return result
    return {
        "ok": True,
        "template_key": template_key,
        "path": template["path"],
        "title": template["title"],
    }


async def automation_install_all_starters() -> dict:
    installed = []
    errors = []
    for key in STARTER_AUTOMATIONS:
        result = await automation_install_starter(key)
        if result.get("error"):
            errors.append({"key": key, "error": result["error"]})
        else:
            installed.append({"key": key, "path": result["path"], "title": result["title"]})
    return {"installed": installed, "errors": errors, "ok": len(errors) == 0}


def automation_default_payload(template_key: str) -> dict:
    template = STARTER_AUTOMATIONS.get(template_key)
    if not template:
        return {}
    return deepcopy(template.get("default_payload") or {})
