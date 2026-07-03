"""Agent catalog — static metadata for every specialist agent in Astra.

Each entry describes the agent's identity, what tools it can use, what it
produces, and which agents must run before it (dependency graph).

Dependency graph:
  research  — no deps (runs first)
  web       — depends on research
  legal     — depends on research
  marketing — depends on research
  technical — depends on research
  ops       — depends on all five above
"""
from __future__ import annotations

from typing import Any

AGENT_CATALOG: list[dict[str, Any]] = [
    {
        "id": "research",
        "name": "Research",
        "description": (
            "Market sizing, competitor analysis, TAM/SAM/SOM, customer profile. "
            "Performs deep web, news, patent, and video research to validate markets "
            "and produce structured briefs downstream agents can use directly."
        ),
        "tools": [
            "search_and_fetch",
            "fetch_and_read",
            "research_papers",
            "news_search",
            "patent_search",
            "youtube_research",
            "youtube_get_transcript",
            "tiktok_research",
            "obsidian_log",
            "obsidian_read",
            "obsidian_append",
        ],
        "produces": [
            "market_research_report",
            "competitor_analysis",
            "customer_personas",
            "market_brief",
            "icp_brief",
            "pricing_hypothesis",
        ],
        "depends_on": [],
    },
    {
        "id": "research_competitors",
        "name": "Competitor Intel",
        "description": (
            "Deep competitor intelligence: named competitors, pricing pages, "
            "funding and review mining, and market maps. Produces a competitor "
            "table with strengths, weaknesses, and whitespace opportunities."
        ),
        "tools": [
            "run_research_pipeline",
            "batch_search",
            "fetch_and_read",
            "patent_search",
            "youtube_research",
            "youtube_get_transcript",
            "obsidian_log",
            "obsidian_read",
            "obsidian_append",
        ],
        "produces": [
            "competitor_table",
            "whitespace_opportunities",
            "competitor_analysis",
        ],
        "depends_on": [],
    },
    {
        "id": "research_execution",
        "name": "Execution Strategy",
        "description": (
            "Execution-focused research: GTM strategy, revenue model, recommended "
            "tech stack, unit economics, and a first-90-days plan grounded in "
            "founder case studies and customer evidence."
        ),
        "tools": [
            "run_research_pipeline",
            "batch_search",
            "fetch_and_read",
            "youtube_research",
            "youtube_get_transcript",
            "obsidian_log",
            "obsidian_read",
            "obsidian_append",
        ],
        "produces": [
            "execution_strategy",
            "gtm_strategy",
            "recommended_tech_stack",
        ],
        "depends_on": [],
    },
    {
        "id": "legal",
        "name": "Legal",
        "description": (
            "Privacy policies, terms of service, founder agreements, IP assignment, "
            "entity formation guidance, and patent landscape research. Generates "
            "PDF-ready legal documents and a founder compliance checklist."
        ),
        "tools": [
            "generate_pdf",
            "patent_search",
            "format_legal_document",
            "file_llc_live",
            "obsidian_log",
            "obsidian_read",
            "obsidian_append",
        ],
        "produces": [
            "legal_checklist",
            "policy_outline",
            "founder_agreement",
            "patent_landscape",
        ],
        "depends_on": ["research"],
    },
    {
        "id": "web",
        "name": "Web",
        "description": (
            "Landing page generation, Vercel deployment, conversion-focused copy, "
            "and website architecture. Builds and deploys a public-facing launch "
            "surface based on research and brand direction."
        ),
        "tools": [
            "generate_landing_page_html",
            "vercel_deploy",
            "obsidian_log",
            "obsidian_read",
            "obsidian_append",
        ],
        "produces": [
            "landing_page",
            "website_copy",
            "deployed_url",
        ],
        "depends_on": ["research"],
    },
    {
        "id": "design",
        "name": "Design & Brand",
        "description": (
            "Visual identity, logo and wordmark generation, brand color systems, "
            "wireframes, and a complete design spec. Produces launch-ready brand "
            "and UI direction grounded in research and positioning."
        ),
        "tools": [
            "generate_design_spec",
            "generate_wireframe",
            "generate_logo",
            "generate_brand_board",
            "obsidian_log",
            "obsidian_read",
            "obsidian_append",
        ],
        "produces": [
            "design_spec",
            "brand_direction",
            "logo",
        ],
        "depends_on": ["research"],
    },
    {
        "id": "marketing",
        "name": "Marketing",
        "description": (
            "Go-to-market strategy, social media content (Reels, TikTok, LinkedIn), "
            "Meta ad copy, email campaigns, and growth channel planning. Produces "
            "launch-ready creative assets and a sequenced GTM plan."
        ),
        "tools": [
            "search_and_fetch",
            "generate_reel_package",
            "generate_tiktok_package",
            "generate_meta_ad",
            "generate_ad_image",
            "build_email_html",
            "send_email_campaign",
            "composio_gmail_send",
            "composio_linkedin_post",
            "obsidian_log",
            "obsidian_read",
            "obsidian_append",
        ],
        "produces": [
            "gtm_plan",
            "launch_content",
            "ad_creatives",
            "email_sequence",
            "social_posts",
        ],
        "depends_on": ["research"],
    },
    {
        "id": "technical",
        "name": "Technical",
        "description": (
            "Software architecture, MVP development, GitHub repo creation, Vercel "
            "deployment, Supabase schema generation, Clerk auth integration, and "
            "full-stack implementation planning. Produces an actionable technical "
            "roadmap and working code skeleton."
        ),
        "tools": [
            "github_create_repo",
            "run_mvp_loop",
            "run_claude_in_repo",
            "write_files_to_repo",
            "vercel_deploy_from_github",
            "supabase_generate_schema",
            "supabase_create_project",
            "clerk_generate_integration",
            "posthog_generate_integration",
            "composio_linear_create_issue",
            "composio_notion_create_page",
            "create_product_with_payment_link",
            "obsidian_log",
            "obsidian_read",
            "obsidian_append",
        ],
        "produces": [
            "mvp_roadmap",
            "technical_plan",
            "github_repo",
            "deployed_app",
            "database_schema",
        ],
        "depends_on": ["research"],
    },
    {
        "id": "ops",
        "name": "Operations",
        "description": (
            "Synthesizes every agent lane into a founder operating plan: 30-day "
            "execution calendar, investor memo, weekly cadence, Notion/Linear "
            "project setup, and prioritized next actions. Runs last after all "
            "other agents complete."
        ),
        "tools": [
            "generate_pdf",
            "composio_gmail_send",
            "composio_calendar_create_event",
            "composio_notion_create_page",
            "composio_linear_create_issue",
            "resend_send_email",
            "resend_generate_integration",
            "resend_create_email_templates",
            "create_product_with_payment_link",
            "obsidian_log",
            "obsidian_read",
            "obsidian_append",
        ],
        "produces": [
            "thirty_day_plan",
            "investor_memo",
            "founder_next_actions",
            "operating_cadence",
            "decision_log",
        ],
        "depends_on": ["research", "legal", "web", "marketing", "technical"],
    },
    {
        "id": "research_market",
        "name": "Market Research",
        "description": "Deep TAM/SAM/SOM sizing, ICP profiling, pricing benchmarks, competitor landscape.",
        "tools": ["search_and_fetch", "news_search", "patent_search", "youtube_research", "youtube_get_transcript", "generate_pdf", "obsidian_log", "obsidian_read"],
        "produces": ["tam_sam_som_report", "icp_brief", "pricing_benchmark", "competitor_map"],
        "depends_on": [],
    },
    {
        "id": "research_financial",
        "name": "Financial Research",
        "description": "Unit economics benchmarks, fundraising comps, burn rate analysis, investor readiness scoring.",
        "tools": ["search_and_fetch", "news_search", "generate_pdf", "obsidian_log", "obsidian_read"],
        "produces": ["unit_economics_report", "fundraising_comps", "burn_benchmark_pdf"],
        "depends_on": ["research_market"],
    },
    {
        "id": "research_regulatory",
        "name": "Regulatory Research",
        "description": "GDPR/HIPAA/SOC2 compliance mapping, regulatory risk flags, compliance checklist PDF.",
        "tools": ["search_and_fetch", "patent_search", "generate_pdf", "obsidian_log", "obsidian_read"],
        "produces": ["compliance_checklist", "regulatory_risk_report", "compliance_pdf"],
        "depends_on": ["research_market"],
    },
    {
        "id": "legal_docs",
        "name": "Legal Documents",
        "description": "Privacy policy, terms of service, NDA, IP assignment — full PDFs.",
        "tools": ["format_legal_document", "generate_pdf", "obsidian_log", "obsidian_read"],
        "produces": ["privacy_policy_pdf", "tos_pdf", "nda_pdf", "ip_assignment_pdf"],
        "depends_on": ["research"],
    },
    {
        "id": "legal_entity",
        "name": "Entity Formation",
        "description": "LLC/C-Corp formation guidance, EIN walkthrough, founder agreement, cap table setup.",
        "tools": ["format_legal_document", "generate_pdf", "obsidian_log", "obsidian_read"],
        "produces": ["entity_formation_guide", "founder_agreement_pdf", "cap_table_template"],
        "depends_on": ["research"],
    },
    {
        "id": "legal_ip",
        "name": "IP Strategy",
        "description": "Patent search, trademark clearance, IP assignment, trade secret playbook.",
        "tools": ["patent_search", "format_legal_document", "generate_pdf", "obsidian_log", "obsidian_read"],
        "produces": ["patent_landscape", "trademark_report", "ip_strategy_pdf"],
        "depends_on": ["research"],
    },
    {
        "id": "marketing_content",
        "name": "Content Marketing",
        "description": "Instagram Reels scripts, TikTok packages, Meta ad copy, 30-day content calendar PDF.",
        "tools": ["generate_reel_package", "generate_tiktok_package", "generate_meta_ad", "generate_pdf", "obsidian_log"],
        "produces": ["reels_scripts", "tiktok_package", "meta_ads", "content_calendar_pdf"],
        "depends_on": ["research"],
    },
    {
        "id": "marketing_outreach",
        "name": "Outreach & Lead Gen",
        "description": "Hunter lead discovery, cold email sequences, SendGrid campaign execution.",
        "tools": ["outreach_find_leads", "send_email_campaign", "composio_gmail_send", "obsidian_log"],
        "produces": ["lead_list", "email_sequence", "outreach_report"],
        "depends_on": ["research"],
    },
    {
        "id": "marketing_seo",
        "name": "SEO Strategy",
        "description": "Keyword research, content calendar, blog outlines, on-page SEO checklist PDF.",
        "tools": ["search_and_fetch", "generate_pdf", "obsidian_log"],
        "produces": ["keyword_research", "seo_content_calendar", "blog_outlines_pdf"],
        "depends_on": ["research"],
    },
    {
        "id": "marketing_paid",
        "name": "Paid Advertising",
        "description": "Google/Meta campaign strategy, budget allocation, creative briefs, audience targeting PDF.",
        "tools": ["search_and_fetch", "generate_pdf", "generate_meta_ad", "obsidian_log"],
        "produces": ["paid_strategy_pdf", "campaign_briefs", "budget_plan"],
        "depends_on": ["research"],
    },
    {
        "id": "sales",
        "name": "Sales & Outreach",
        "description": (
            "Lead discovery via web search and Hunter.io enrichment, personalized "
            "multi-step outreach sequences, and CRM contact records. Finds real "
            "prospects matching the ICP and builds ready-to-send email cadences."
        ),
        "tools": [
            "find_leads",
            "enrich_lead",
            "build_outreach_sequence",
            "build_crm_contact",
            "hunter_domain_search",
            "hunter_find_email",
            "obsidian_log",
            "obsidian_read",
            "obsidian_append",
        ],
        "produces": [
            "leads",
            "outreach_sequences",
            "crm_contacts",
        ],
        "depends_on": ["research"],
    },
    {
        "id": "sales_pipeline",
        "name": "Sales Pipeline",
        "description": "CRM stage design, MEDDIC/BANT qualification, objection scripts, sales playbook PDF.",
        "tools": ["generate_pdf", "composio_linear_create_issue", "obsidian_log"],
        "produces": ["sales_playbook_pdf", "crm_stage_map", "objection_scripts"],
        "depends_on": ["research"],
    },
    {
        "id": "sales_enablement",
        "name": "Sales Enablement",
        "description": "Pitch deck, one-pager, case study templates, competitive battlecards PDFs.",
        "tools": ["generate_pdf", "obsidian_log"],
        "produces": ["pitch_deck_pdf", "one_pager_pdf", "battlecards_pdf"],
        "depends_on": ["research"],
    },
    {
        "id": "technical_scaffold",
        "name": "Code Scaffold",
        "description": "GitHub repo creation, Claude Code CLI scaffolding — 20-30 working files committed.",
        "tools": ["github_create_repo", "claude_code_scaffold", "obsidian_log"],
        "produces": ["github_repo", "scaffolded_codebase"],
        "depends_on": ["research"],
    },
    {
        "id": "technical_infra",
        "name": "Infrastructure",
        "description": "CI/CD pipeline, Docker setup, hosting config, monitoring, runbook PDF.",
        "tools": ["github_create_repo", "generate_pdf", "obsidian_log"],
        "produces": ["cicd_config", "docker_compose", "infra_runbook_pdf"],
        "depends_on": ["technical_scaffold"],
    },
    {
        "id": "technical_data",
        "name": "Data Architecture",
        "description": "ER diagram, Postgres schema, analytics event plan, data pipeline spec PDF.",
        "tools": ["generate_pdf", "obsidian_log"],
        "produces": ["er_diagram", "postgres_schema", "analytics_event_plan_pdf"],
        "depends_on": ["research"],
    },
    {
        "id": "finance_model",
        "name": "Financial Model",
        "description": "12-month revenue model, 3 scenarios (base/bull/bear), unit economics, P&L PDF.",
        "tools": ["generate_pdf", "obsidian_log"],
        "produces": ["financial_model_pdf", "unit_economics_sheet", "scenario_analysis"],
        "depends_on": ["research_financial"],
    },
    {
        "id": "finance_fundraise",
        "name": "Fundraising Strategy",
        "description": "Raise recommendation, investor target list, SAFE/priced terms, pitch narrative PDF.",
        "tools": ["search_and_fetch", "generate_pdf", "obsidian_log"],
        "produces": ["raise_recommendation", "investor_list", "fundraising_narrative_pdf"],
        "depends_on": ["finance_model"],
    },
]

# Fast lookup by id
_CATALOG_BY_ID: dict[str, dict[str, Any]] = {a["id"]: a for a in AGENT_CATALOG}

# Valid agent IDs for validation
VALID_AGENT_IDS: frozenset[str] = frozenset(_CATALOG_BY_ID)


def get_agent_catalog() -> list[dict[str, Any]]:
    """Return the full agent catalog."""
    return AGENT_CATALOG


def get_agent_entry(agent_id: str) -> dict[str, Any] | None:
    """Return a single agent catalog entry or None."""
    return _CATALOG_BY_ID.get(agent_id)
