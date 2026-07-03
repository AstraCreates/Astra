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
        "category": "Sales",
        "integrations": ["gmail", "hubspot", "apollo"],
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
        "category": "Support",
        "integrations": ["gmail", "slack", "linear"],
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
        "category": "Ops",
        "integrations": ["notion", "slack", "linear"],
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
    "github_pr_triage": {
        "path": "u/admin/github-pr-triage",
        "title": "GitHub PR triage",
        "category": "Engineering",
        "integrations": ["github", "linear", "slack"],
        "summary": "Review new pull requests, assign the owner, and post the next action.",
        "description": "Starter automation for routing code review work inside Astra.",
        "default_payload": {
            "repo": "AstraCreates/Astra",
            "pr_number": 482,
            "title": "Fix automations starter install flow",
            "author": "contributor",
            "labels": ["frontend", "automations"],
        },
        "flow": {
            "summary": "GitHub PR triage",
            "description": "Summarizes a pull request and proposes routing.",
            "schema": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string"},
                    "pr_number": {"type": "number"},
                    "title": {"type": "string"},
                    "author": {"type": "string"},
                    "labels": {"type": "array", "items": {"type": "string"}},
                    "founder_id": {"type": "string"},
                },
            },
            "value": {
                "modules": [
                    {
                        "id": "triage_pr",
                        "summary": "Create PR routing guidance",
                        "value": {
                            "type": "rawscript",
                            "language": "bun",
                            "input_transforms": {
                                "repo": {"type": "javascript", "expr": "flow_input.repo"},
                                "pr_number": {"type": "javascript", "expr": "flow_input.pr_number"},
                                "title": {"type": "javascript", "expr": "flow_input.title"},
                                "author": {"type": "javascript", "expr": "flow_input.author"},
                                "labels": {"type": "javascript", "expr": "flow_input.labels || []"},
                                "founder_id": {"type": "javascript", "expr": "flow_input.founder_id"},
                            },
                            "content": """export async function main({ repo, pr_number, title, author, labels = [], founder_id }) {\n  const owner = labels.includes(\"frontend\") ? \"product-engineering\" : \"platform\";\n  return {\n    founder_id,\n    repo,\n    pr_number,\n    summary: `PR #${pr_number} in ${repo}: ${title}`,\n    routing: { owner, channel: \"engineering-review\", urgency: labels.includes(\"hotfix\") ? \"high\" : \"normal\" },\n    reviewer_note: `${author} opened a PR that likely needs ${owner} review next.`\n  };\n}""",
                        },
                    }
                ]
            },
        },
    },
    "notion_meeting_sync": {
        "path": "u/admin/notion-meeting-sync",
        "title": "Notion meeting sync",
        "category": "Workspace",
        "integrations": ["notion", "gmail", "google_calendar"],
        "summary": "Turn meeting notes into a Notion-ready brief with owners and follow-ups.",
        "description": "Starter automation for packaging meeting notes into a structured update.",
        "default_payload": {
            "meeting_title": "Weekly product sync",
            "notes": "Discussed onboarding friction, billing polish, and launch checklist.",
            "actions": ["Review onboarding dropoff", "Finalize billing QA"],
        },
        "flow": {
            "summary": "Notion meeting sync",
            "description": "Formats notes into a Notion-friendly summary.",
            "schema": {
                "type": "object",
                "properties": {
                    "meeting_title": {"type": "string"},
                    "notes": {"type": "string"},
                    "actions": {"type": "array", "items": {"type": "string"}},
                    "founder_id": {"type": "string"},
                },
            },
            "value": {
                "modules": [
                    {
                        "id": "shape_notes",
                        "summary": "Shape meeting notes into a page outline",
                        "value": {
                            "type": "rawscript",
                            "language": "bun",
                            "input_transforms": {
                                "meeting_title": {"type": "javascript", "expr": "flow_input.meeting_title"},
                                "notes": {"type": "javascript", "expr": "flow_input.notes"},
                                "actions": {"type": "javascript", "expr": "flow_input.actions || []"},
                                "founder_id": {"type": "javascript", "expr": "flow_input.founder_id"},
                            },
                            "content": """export async function main({ meeting_title, notes, actions = [], founder_id }) {\n  return {\n    founder_id,\n    notion_title: meeting_title,\n    summary: notes,\n    action_items: actions,\n    page_markdown: `# ${meeting_title}\\n\\n## Summary\\n${notes}\\n\\n## Actions\\n${actions.map((x) => `- ${x}`).join(\"\\n\") || \"- None\"}`\n  };\n}""",
                        },
                    }
                ]
            },
        },
    },
    "stripe_recovery_follow_up": {
        "path": "u/admin/stripe-recovery-follow-up",
        "title": "Stripe recovery follow-up",
        "category": "Revenue",
        "integrations": ["stripe", "gmail", "slack"],
        "summary": "Package failed payment context and draft the recovery follow-up.",
        "description": "Starter automation for failed-payment outreach and escalation.",
        "default_payload": {
            "customer_email": "buyer@example.com",
            "invoice_id": "in_12345",
            "amount": "$49",
            "failure_reason": "card_declined",
        },
        "flow": {
            "summary": "Stripe recovery follow-up",
            "description": "Summarizes a failed payment and drafts the follow-up.",
            "schema": {
                "type": "object",
                "properties": {
                    "customer_email": {"type": "string"},
                    "invoice_id": {"type": "string"},
                    "amount": {"type": "string"},
                    "failure_reason": {"type": "string"},
                    "founder_id": {"type": "string"},
                },
            },
            "value": {
                "modules": [
                    {
                        "id": "draft_recovery",
                        "summary": "Draft revenue recovery response",
                        "value": {
                            "type": "rawscript",
                            "language": "bun",
                            "input_transforms": {
                                "customer_email": {"type": "javascript", "expr": "flow_input.customer_email"},
                                "invoice_id": {"type": "javascript", "expr": "flow_input.invoice_id"},
                                "amount": {"type": "javascript", "expr": "flow_input.amount"},
                                "failure_reason": {"type": "javascript", "expr": "flow_input.failure_reason"},
                                "founder_id": {"type": "javascript", "expr": "flow_input.founder_id"},
                            },
                            "content": """export async function main({ customer_email, invoice_id, amount, failure_reason, founder_id }) {\n  return {\n    founder_id,\n    customer_email,\n    invoice_id,\n    amount,\n    recovery_stage: failure_reason === \"card_declined\" ? \"retry-needed\" : \"manual-review\",\n    draft_email: `We noticed your payment for ${amount} did not go through (${failure_reason}). Here is a quick link to update billing and keep things moving.`,\n    internal_alert: `Check ${invoice_id} and decide whether to retry automatically or escalate.`\n  };\n}""",
                        },
                    }
                ]
            },
        },
    },
    "slack_founder_alert": {
        "path": "u/admin/slack-founder-alert",
        "title": "Slack founder alert",
        "category": "Ops",
        "integrations": ["slack", "linear", "github"],
        "summary": "Bundle a high-priority event into a founder-ready Slack escalation.",
        "description": "Starter automation for alerting the founder with context and action items.",
        "default_payload": {
            "event": "Production deploy failed",
            "impact": "Users cannot access the billing flow",
            "owner": "engineering",
        },
        "flow": {
            "summary": "Slack founder alert",
            "description": "Shapes a critical event into an escalation packet.",
            "schema": {
                "type": "object",
                "properties": {
                    "event": {"type": "string"},
                    "impact": {"type": "string"},
                    "owner": {"type": "string"},
                    "founder_id": {"type": "string"},
                },
            },
            "value": {
                "modules": [
                    {
                        "id": "compose_alert",
                        "summary": "Compose founder alert packet",
                        "value": {
                            "type": "rawscript",
                            "language": "bun",
                            "input_transforms": {
                                "event": {"type": "javascript", "expr": "flow_input.event"},
                                "impact": {"type": "javascript", "expr": "flow_input.impact"},
                                "owner": {"type": "javascript", "expr": "flow_input.owner"},
                                "founder_id": {"type": "javascript", "expr": "flow_input.founder_id"},
                            },
                            "content": """export async function main({ event, impact, owner, founder_id }) {\n  return {\n    founder_id,\n    severity: \"high\",\n    slack_message: `Founder alert: ${event}. Impact: ${impact}. Owner: ${owner}.`,\n    next_action: `Ask ${owner} for ETA and post mitigation update.`\n  };\n}""",
                        },
                    }
                ]
            },
        },
    },
    "klaviyo_winback_draft": {
        "path": "u/admin/klaviyo-winback-draft",
        "title": "Klaviyo win-back draft",
        "category": "Marketing",
        "integrations": ["klaviyo", "stripe", "gmail"],
        "summary": "Draft a win-back campaign packet for churn-risk or lapsed buyers.",
        "description": "Starter automation for retention campaign planning.",
        "default_payload": {
            "segment": "Trial expired without upgrade",
            "offer": "20% off first paid month",
            "goal": "Recover 15 dormant trials",
        },
        "flow": {
            "summary": "Klaviyo win-back draft",
            "description": "Creates a retention message packet for email automation.",
            "schema": {
                "type": "object",
                "properties": {
                    "segment": {"type": "string"},
                    "offer": {"type": "string"},
                    "goal": {"type": "string"},
                    "founder_id": {"type": "string"},
                },
            },
            "value": {
                "modules": [
                    {
                        "id": "draft_campaign",
                        "summary": "Draft a win-back campaign outline",
                        "value": {
                            "type": "rawscript",
                            "language": "bun",
                            "input_transforms": {
                                "segment": {"type": "javascript", "expr": "flow_input.segment"},
                                "offer": {"type": "javascript", "expr": "flow_input.offer"},
                                "goal": {"type": "javascript", "expr": "flow_input.goal"},
                                "founder_id": {"type": "javascript", "expr": "flow_input.founder_id"},
                            },
                            "content": """export async function main({ segment, offer, goal, founder_id }) {\n  return {\n    founder_id,\n    audience: segment,\n    offer,\n    goal,\n    subject_line: `A quick reason to come back`,\n    campaign_brief: `Target ${segment}. Offer ${offer}. Goal: ${goal}.`\n  };\n}""",
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
            if not r.content:
                return {"ok": True}
            content_type = (r.headers.get("content-type") or "").lower()
            if "application/json" in content_type:
                return r.json()
            text = r.text.strip()
            return {"ok": True, "job_id": text} if text else {"ok": True}
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
            "category": value.get("category", "Automation"),
            "integrations": list(value.get("integrations") or []),
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
