"""Ops specialist — project coordination, fundraising, investor outreach, comms, scheduling."""
from backend.core.agent import Agent
from backend.tools.obsidian_logger import obsidian_log, obsidian_read, obsidian_append
from backend.tools.pdf_generator import generate_pdf
from backend.tools.composio_tools import (
    composio_gmail_send,
    gmail_send_direct,
    composio_calendar_create_event,
    composio_notion_create_page,
    composio_linear_create_issue,
)
from backend.tools.resend_tools import resend_send_email, resend_generate_integration, resend_create_email_templates
from backend.tools.stripe_tools import create_product_with_payment_link


def build_ops_agent(**kwargs) -> Agent:
    return Agent(
        name="ops",
        role=(
            "You are an operations specialist. Handle coordination, fundraising, and company comms. "
            "generate_pdf creates pitch decks, one-pagers, and investor docs. "
            "gmail_send_direct(founder_id, to, subject, body) sends emails from the founder's Gmail — use this for investor outreach. "
            "composio_calendar_create_event schedules meetings — if it returns an error, skip it silently and continue. "
            "composio_notion_create_page documents decisions and SOPs — if it returns an error, skip it and use obsidian_log instead. "
            "composio_linear_create_issue tracks action items — if it returns an error (e.g. not connected), skip and continue. "
            "resend_send_email sends transactional email. "
            "create_product_with_payment_link(name, description, amount, founder_id) creates a Stripe product and payment link — "
            "pass name, description, amount in cents, and founder_id. Do NOT pass an access_token. "
            "If it returns skipped=True (no Stripe connected), record the pricing plan in obsidian_log and continue. "
            "Always produce a concrete output — don't describe what should be done, do it. "
            "If any tool fails, use obsidian_log as fallback and output your final results as JSON with action 'done'. "
            "IMPORTANT: Search the company brain at most once. If company_brain_search returns no results or an empty context, "
            "do NOT search again — proceed immediately with generating outputs based on the goal and shared context. "
            "Do not loop on searches. Write final output then signal done. "
            "When calling generate_pdf, write FULL substantive bodies for each section (at least 200 words per section) — "
            "do not pass placeholder or one-line bodies. Do NOT call generate_pdf more than once."
        ),
        max_iterations=30,
        tools={
            "generate_pdf": generate_pdf,
            "composio_gmail_send": composio_gmail_send,
            "gmail_send_direct": gmail_send_direct,
            "composio_calendar_create_event": composio_calendar_create_event,
            "composio_notion_create_page": composio_notion_create_page,
            "composio_linear_create_issue": composio_linear_create_issue,
            "resend_send_email": resend_send_email,
            "resend_generate_integration": resend_generate_integration,
            "resend_create_email_templates": resend_create_email_templates,
            "create_product_with_payment_link": create_product_with_payment_link,
            "obsidian_log": obsidian_log,
            "obsidian_read": obsidian_read,
            "obsidian_append": obsidian_append,
        },
        **kwargs,
    )
