"""Custom stack package builder.

Allows founders to hand-pick a subset of the 6 specialist agents and receive
a deployable package — manifest, tasks, approval queue, and start payload —
scoped only to those agents.
"""
from __future__ import annotations

from typing import Any

from backend.stacks.catalog import VALID_AGENT_IDS, get_agent_entry
from backend.stacks.templates import (
    AgentStackTemplate,
    StackApprovalGate,
    StackArtifact,
    StackConnectorRequirement,
    StackTaskTemplate,
)

# ── Per-agent task templates (trimmed from IDEA_TO_REVENUE_STACK) ─────────────

_AGENT_TASKS: dict[str, StackTaskTemplate] = {
    "research": StackTaskTemplate(
        id="c_research",
        agent="research",
        title="Market and customer research",
        instruction=(
            "Validate the market, target customer, pain severity, buying trigger, "
            "category, pricing references, and early wedge. Produce specific research "
            "that downstream agents can use directly."
        ),
        depends_on=[],
        artifacts=["market_brief", "icp_brief", "pricing_hypothesis"],
    ),
    "legal": StackTaskTemplate(
        id="c_legal",
        agent="legal",
        title="Legal starter kit",
        instruction=(
            "Draft the legal and compliance starter kit appropriate for this outcome: "
            "privacy policy outline, terms outline, risk notes, entity considerations, "
            "and founder checklist. Do not file or publish anything without approval."
        ),
        depends_on=["c_research"],
        artifacts=["legal_checklist", "policy_outline"],
    ),
    "web": StackTaskTemplate(
        id="c_web",
        agent="web",
        title="Launch surface",
        instruction=(
            "Create and deploy a conversion-focused landing page based on the research. "
            "Include hero copy, value props, social proof framing, "
            "waitlist or lead capture direction, and deployment handoff."
        ),
        depends_on=["c_research"],
        artifacts=["landing_page", "website_copy"],
    ),
    "marketing": StackTaskTemplate(
        id="c_marketing",
        agent="marketing",
        title="Go-to-market motion",
        instruction=(
            "Create the launch marketing motion: positioning angle, first channels, "
            "content ideas, launch sequence, landing page CTA strategy, and messaging "
            "tests tied to the target customer."
        ),
        depends_on=["c_research"],
        artifacts=["gtm_plan", "launch_content"],
    ),
    "technical": StackTaskTemplate(
        id="c_technical",
        agent="technical",
        title="Product roadmap",
        instruction=(
            "Define the MVP product architecture and build path. Produce a practical "
            "technical roadmap with core entities, auth/data needs, repo structure, and "
            "first usable product scope."
        ),
        depends_on=["c_research"],
        artifacts=["mvp_roadmap", "technical_plan"],
    ),
    "ops": StackTaskTemplate(
        id="c_ops",
        agent="ops",
        title="Execution operating plan",
        instruction=(
            "Synthesize every completed lane into a founder operating plan: 30-day "
            "execution plan, weekly milestones, priorities, decision log, investor memo "
            "outline, and next actions for the founder."
        ),
        depends_on=["c_research", "c_legal", "c_web", "c_marketing", "c_technical"],
        artifacts=["thirty_day_plan", "investor_memo", "founder_next_actions"],
    ),
    "design": StackTaskTemplate(
        id="c_design",
        agent="design",
        title="Brand and visual identity",
        instruction=(
            "Generate a complete visual identity system: logo, wordmark, brand color "
            "palette, typography, and UI direction. Produce wireframes for the core "
            "screens and a design spec downstream agents (web, technical) can use directly."
        ),
        depends_on=["c_research"],
        artifacts=["design_spec", "brand_direction", "logo"],
    ),
    "sales": StackTaskTemplate(
        id="c_sales",
        agent="sales",
        title="Lead list and outreach sequences",
        instruction=(
            "Find real prospects matching the ICP using web search and Hunter.io. "
            "Build personalized multi-step outreach sequences (3–5 touches) and CRM "
            "contact records. Do not send any emails without founder approval."
        ),
        depends_on=["c_research"],
        artifacts=["leads", "outreach_sequences", "crm_contacts"],
    ),
    "research_competitors": StackTaskTemplate(
        id="c_research_competitors",
        agent="research_competitors",
        title="Competitor intelligence",
        instruction=(
            "Research every named competitor: pricing pages, feature sets, funding "
            "history, G2/Capterra reviews, and market positioning. Produce a structured "
            "competitor table with strengths, weaknesses, and whitespace opportunities."
        ),
        depends_on=[],
        artifacts=["competitor_table", "whitespace_opportunities"],
    ),
    "research_execution": StackTaskTemplate(
        id="c_research_execution",
        agent="research_execution",
        title="Execution strategy research",
        instruction=(
            "Research GTM playbooks, revenue models, and tech stacks used by comparable "
            "companies at this stage. Produce a first-90-days execution strategy grounded "
            "in founder case studies and customer evidence."
        ),
        depends_on=[],
        artifacts=["execution_strategy", "gtm_strategy", "recommended_tech_stack"],
    ),
    "research_market": StackTaskTemplate(
        id="c_research_market",
        agent="research_market",
        title="Market sizing and ICP profiling",
        instruction=(
            "Deep TAM/SAM/SOM sizing with sourced numbers. ICP profiling with demographics, "
            "psychographics, buying triggers, and objections. Pricing benchmarks and a "
            "structured competitor landscape overview."
        ),
        depends_on=[],
        artifacts=["tam_sam_som_report", "icp_brief", "pricing_benchmark"],
    ),
    "research_financial": StackTaskTemplate(
        id="c_research_financial",
        agent="research_financial",
        title="Financial benchmarks and fundraising comps",
        instruction=(
            "Research unit economics benchmarks for this business model, fundraising "
            "comparable rounds, burn rate norms, and investor readiness signals. Produce "
            "a sourced financial benchmarks report."
        ),
        depends_on=["c_research_market"],
        artifacts=["unit_economics_report", "fundraising_comps"],
    ),
    "research_regulatory": StackTaskTemplate(
        id="c_research_regulatory",
        agent="research_regulatory",
        title="Regulatory and compliance research",
        instruction=(
            "Map applicable regulations (GDPR, HIPAA, SOC2, FTC, sector-specific). "
            "Flag the top regulatory risks, required disclosures, and compliance actions. "
            "Produce a compliance checklist PDF and a risk summary."
        ),
        depends_on=["c_research_market"],
        artifacts=["compliance_checklist", "regulatory_risk_report"],
    ),
    "legal_docs": StackTaskTemplate(
        id="c_legal_docs",
        agent="legal_docs",
        title="Legal documents",
        instruction=(
            "Draft full PDF-ready legal documents: privacy policy, terms of service, NDA, "
            "and IP assignment agreement. Tailor each to the company type and jurisdiction. "
            "Do not publish any document without founder review."
        ),
        depends_on=["c_research"],
        artifacts=["privacy_policy_pdf", "tos_pdf", "nda_pdf"],
    ),
    "legal_entity": StackTaskTemplate(
        id="c_legal_entity",
        agent="legal_entity",
        title="Entity formation guide",
        instruction=(
            "Produce an entity formation guide: LLC vs C-Corp analysis for this company's "
            "goals, EIN walkthrough, founder agreement template, and cap table setup. "
            "Do not file any documents without explicit founder approval."
        ),
        depends_on=["c_research"],
        artifacts=["entity_formation_guide", "founder_agreement_pdf"],
    ),
    "legal_ip": StackTaskTemplate(
        id="c_legal_ip",
        agent="legal_ip",
        title="IP strategy",
        instruction=(
            "Run a patent landscape search, trademark clearance check for the product "
            "name and logo, draft an IP assignment agreement, and produce a trade secret "
            "protection playbook."
        ),
        depends_on=["c_research"],
        artifacts=["patent_landscape", "trademark_report"],
    ),
    "marketing_content": StackTaskTemplate(
        id="c_marketing_content",
        agent="marketing_content",
        title="Content marketing assets",
        instruction=(
            "Produce a 30-day content calendar with Instagram Reels scripts, TikTok "
            "packages, Meta ad copy, and LinkedIn posts. Each piece must be tied to "
            "the positioning and ICP from research."
        ),
        depends_on=["c_research"],
        artifacts=["reels_scripts", "tiktok_package", "meta_ads"],
    ),
    "marketing_outreach": StackTaskTemplate(
        id="c_marketing_outreach",
        agent="marketing_outreach",
        title="Outreach and lead generation",
        instruction=(
            "Use Hunter.io to find leads matching the ICP. Write 3-touch cold email "
            "sequences for each lead segment. Prepare the SendGrid campaign setup. "
            "Do not send any email without founder approval."
        ),
        depends_on=["c_research"],
        artifacts=["lead_list", "email_sequence", "outreach_report"],
    ),
    "marketing_seo": StackTaskTemplate(
        id="c_marketing_seo",
        agent="marketing_seo",
        title="SEO strategy",
        instruction=(
            "Research target keywords, produce a 90-day content calendar with blog "
            "outlines, and generate an on-page SEO checklist. Priority: high-intent "
            "keywords the ICP actually searches."
        ),
        depends_on=["c_research"],
        artifacts=["keyword_research", "seo_content_calendar"],
    ),
    "marketing_paid": StackTaskTemplate(
        id="c_marketing_paid",
        agent="marketing_paid",
        title="Paid advertising strategy",
        instruction=(
            "Produce a Google/Meta paid advertising strategy: audience targeting, budget "
            "allocation, creative briefs, and campaign structure. Include a test-and-learn "
            "framework. Do not activate spend without founder approval."
        ),
        depends_on=["c_research"],
        artifacts=["paid_strategy_pdf", "campaign_briefs"],
    ),
    "sales_pipeline": StackTaskTemplate(
        id="c_sales_pipeline",
        agent="sales_pipeline",
        title="Sales pipeline design",
        instruction=(
            "Design the CRM pipeline stages, MEDDIC/BANT qualification criteria, "
            "objection handling scripts, and a sales playbook PDF. Produce a stage map "
            "ready to import into HubSpot or Notion."
        ),
        depends_on=["c_research"],
        artifacts=["sales_playbook_pdf", "crm_stage_map"],
    ),
    "sales_enablement": StackTaskTemplate(
        id="c_sales_enablement",
        agent="sales_enablement",
        title="Sales enablement kit",
        instruction=(
            "Produce the full sales enablement kit: pitch deck, one-pager, case study "
            "template, and competitive battlecards. All assets must be grounded in the "
            "ICP and competitor research."
        ),
        depends_on=["c_research"],
        artifacts=["pitch_deck_pdf", "one_pager_pdf", "battlecards_pdf"],
    ),
    "technical_scaffold": StackTaskTemplate(
        id="c_technical_scaffold",
        agent="technical_scaffold",
        title="Code scaffold",
        instruction=(
            "Create a GitHub repo and scaffold the codebase using Claude Code CLI: "
            "20-30 working files covering core entities, auth, data layer, and API routes. "
            "Commit and push. Request deploy approval before any production deployment."
        ),
        depends_on=["c_research"],
        artifacts=["github_repo", "scaffolded_codebase"],
    ),
    "technical_infra": StackTaskTemplate(
        id="c_technical_infra",
        agent="technical_infra",
        title="Infrastructure setup",
        instruction=(
            "Set up CI/CD pipeline (GitHub Actions), Docker compose, hosting config, "
            "monitoring setup, and produce a runbook PDF. Depends on the scaffolded "
            "codebase being committed."
        ),
        depends_on=["c_technical_scaffold"],
        artifacts=["cicd_config", "docker_compose"],
    ),
    "technical_data": StackTaskTemplate(
        id="c_technical_data",
        agent="technical_data",
        title="Data architecture",
        instruction=(
            "Produce an ER diagram, full Postgres schema with migrations, analytics "
            "event plan, and data pipeline spec PDF. Schema must reflect the ICP and "
            "core product entities from research."
        ),
        depends_on=["c_research"],
        artifacts=["er_diagram", "postgres_schema"],
    ),
    "finance_model": StackTaskTemplate(
        id="c_finance_model",
        agent="finance_model",
        title="Financial model",
        instruction=(
            "Build a 12-month revenue model with 3 scenarios (base/bull/bear), unit "
            "economics breakdown, and a P&L PDF. Ground assumptions in the financial "
            "benchmarks research."
        ),
        depends_on=["c_research_financial"],
        artifacts=["financial_model_pdf", "unit_economics_sheet"],
    ),
    "finance_fundraise": StackTaskTemplate(
        id="c_finance_fundraise",
        agent="finance_fundraise",
        title="Fundraising strategy",
        instruction=(
            "Produce a raise recommendation (amount, instrument, timing), a targeted "
            "investor list with thesis match, SAFE/priced round term guidance, and a "
            "pitch narrative PDF. Do not contact any investor without founder approval."
        ),
        depends_on=["c_finance_model"],
        artifacts=["raise_recommendation", "investor_list"],
    ),
}

# Artifacts that each agent can produce (used to populate the artifact list)
_AGENT_ARTIFACTS: dict[str, list[StackArtifact]] = {
    "research": [
        StackArtifact("market_brief", "Market brief", "research", "Market size, category, trends, and validation signals."),
        StackArtifact("icp_brief", "ICP brief", "research", "Target customer, pain, trigger, objections, and buying process."),
        StackArtifact("pricing_hypothesis", "Pricing hypothesis", "research", "Initial packaging and pricing rationale."),
    ],
    "legal": [
        StackArtifact("legal_checklist", "Legal checklist", "legal", "Founder legal risk and setup checklist."),
        StackArtifact("policy_outline", "Policy outline", "legal", "Privacy and terms outline for launch."),
    ],
    "web": [
        StackArtifact("landing_page", "Landing page", "web", "Public launch surface or deployable page output."),
        StackArtifact("website_copy", "Website copy", "web", "Hero, sections, CTA, FAQ, and conversion copy."),
    ],
    "marketing": [
        StackArtifact("gtm_plan", "GTM plan", "marketing", "Launch channels, messaging tests, and initial campaign plan."),
        StackArtifact("launch_content", "Launch content", "marketing", "Social, email, and community copy drafts."),
    ],
    "technical": [
        StackArtifact("mvp_roadmap", "MVP roadmap", "technical", "Product scope, user stories, and build sequence."),
        StackArtifact("technical_plan", "Technical plan", "technical", "Architecture, data model, repo, and deployment plan."),
    ],
    "ops": [
        StackArtifact("thirty_day_plan", "30-day plan", "ops", "Week-by-week operating plan."),
        StackArtifact("investor_memo", "Investor memo", "ops", "Concise investor/fundraising narrative."),
        StackArtifact("founder_next_actions", "Founder next actions", "ops", "Prioritized next actions and approvals."),
    ],
    "design": [
        StackArtifact("design_spec", "Design spec", "design", "Full visual identity: colors, type, spacing, component direction."),
        StackArtifact("brand_direction", "Brand direction", "design", "Logo, wordmark, and brand board."),
        StackArtifact("logo", "Logo", "design", "Primary logo and wordmark file."),
    ],
    "sales": [
        StackArtifact("leads", "Lead list", "sales", "Qualified prospects matching the ICP with contact details."),
        StackArtifact("outreach_sequences", "Outreach sequences", "sales", "Personalized multi-touch email cadences per segment."),
        StackArtifact("crm_contacts", "CRM contacts", "sales", "Contact records ready to import into CRM."),
    ],
    "research_competitors": [
        StackArtifact("competitor_table", "Competitor table", "research_competitors", "Named competitors with pricing, features, and weaknesses."),
        StackArtifact("whitespace_opportunities", "Whitespace opportunities", "research_competitors", "Market gaps and positioning angles not covered by competitors."),
    ],
    "research_execution": [
        StackArtifact("execution_strategy", "Execution strategy", "research_execution", "First-90-days plan grounded in comparable founder case studies."),
        StackArtifact("gtm_strategy", "GTM strategy", "research_execution", "Go-to-market channels, sequencing, and early traction playbook."),
        StackArtifact("recommended_tech_stack", "Recommended tech stack", "research_execution", "Tech stack recommendation with rationale."),
    ],
    "research_market": [
        StackArtifact("tam_sam_som_report", "TAM/SAM/SOM report", "research_market", "Sourced market sizing with methodology."),
        StackArtifact("icp_brief", "ICP brief", "research_market", "Ideal customer profile with demographics, triggers, and objections."),
        StackArtifact("pricing_benchmark", "Pricing benchmark", "research_market", "Comparable pricing models and packaging options."),
    ],
    "research_financial": [
        StackArtifact("unit_economics_report", "Unit economics report", "research_financial", "Benchmarks for CAC, LTV, payback period, and margins."),
        StackArtifact("fundraising_comps", "Fundraising comps", "research_financial", "Comparable fundraising rounds and investor thesis signals."),
    ],
    "research_regulatory": [
        StackArtifact("compliance_checklist", "Compliance checklist", "research_regulatory", "Required compliance actions before launch."),
        StackArtifact("regulatory_risk_report", "Regulatory risk report", "research_regulatory", "Top regulatory risks and mitigation steps."),
    ],
    "legal_docs": [
        StackArtifact("privacy_policy_pdf", "Privacy policy", "legal_docs", "PDF-ready privacy policy tailored to this company."),
        StackArtifact("tos_pdf", "Terms of service", "legal_docs", "PDF-ready terms of service."),
        StackArtifact("nda_pdf", "NDA", "legal_docs", "Non-disclosure agreement template."),
    ],
    "legal_entity": [
        StackArtifact("entity_formation_guide", "Entity formation guide", "legal_entity", "LLC vs C-Corp analysis and formation walkthrough."),
        StackArtifact("founder_agreement_pdf", "Founder agreement", "legal_entity", "Founder equity and vesting agreement template."),
    ],
    "legal_ip": [
        StackArtifact("patent_landscape", "Patent landscape", "legal_ip", "Existing patents in the space and freedom-to-operate notes."),
        StackArtifact("trademark_report", "Trademark report", "legal_ip", "Trademark clearance check for name and logo."),
    ],
    "marketing_content": [
        StackArtifact("reels_scripts", "Reels scripts", "marketing_content", "Instagram Reels scripts with hooks, B-roll notes, and CTAs."),
        StackArtifact("tiktok_package", "TikTok package", "marketing_content", "TikTok video concepts and scripts."),
        StackArtifact("meta_ads", "Meta ad copy", "marketing_content", "Facebook/Instagram ad headlines, bodies, and CTAs."),
    ],
    "marketing_outreach": [
        StackArtifact("lead_list", "Lead list", "marketing_outreach", "Qualified contacts discovered via Hunter.io."),
        StackArtifact("email_sequence", "Email sequence", "marketing_outreach", "3-touch cold email cadence per ICP segment."),
        StackArtifact("outreach_report", "Outreach report", "marketing_outreach", "Sequence performance plan and send schedule."),
    ],
    "marketing_seo": [
        StackArtifact("keyword_research", "Keyword research", "marketing_seo", "Target keywords with volume, difficulty, and intent mapping."),
        StackArtifact("seo_content_calendar", "SEO content calendar", "marketing_seo", "90-day content calendar with blog outlines."),
    ],
    "marketing_paid": [
        StackArtifact("paid_strategy_pdf", "Paid strategy", "marketing_paid", "Google/Meta campaign structure, audiences, and budget plan."),
        StackArtifact("campaign_briefs", "Campaign briefs", "marketing_paid", "Creative briefs for each ad set."),
    ],
    "sales_pipeline": [
        StackArtifact("sales_playbook_pdf", "Sales playbook", "sales_pipeline", "CRM stages, qualification criteria, and objection scripts."),
        StackArtifact("crm_stage_map", "CRM stage map", "sales_pipeline", "Pipeline stages ready to import into HubSpot or Notion."),
    ],
    "sales_enablement": [
        StackArtifact("pitch_deck_pdf", "Pitch deck", "sales_enablement", "Investor/sales pitch deck PDF."),
        StackArtifact("one_pager_pdf", "One-pager", "sales_enablement", "Single-page product/company overview."),
        StackArtifact("battlecards_pdf", "Battlecards", "sales_enablement", "Competitive battlecards for sales conversations."),
    ],
    "technical_scaffold": [
        StackArtifact("github_repo", "GitHub repo", "technical_scaffold", "Committed repository with scaffolded codebase."),
        StackArtifact("scaffolded_codebase", "Scaffolded codebase", "technical_scaffold", "20-30 working files covering core app structure."),
    ],
    "technical_infra": [
        StackArtifact("cicd_config", "CI/CD config", "technical_infra", "GitHub Actions workflow files."),
        StackArtifact("docker_compose", "Docker compose", "technical_infra", "Docker setup for local and production environments."),
    ],
    "technical_data": [
        StackArtifact("er_diagram", "ER diagram", "technical_data", "Entity-relationship diagram for core data model."),
        StackArtifact("postgres_schema", "Postgres schema", "technical_data", "Full schema with migrations."),
    ],
    "finance_model": [
        StackArtifact("financial_model_pdf", "Financial model", "finance_model", "12-month P&L with 3 scenarios."),
        StackArtifact("unit_economics_sheet", "Unit economics", "finance_model", "CAC, LTV, payback period, and margin breakdown."),
    ],
    "finance_fundraise": [
        StackArtifact("raise_recommendation", "Raise recommendation", "finance_fundraise", "Recommended raise amount, instrument, and timing."),
        StackArtifact("investor_list", "Investor list", "finance_fundraise", "Targeted investors with thesis match and contact notes."),
    ],
}

# Approval gates that apply when a given agent is selected
_AGENT_APPROVAL_GATES: dict[str, StackApprovalGate] = {
    "web": StackApprovalGate(
        key="public_deploy",
        title="Publish public launch surface",
        trigger="web agent has a deployable landing page",
        required_before="public website publication or production domain changes",
        reason="Public-facing brand and claims need founder approval.",
    ),
    "marketing": StackApprovalGate(
        key="outbound_send",
        title="Send outbound email",
        trigger="marketing creates an email sequence",
        required_before="sending email to prospects or importing contacts into a campaign",
        reason="Outbound can affect reputation, deliverability, and legal compliance.",
    ),
    "legal": StackApprovalGate(
        key="legal_publish",
        title="Use legal documents publicly",
        trigger="legal agent drafts policy, terms, or entity guidance",
        required_before="publishing policies, filing entity documents, or paying filing fees",
        reason="Legal and financial actions must stay founder-controlled.",
    ),
    "legal_docs": StackApprovalGate(
        key="legal_publish",
        title="Use legal documents publicly",
        trigger="legal_docs agent produces privacy policy, terms, or NDA",
        required_before="publishing any legal document or sharing with counterparties",
        reason="Legal documents carry liability and must be founder-reviewed.",
    ),
    "legal_entity": StackApprovalGate(
        key="entity_file",
        title="File or act on entity guidance",
        trigger="legal_entity agent produces formation guide or founder agreement",
        required_before="filing with any state, paying filing fees, or signing founder agreements",
        reason="Entity and equity decisions are irreversible without founder approval.",
    ),
    "legal_ip": StackApprovalGate(
        key="legal_publish",
        title="Use IP strategy documents publicly",
        trigger="legal_ip agent produces patent landscape or trademark report",
        required_before="filing trademark, patent, or publishing IP assignment",
        reason="IP filings are costly and irreversible without founder review.",
    ),
    "sales": StackApprovalGate(
        key="outbound_send",
        title="Send outbound to prospects",
        trigger="sales agent builds outreach sequences",
        required_before="sending any email or LinkedIn message to prospects",
        reason="Outbound affects reputation and must be founder-approved.",
    ),
    "marketing_outreach": StackApprovalGate(
        key="outbound_send",
        title="Send outbound email campaign",
        trigger="marketing_outreach agent builds email sequences",
        required_before="sending cold email or importing contacts into a campaign tool",
        reason="Outbound can affect deliverability and legal compliance.",
    ),
    "marketing_paid": StackApprovalGate(
        key="paid_campaign",
        title="Activate paid ad spend",
        trigger="marketing_paid agent produces campaign strategy and briefs",
        required_before="activating any paid campaign or committing ad budget",
        reason="Paid spend requires founder approval before money is spent.",
    ),
    "technical_scaffold": StackApprovalGate(
        key="public_deploy",
        title="Deploy scaffolded code to production",
        trigger="technical_scaffold agent commits codebase to GitHub",
        required_before="deploying to a production or public-facing URL",
        reason="Public deployments represent the brand and need founder sign-off.",
    ),
    "finance_fundraise": StackApprovalGate(
        key="investor_outreach",
        title="Contact investors",
        trigger="finance_fundraise agent produces investor list and pitch narrative",
        required_before="reaching out to any investor on the target list",
        reason="Investor relationships are founder-owned and require explicit approval.",
    ),
}

# Connector requirements per agent
_AGENT_CONNECTORS: dict[str, list[StackConnectorRequirement]] = {
    "research": [],
    "legal": [
        StackConnectorRequirement("google_drive", "Google Drive", "knowledge", "Store legal and planning artifacts.", False),
    ],
    "web": [
        StackConnectorRequirement("github", "GitHub", "code", "Create or update the product repository.", True),
        StackConnectorRequirement("vercel", "Vercel", "deployment", "Deploy or prepare the launch surface.", True),
    ],
    "marketing": [
        StackConnectorRequirement("gmail", "Gmail", "outreach", "Draft founder-approved outbound and launch emails.", False),
    ],
    "technical": [
        StackConnectorRequirement("github", "GitHub", "code", "Create or update the product repository and preserve implementation handoff.", True),
        StackConnectorRequirement("vercel", "Vercel", "deployment", "Deploy or prepare the app preview.", True),
        StackConnectorRequirement("supabase", "Supabase", "data", "Prepare the database/auth foundation for the MVP.", False),
    ],
    "ops": [
        StackConnectorRequirement("google_drive", "Google Drive", "knowledge", "Store investor, legal, and planning artifacts.", False),
        StackConnectorRequirement("obsidian", "Obsidian", "company_brain", "Persist research, decisions, and execution context.", False),
    ],
    "design": [],
    "sales": [
        StackConnectorRequirement("gmail", "Gmail", "outreach", "Send founder-approved outbound sequences.", False),
    ],
    "research_competitors": [],
    "research_execution": [],
    "research_market": [],
    "research_financial": [],
    "research_regulatory": [],
    "legal_docs": [
        StackConnectorRequirement("google_drive", "Google Drive", "knowledge", "Store legal document PDFs.", False),
    ],
    "legal_entity": [
        StackConnectorRequirement("google_drive", "Google Drive", "knowledge", "Store entity formation guide and founder agreements.", False),
    ],
    "legal_ip": [
        StackConnectorRequirement("google_drive", "Google Drive", "knowledge", "Store IP strategy and patent landscape reports.", False),
    ],
    "marketing_content": [],
    "marketing_outreach": [
        StackConnectorRequirement("gmail", "Gmail", "outreach", "Execute cold email sequences after founder approval.", False),
    ],
    "marketing_seo": [],
    "marketing_paid": [],
    "sales_pipeline": [
        StackConnectorRequirement("notion", "Notion", "knowledge", "Import CRM stage map and sales playbook.", False),
    ],
    "sales_enablement": [
        StackConnectorRequirement("google_drive", "Google Drive", "knowledge", "Store pitch deck, one-pager, and battlecard PDFs.", False),
    ],
    "technical_scaffold": [
        StackConnectorRequirement("github", "GitHub", "code", "Create the repo and commit scaffolded codebase.", True),
        StackConnectorRequirement("vercel", "Vercel", "deployment", "Deploy preview after founder approval.", False),
    ],
    "technical_infra": [
        StackConnectorRequirement("github", "GitHub", "code", "Commit CI/CD config and Docker files to the repo.", True),
    ],
    "technical_data": [
        StackConnectorRequirement("supabase", "Supabase", "data", "Apply Postgres schema to the project database.", False),
    ],
    "finance_model": [
        StackConnectorRequirement("google_drive", "Google Drive", "knowledge", "Store financial model PDF and unit economics sheet.", False),
    ],
    "finance_fundraise": [
        StackConnectorRequirement("google_drive", "Google Drive", "knowledge", "Store fundraising narrative and investor list.", False),
    ],
}


def _prune_depends_on(task: StackTaskTemplate, selected_task_ids: set[str]) -> list[str]:
    """Remove dependency IDs that aren't in the selected set."""
    return [dep for dep in task.depends_on if dep in selected_task_ids]


def build_custom_stack_package(
    *,
    agents: list[str],
    instruction: str,
    founder_id: str = "",
    company_name: str | None = None,
) -> dict[str, Any]:
    """Build a deployable stack package for an arbitrary subset of agents."""
    # Validate agent IDs
    unknown = [a for a in agents if a not in VALID_AGENT_IDS]
    if unknown:
        return {
            "ok": False,
            "error": f"Unknown agent(s): {unknown}. Valid agents: {sorted(VALID_AGENT_IDS)}",
        }
    if not agents:
        return {"ok": False, "error": "agents list must contain at least one agent."}

    selected = list(dict.fromkeys(agents))  # deduplicate, preserve order

    # Build task list — prune deps to only selected tasks
    selected_task_ids = {_AGENT_TASKS[a].id for a in selected if a in _AGENT_TASKS}
    tasks: list[dict[str, Any]] = []
    for agent_id in selected:
        template = _AGENT_TASKS.get(agent_id)
        if not template:
            continue
        pruned_deps = _prune_depends_on(template, selected_task_ids)
        tasks.append({
            "id": template.id,
            "agent": template.agent,
            "instruction": (
                f"{template.instruction}\n\n"
                f"Founder goal: {instruction}\n\n"
                f"Stack: custom ({', '.join(selected)}). "
                f"Company: {company_name or 'unknown'}."
            ),
            "depends_on": pruned_deps,
            "stack_task_title": template.title,
            "expected_artifacts": list(template.artifacts),
        })

    # Build artifact list
    artifacts: list[dict[str, Any]] = []
    for agent_id in selected:
        for artifact in _AGENT_ARTIFACTS.get(agent_id, []):
            artifacts.append({
                "key": artifact.key,
                "title": artifact.title,
                "owner_agent": artifact.owner_agent,
                "description": artifact.description,
                "required": artifact.required,
            })

    # Build approval queue — only gates relevant to selected agents
    approval_queue: list[dict[str, Any]] = []
    seen_gate_keys: set[str] = set()
    for agent_id in selected:
        gate = _AGENT_APPROVAL_GATES.get(agent_id)
        if gate and gate.key not in seen_gate_keys:
            seen_gate_keys.add(gate.key)
            approval_queue.append({
                "key": gate.key,
                "title": gate.title,
                "trigger": gate.trigger,
                "required_before": gate.required_before,
                "reason": gate.reason,
                "status": "armed",
                "triggered_by": None,
            })

    # Build connector list (deduplicated by key, required wins)
    connectors_by_key: dict[str, dict[str, Any]] = {}
    for agent_id in selected:
        for req in _AGENT_CONNECTORS.get(agent_id, []):
            existing = connectors_by_key.get(req.key)
            if existing is None or (req.required and not existing["required"]):
                connectors_by_key[req.key] = {
                    "key": req.key,
                    "label": req.label,
                    "category": req.category,
                    "purpose": req.purpose,
                    "required": req.required,
                }
    required_connectors = [c for c in connectors_by_key.values() if c["required"]]
    optional_connectors = [c for c in connectors_by_key.values() if not c["required"]]

    # Agent catalog entries for selected agents
    agents_meta = [get_agent_entry(a) for a in selected if get_agent_entry(a)]

    return {
        "ok": True,
        "stack_id": "custom",
        "stack_name": f"Custom Stack ({', '.join(selected)})",
        "instruction": instruction,
        "founder_id": founder_id,
        "company_name": company_name or "",
        "agents": agents_meta,
        "tasks": tasks,
        "artifacts": artifacts,
        "approval_queue": approval_queue,
        "connector_setup": {
            "required": required_connectors,
            "optional": optional_connectors,
        },
        "start_payload": {
            "founder_id": founder_id or "<founder_id>",
            "instruction": instruction,
            "stack_id": "custom",
            "constraints": {
                "stack_id": "custom",
                "agents": selected,
                "company_name": company_name or "",
            },
        },
        "summary": (
            f"Custom stack with {len(selected)} agent(s) "
            f"({', '.join(selected)}), {len(tasks)} task(s), "
            f"{len(artifacts)} artifact(s), and {len(approval_queue)} approval gate(s)."
        ),
    }
