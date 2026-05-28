"""Ops specialist — project coordination, fundraising, investor outreach, comms, scheduling."""
from backend.core.agent import Agent
from backend.tools.obsidian_logger import obsidian_log, obsidian_read, obsidian_append
from backend.tools.pdf_generator import generate_pdf
from backend.tools.composio_tools import (
    composio_gmail_send,
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
            "composio_gmail_send sends investor outreach emails. "
            "composio_calendar_create_event schedules meetings. "
            "composio_notion_create_page documents decisions and SOPs — if it returns an error, skip it and use obsidian_log instead. "
            "composio_linear_create_issue tracks action items — if it returns an error (e.g. not connected), skip and continue. "
            "resend_send_email sends transactional email. "
            "create_product_with_payment_link creates a Stripe product, price, and shareable payment link. "
            "Use create_product_with_payment_link when the research findings suggest a pricing model — "
            "pass the founder's stripe access_token from shared context, product name, description, amount in cents, currency, and interval (month/year/empty for one-time). "
            "Always produce a concrete output — don't describe what should be done, do it. "
            "If any tool fails, use obsidian_log as fallback and still call done with your results. "
            "Call obsidian_log then done."
        ),
        tools={
            "generate_pdf": generate_pdf,
            "composio_gmail_send": composio_gmail_send,
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
