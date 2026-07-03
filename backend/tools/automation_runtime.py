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
    "vercel_launch_readiness": {
        "path": "u/admin/vercel-launch-readiness",
        "title": "Vercel launch readiness",
        "category": "Launch",
        "integrations": ["vercel", "github", "slack"],
        "summary": "Package deploy risk, launch notes, and the owner handoff before shipping.",
        "description": "Starter automation for converting release context into a launch checklist.",
        "default_payload": {
            "project": "astra-app",
            "environment": "production",
            "recent_changes": ["Automations page refresh", "Windmill runtime hookup"],
            "known_risks": ["Need one last mobile QA pass"],
        },
        "flow": {
            "summary": "Vercel launch readiness",
            "description": "Shapes deploy context into a founder-friendly launch brief.",
            "schema": {
                "type": "object",
                "properties": {
                    "project": {"type": "string"},
                    "environment": {"type": "string"},
                    "recent_changes": {"type": "array", "items": {"type": "string"}},
                    "known_risks": {"type": "array", "items": {"type": "string"}},
                    "founder_id": {"type": "string"},
                },
            },
            "value": {
                "modules": [
                    {
                        "id": "prepare_launch_packet",
                        "summary": "Prepare a launch readiness packet",
                        "value": {
                            "type": "rawscript",
                            "language": "bun",
                            "input_transforms": {
                                "project": {"type": "javascript", "expr": "flow_input.project"},
                                "environment": {"type": "javascript", "expr": "flow_input.environment"},
                                "recent_changes": {"type": "javascript", "expr": "flow_input.recent_changes || []"},
                                "known_risks": {"type": "javascript", "expr": "flow_input.known_risks || []"},
                                "founder_id": {"type": "javascript", "expr": "flow_input.founder_id"},
                            },
                            "content": """export async function main({ project, environment, recent_changes = [], known_risks = [], founder_id }) {\n  const bullet = (items) => items.length ? items.map((x) => `- ${x}`).join(\"\\n\") : \"- None\";\n  return {\n    founder_id,\n    project,\n    environment,\n    release_summary: `${project} is preparing for ${environment} launch readiness review.`,\n    launch_packet: `## Launch packet\\n\\n### Recent changes\\n${bullet(recent_changes)}\\n\\n### Known risks\\n${bullet(known_risks)}`,\n    recommendation: known_risks.length > 0 ? \"Hold until risks are closed or explicitly accepted.\" : \"Ready for deploy.\"\n  };\n}""",
                        },
                    }
                ]
            },
        },
    },
    "sendgrid_campaign_qa": {
        "path": "u/admin/sendgrid-campaign-qa",
        "title": "SendGrid campaign QA",
        "category": "Marketing",
        "integrations": ["sendgrid", "gmail", "notion"],
        "summary": "Review a campaign draft, catch risk points, and prep the launch checklist.",
        "description": "Starter automation for email campaign quality review before send.",
        "default_payload": {
            "campaign_name": "Founder summer launch",
            "audience": "Warm waitlist",
            "subject_line": "Astra is ready for your team",
            "body_summary": "Product launch email with founder note and invite link.",
        },
        "flow": {
            "summary": "SendGrid campaign QA",
            "description": "Creates a lightweight QA packet for outbound email campaigns.",
            "schema": {
                "type": "object",
                "properties": {
                    "campaign_name": {"type": "string"},
                    "audience": {"type": "string"},
                    "subject_line": {"type": "string"},
                    "body_summary": {"type": "string"},
                    "founder_id": {"type": "string"},
                },
            },
            "value": {
                "modules": [
                    {
                        "id": "qa_campaign",
                        "summary": "QA outbound campaign",
                        "value": {
                            "type": "rawscript",
                            "language": "bun",
                            "input_transforms": {
                                "campaign_name": {"type": "javascript", "expr": "flow_input.campaign_name"},
                                "audience": {"type": "javascript", "expr": "flow_input.audience"},
                                "subject_line": {"type": "javascript", "expr": "flow_input.subject_line"},
                                "body_summary": {"type": "javascript", "expr": "flow_input.body_summary"},
                                "founder_id": {"type": "javascript", "expr": "flow_input.founder_id"},
                            },
                            "content": """export async function main({ campaign_name, audience, subject_line, body_summary, founder_id }) {\n  const risky = /free|guarantee|urgent|act now/i.test(`${subject_line} ${body_summary}`);\n  return {\n    founder_id,\n    campaign_name,\n    audience,\n    qa_status: risky ? \"needs-review\" : \"ready\",\n    checklist: [\n      \"Confirm links and CTA destinations\",\n      \"Verify unsubscribe + footer copy\",\n      \"Send internal preview to founder\"\n    ],\n    reviewer_note: risky ? \"Tone may trigger deliverability or trust concerns.\" : \"No obvious copy risk detected.\"\n  };\n}""",
                        },
                    }
                ]
            },
        },
    },
    "printful_order_watch": {
        "path": "u/admin/printful-order-watch",
        "title": "Printful order watch",
        "category": "Operations",
        "integrations": ["printful", "gmail", "slack"],
        "summary": "Package delayed-fulfillment issues into a customer and team follow-up plan.",
        "description": "Starter automation for fulfillment exception handling.",
        "default_payload": {
            "order_id": "PF-2048",
            "customer_email": "buyer@example.com",
            "status": "delayed",
            "delay_reason": "Inventory transfer in progress",
        },
        "flow": {
            "summary": "Printful order watch",
            "description": "Summarizes order delay context and drafts next steps.",
            "schema": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string"},
                    "customer_email": {"type": "string"},
                    "status": {"type": "string"},
                    "delay_reason": {"type": "string"},
                    "founder_id": {"type": "string"},
                },
            },
            "value": {
                "modules": [
                    {
                        "id": "handle_order_delay",
                        "summary": "Handle delayed fulfillment context",
                        "value": {
                            "type": "rawscript",
                            "language": "bun",
                            "input_transforms": {
                                "order_id": {"type": "javascript", "expr": "flow_input.order_id"},
                                "customer_email": {"type": "javascript", "expr": "flow_input.customer_email"},
                                "status": {"type": "javascript", "expr": "flow_input.status"},
                                "delay_reason": {"type": "javascript", "expr": "flow_input.delay_reason"},
                                "founder_id": {"type": "javascript", "expr": "flow_input.founder_id"},
                            },
                            "content": """export async function main({ order_id, customer_email, status, delay_reason, founder_id }) {\n  return {\n    founder_id,\n    order_id,\n    status,\n    escalation: status === \"delayed\" ? \"ops-review\" : \"monitor\",\n    customer_draft: `We are tracking order ${order_id}. Current status: ${status}. Reason: ${delay_reason}. We will send the next update as soon as we have movement.`,\n    internal_note: `Post ${order_id} in ops channel and confirm replacement or expedite options.`\n  };\n}""",
                        },
                    }
                ]
            },
        },
    },
    "square_daily_flash": {
        "path": "u/admin/square-daily-flash",
        "title": "Square daily flash",
        "category": "Revenue",
        "integrations": ["square", "gmail", "slack"],
        "summary": "Turn daily POS activity into a founder-ready revenue snapshot and alert.",
        "description": "Starter automation for daily sales pulse reporting.",
        "default_payload": {
            "date": "2026-07-03",
            "gross_sales": "$1,840",
            "orders": 29,
            "top_service": "Consultation package",
        },
        "flow": {
            "summary": "Square daily flash",
            "description": "Packages sales totals into a founder flash update.",
            "schema": {
                "type": "object",
                "properties": {
                    "date": {"type": "string"},
                    "gross_sales": {"type": "string"},
                    "orders": {"type": "number"},
                    "top_service": {"type": "string"},
                    "founder_id": {"type": "string"},
                },
            },
            "value": {
                "modules": [
                    {
                        "id": "build_sales_flash",
                        "summary": "Build daily sales flash",
                        "value": {
                            "type": "rawscript",
                            "language": "bun",
                            "input_transforms": {
                                "date": {"type": "javascript", "expr": "flow_input.date"},
                                "gross_sales": {"type": "javascript", "expr": "flow_input.gross_sales"},
                                "orders": {"type": "javascript", "expr": "flow_input.orders"},
                                "top_service": {"type": "javascript", "expr": "flow_input.top_service"},
                                "founder_id": {"type": "javascript", "expr": "flow_input.founder_id"},
                            },
                            "content": """export async function main({ date, gross_sales, orders, top_service, founder_id }) {\n  return {\n    founder_id,\n    date,\n    flash_message: `Daily flash for ${date}: ${gross_sales} across ${orders} orders. Top service: ${top_service}.`,\n    insight: orders >= 20 ? \"Healthy sales day.\" : \"Watch volume and conversion tomorrow.\",\n    status: \"compiled\"\n  };\n}""",
                        },
                    }
                ]
            },
        },
    },
    "yelp_review_rescue": {
        "path": "u/admin/yelp-review-rescue",
        "title": "Yelp review rescue",
        "category": "Reputation",
        "integrations": ["yelp", "gmail", "slack"],
        "summary": "Triage a negative review and produce the response plus internal fix list.",
        "description": "Starter automation for review-response and service-recovery handling.",
        "default_payload": {
            "reviewer_name": "Jordan",
            "rating": 2,
            "review_text": "Service was friendly but the wait was much longer than expected.",
            "location": "Downtown",
        },
        "flow": {
            "summary": "Yelp review rescue",
            "description": "Converts a review into response guidance and action items.",
            "schema": {
                "type": "object",
                "properties": {
                    "reviewer_name": {"type": "string"},
                    "rating": {"type": "number"},
                    "review_text": {"type": "string"},
                    "location": {"type": "string"},
                    "founder_id": {"type": "string"},
                },
            },
            "value": {
                "modules": [
                    {
                        "id": "rescue_review",
                        "summary": "Prepare review recovery response",
                        "value": {
                            "type": "rawscript",
                            "language": "bun",
                            "input_transforms": {
                                "reviewer_name": {"type": "javascript", "expr": "flow_input.reviewer_name"},
                                "rating": {"type": "javascript", "expr": "flow_input.rating"},
                                "review_text": {"type": "javascript", "expr": "flow_input.review_text"},
                                "location": {"type": "javascript", "expr": "flow_input.location"},
                                "founder_id": {"type": "javascript", "expr": "flow_input.founder_id"},
                            },
                            "content": """export async function main({ reviewer_name, rating, review_text, location, founder_id }) {\n  const severity = rating <= 2 ? \"high\" : \"normal\";\n  return {\n    founder_id,\n    severity,\n    public_reply: `Hi ${reviewer_name}, thank you for the candid feedback about your ${location} experience. We are sorry the wait missed the mark and are reviewing this with the team.`,\n    internal_fix_list: [\n      \"Check staffing coverage for the reported time window\",\n      \"Review wait-time expectations in customer messaging\",\n      \"Follow up internally on service recovery options\"\n    ],\n    source_text: review_text\n  };\n}""",
                        },
                    }
                ]
            },
        },
    },
    "social_content_burst": {
        "path": "u/admin/social-content-burst",
        "title": "Social content burst",
        "category": "Content",
        "integrations": ["instagram", "tiktok", "meta_ads"],
        "summary": "Turn one campaign angle into channel-specific social and ad hooks.",
        "description": "Starter automation for shaping one growth idea across social channels.",
        "default_payload": {
            "campaign_angle": "Astra as your founder operating system",
            "audience": "Seed-stage founders",
            "offer": "Book a walkthrough",
        },
        "flow": {
            "summary": "Social content burst",
            "description": "Generates a multi-channel content packet from one campaign angle.",
            "schema": {
                "type": "object",
                "properties": {
                    "campaign_angle": {"type": "string"},
                    "audience": {"type": "string"},
                    "offer": {"type": "string"},
                    "founder_id": {"type": "string"},
                },
            },
            "value": {
                "modules": [
                    {
                        "id": "shape_social_campaign",
                        "summary": "Shape campaign into social hooks",
                        "value": {
                            "type": "rawscript",
                            "language": "bun",
                            "input_transforms": {
                                "campaign_angle": {"type": "javascript", "expr": "flow_input.campaign_angle"},
                                "audience": {"type": "javascript", "expr": "flow_input.audience"},
                                "offer": {"type": "javascript", "expr": "flow_input.offer"},
                                "founder_id": {"type": "javascript", "expr": "flow_input.founder_id"},
                            },
                            "content": """export async function main({ campaign_angle, audience, offer, founder_id }) {\n  return {\n    founder_id,\n    instagram_hook: `${campaign_angle} for ${audience}`,\n    tiktok_hook: `If you are a ${audience}, here is the workflow change to steal`,\n    meta_ads_headline: `Run your company with less founder thrash`,\n    call_to_action: offer\n  };\n}""",
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
