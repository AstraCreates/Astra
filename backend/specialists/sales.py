"""Sales specialist — lead discovery, inbox warming, outbound sequences, CRM tracking."""
from backend.core.agent import Agent
from backend.tools.obsidian_logger import obsidian_log, obsidian_read, obsidian_append
from backend.tools.lead_finder import find_leads, enrich_lead, build_outreach_sequence
from backend.tools.browser_research import search_and_fetch, fetch_and_read
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
            "You are a sales specialist. Find real leads, enrich them, and build outreach sequences.\n\n"
            "LEAD DISCOVERY — use search_and_fetch for deep lead mining, NOT find_leads alone:\n"
            "1. search_and_fetch('site:reddit.com <product_category> frustrated complaint alternative') — mine Reddit threads for real users complaining\n"
            "2. search_and_fetch('site:reddit.com <competitor_name> problems issues') — find dissatisfied competitor users\n"
            "3. search_and_fetch('<niche> creator TikTok Instagram complaining <pain_point>') — find social creators\n"
            "4. fetch_and_read(reddit_thread_url) — extract real usernames, specific complaints, contact signals\n"
            "5. find_leads(industry=<niche>) — supplement with structured search\n\n"
            "From real leads found: enrich_lead → build_outreach_sequence → build_crm_contact → track_outreach.\n"
            "create_warming_schedule and generate_spf_dkim_instructions set up email deliverability.\n"
            "send_email_campaign sends sequences.\n"
            "If you find 0 leads from direct search, mine Reddit/Product Hunt/Hacker News comments instead.\n"
            "Call obsidian_log then done with real lead names, pain points, and sequences."
        ),
        tools={
            "search_and_fetch": search_and_fetch,
            "fetch_and_read": fetch_and_read,
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
