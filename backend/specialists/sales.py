"""Sales specialist — lead discovery, inbox warming, outbound sequences, CRM tracking."""
from backend.core.agent import Agent
from backend.tools.obsidian_logger import obsidian_log, obsidian_read, obsidian_append
from backend.tools.lead_finder import find_leads, enrich_lead, build_outreach_sequence
from backend.tools.inbox_warmer import (
    create_warming_schedule,
    generate_spf_dkim_instructions,
    build_crm_contact,
    track_outreach,
)
from backend.tools.email_campaign import send_email_campaign


def build_sales_agent(**kwargs) -> Agent:
    return Agent(
        name="sales",
        role=(
            "You are the sales specialist. Your agent name is 'sales'. "
            "Your prior session notes are pre-loaded in prior_vault_notes in SHARED CONTEXT — read them before acting. "
            "You handle: lead discovery (find_leads), lead enrichment (enrich_lead), "
            "outreach sequence generation (build_outreach_sequence), inbox warming setup (create_warming_schedule), "
            "DNS/deliverability config (generate_spf_dkim_instructions), CRM contact creation (build_crm_contact), "
            "outreach tracking (track_outreach), and sending individual emails (send_email_campaign). "
            "Workflow: (1) Use find_leads to discover prospects matching the ICP. "
            "If the goal is to reach businesses WITHOUT websites, pass no_website=True — this searches Yelp/Google Maps listings instead of LinkedIn. "
            "Never target LinkedIn, Twitter, Facebook, or other social platforms as leads. "
            "(2) Enrich top 3-5 leads with enrich_lead. "
            "(3) Build outreach sequences with build_outreach_sequence for each enriched lead. "
            "(4) Call generate_spf_dkim_instructions and create_warming_schedule for email deliverability. "
            "(5) Call obsidian_log(agent='sales', session_id=<from context>, summary=..., output=...) then done. "
            "Never call done without real lead and sequence data. Enrich multiple leads and build full sequences."
        ),
        tools={
            "find_leads": find_leads,
            "enrich_lead": enrich_lead,
            "build_outreach_sequence": build_outreach_sequence,
            "create_warming_schedule": create_warming_schedule,
            "generate_spf_dkim_instructions": generate_spf_dkim_instructions,
            "build_crm_contact": build_crm_contact,
            "track_outreach": track_outreach,
            "send_email_campaign": send_email_campaign,
            "obsidian_log": obsidian_log,
            "obsidian_read": obsidian_read,
            "obsidian_append": obsidian_append,
        },
        **kwargs,
    )
