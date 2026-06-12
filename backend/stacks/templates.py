"""Reusable Agent Stack templates.

Stack templates are the product contract between a founder outcome and the
agent operating system Astra deploys around it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class StackArtifact:
    key: str
    title: str
    owner_agent: str
    description: str
    required: bool = True


@dataclass(frozen=True)
class StackApprovalGate:
    key: str
    title: str
    trigger: str
    required_before: str
    reason: str


@dataclass(frozen=True)
class StackConnectorRequirement:
    key: str
    label: str
    category: str
    purpose: str
    required: bool = False


@dataclass(frozen=True)
class StackTaskTemplate:
    id: str
    agent: str
    title: str
    instruction: str
    depends_on: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AgentStackTemplate:
    stack_id: str
    name: str
    target_user: str
    primary_outcome: str
    description: str
    input_prompts: list[str]
    tasks: list[StackTaskTemplate]
    artifacts: list[StackArtifact]
    approval_gates: list[StackApprovalGate]
    connector_requirements: list[StackConnectorRequirement]
    dashboard_sections: list[str]
    completion_rules: list[str]

    def to_public_dict(self) -> dict[str, Any]:
        return asdict(self)

    def build_tasks(self, goal: str) -> list[dict[str, Any]]:
        return [
            {
                "id": task.id,
                "agent": task.agent,
                "instruction": (
                    f"{task.instruction}\n\n"
                    f"Founder goal: {goal}\n\n"
                    f"Stack: {self.name}. Primary outcome: {self.primary_outcome}"
                ),
                "depends_on": list(task.depends_on),
                "stack_task_title": task.title,
                "expected_artifacts": list(task.artifacts),
            }
            for task in self.tasks
        ]


IDEA_TO_REVENUE_STACK = AgentStackTemplate(
    stack_id="idea_to_revenue",
    name="Idea to Revenue Stack",
    target_user="Founders starting from a rough startup idea.",
    primary_outcome="Turn a startup idea into a launch-ready company foundation.",
    description=(
        "Creates the first operating kit for a new company: positioning, market research, "
        "ICP, competitor analysis, landing page, product roadmap, GTM plan, sales motion, "
        "legal basics, investor materials, and a 30-day execution plan."
    ),
    input_prompts=[
        "What are you trying to build?",
        "Who do you think the first customer is?",
        "What should exist at the end of this run?",
    ],
    tasks=[
        StackTaskTemplate(
            id="t_research",
            agent="research",
            title="Market foundation",
            instruction=(
                "Validate the market, target customer, pain severity, buying trigger, "
                "category, pricing references, and early wedge. Produce specific research "
                "that downstream agents can use directly."
            ),
            artifacts=["market_brief", "icp_brief", "pricing_hypothesis"],
        ),
        StackTaskTemplate(
            id="t_design",
            agent="design",
            title="Visual direction",
            instruction=(
                "Create the brand direction for the company foundation: positioning tone, "
                "visual system, landing page style, typography guidance, colors, and UI feel."
            ),
            depends_on=["t_research"],
            artifacts=["brand_direction"],
        ),
        StackTaskTemplate(
            id="t_web",
            agent="web",
            title="Launch surface",
            instruction=(
                "Create and deploy a conversion-focused landing page based on the research "
                "and brand direction. Include hero copy, value props, social proof framing, "
                "waitlist or lead capture direction, and deployment handoff."
            ),
            depends_on=["t_research", "t_design"],
            artifacts=["landing_page", "website_copy"],
        ),
        StackTaskTemplate(
            id="t_technical",
            agent="technical",
            title="Product build",
            instruction=(
                "Build the full product on top of the web agent's Next.js repo: add sign-up/auth, "
                "a dashboard, and the core product features. Use the web agent's existing repo_url — "
                "do NOT create a new repo. Keep the marketing landing the web agent built."
            ),
            # Runs AFTER the web agent so it extends the same Next.js repo.
            depends_on=["t_research", "t_web"],
            artifacts=["mvp_roadmap", "technical_plan"],
        ),
        StackTaskTemplate(
            id="t_marketing",
            agent="marketing",
            title="Go-to-market motion",
            instruction=(
                "Create the launch marketing motion: positioning angle, first channels, "
                "content ideas, launch sequence, landing page CTA strategy, and messaging "
                "tests tied to the target customer."
            ),
            depends_on=["t_research"],
            artifacts=["gtm_plan", "launch_content"],
        ),
        StackTaskTemplate(
            id="t_sales",
            agent="sales",
            title="Revenue system",
            instruction=(
                "Design the first revenue workflow: prospect definition, CRM fields, cold "
                "email sequence, qualification criteria, sales script, and follow-up cadence."
            ),
            depends_on=["t_research"],
            artifacts=["crm_setup", "cold_email_sequence", "sales_playbook"],
        ),
        StackTaskTemplate(
            id="t_legal",
            agent="legal",
            title="Legal starter kit",
            instruction=(
                "Draft the legal and compliance starter kit appropriate for this idea: "
                "privacy policy outline, terms outline, risk notes, entity considerations, "
                "and founder checklist. Do not file or publish anything without approval."
            ),
            depends_on=["t_research"],
            artifacts=["legal_checklist", "policy_outline"],
        ),
        StackTaskTemplate(
            id="t_ops",
            agent="ops",
            title="Execution operating plan",
            instruction=(
                "Synthesize every lane into a founder operating plan: 30-day execution plan, "
                "weekly milestones, priorities, decision log, investor memo outline, and "
                "next actions for the founder."
            ),
            depends_on=["t_research", "t_web", "t_technical", "t_marketing", "t_sales", "t_legal"],
            artifacts=["thirty_day_plan", "investor_memo", "founder_next_actions"],
        ),
    ],
    artifacts=[
        StackArtifact("market_brief", "Market brief", "research", "Market size, category, trends, and validation signals."),
        StackArtifact("icp_brief", "ICP brief", "research", "Target customer, pain, trigger, objections, and buying process."),
        StackArtifact("pricing_hypothesis", "Pricing hypothesis", "research", "Initial packaging and pricing rationale."),
        StackArtifact("brand_direction", "Brand direction", "design", "Visual and verbal design system for launch."),
        StackArtifact("landing_page", "Landing page", "web", "Public launch surface or deployable page output."),
        StackArtifact("website_copy", "Website copy", "web", "Hero, sections, CTA, FAQ, and conversion copy."),
        StackArtifact("mvp_roadmap", "MVP roadmap", "technical", "Product scope, user stories, and build sequence."),
        StackArtifact("technical_plan", "Technical plan", "technical", "Architecture, data model, repo, and deployment plan."),
        StackArtifact("gtm_plan", "GTM plan", "marketing", "Launch channels, messaging tests, and initial campaign plan."),
        StackArtifact("launch_content", "Launch content", "marketing", "Social, email, and community copy drafts."),
        StackArtifact("crm_setup", "CRM setup", "sales", "Pipeline stages, fields, and lead management process."),
        StackArtifact("cold_email_sequence", "Cold email sequence", "sales", "Outbound sequence for the first ICP."),
        StackArtifact("sales_playbook", "Sales playbook", "sales", "Discovery script, qualification, objections, and close path."),
        StackArtifact("legal_checklist", "Legal checklist", "legal", "Founder legal risk and setup checklist."),
        StackArtifact("policy_outline", "Policy outline", "legal", "Privacy and terms outline for launch."),
        StackArtifact("thirty_day_plan", "30-day plan", "ops", "Week-by-week operating plan."),
        StackArtifact("investor_memo", "Investor memo", "ops", "Concise investor/fundraising narrative."),
        StackArtifact("founder_next_actions", "Founder next actions", "ops", "Prioritized next actions and approvals."),
    ],
    approval_gates=[
        StackApprovalGate(
            key="public_deploy",
            title="Publish public launch surface",
            trigger="web agent has a deployable landing page",
            required_before="public website publication or production domain changes",
            reason="Public-facing brand and claims need founder approval.",
        ),
        StackApprovalGate(
            key="outbound_send",
            title="Send outbound email",
            trigger="sales or marketing creates an email sequence",
            required_before="sending email to prospects or importing contacts into a campaign",
            reason="Outbound can affect reputation, deliverability, and legal compliance.",
        ),
        StackApprovalGate(
            key="legal_publish",
            title="Use legal documents publicly",
            trigger="legal agent drafts policy, terms, or entity guidance",
            required_before="publishing policies, filing entity documents, or paying filing fees",
            reason="Legal and financial actions must stay founder-controlled.",
        ),
    ],
    connector_requirements=[
        StackConnectorRequirement("github", "GitHub", "code", "Create or update the product repository and preserve implementation handoff.", True),
        StackConnectorRequirement("vercel", "Vercel", "deployment", "Deploy or prepare the launch surface and app preview.", True),
        StackConnectorRequirement("supabase", "Supabase", "data", "Prepare the database/auth foundation for the MVP.", False),
        StackConnectorRequirement("clerk", "Clerk", "auth", "Prepare authentication requirements and setup notes.", False),
        StackConnectorRequirement("gmail", "Gmail", "outreach", "Draft founder-approved outbound and launch emails.", False),
        StackConnectorRequirement("google_drive", "Google Drive", "knowledge", "Store investor, legal, and planning artifacts.", False),
        StackConnectorRequirement("obsidian", "Obsidian", "company_brain", "Persist research, decisions, artifacts, and execution context.", False),
    ],
    dashboard_sections=[
        "Stack overview",
        "Agent lanes",
        "Artifacts",
        "Approval queue",
        "30-day plan",
        "Company brain",
    ],
    completion_rules=[
        "All required artifacts are produced or explicitly marked blocked.",
        "Approval-gated actions are either approved, skipped, or left as founder next actions.",
        "Ops synthesizes the final 30-day execution plan from every completed lane.",
    ],
)


SALES_STACK = AgentStackTemplate(
    stack_id="sales",
    name="Sales Stack",
    target_user="Existing teams that need repeatable pipeline without hiring a full sales team.",
    primary_outcome="Turn a revenue goal into a measurable outbound and CRM operating system.",
    description=(
        "Builds an ICP, lead sourcing motion, qualification model, outbound sequence, CRM "
        "structure, sales script, follow-up cadence, and approval gates for contacting prospects."
    ),
    input_prompts=[
        "What revenue target or sales outcome are you trying to hit?",
        "Who is the buyer and what do they already use?",
        "What tools should Astra connect or prepare handoff for?",
    ],
    tasks=[
        StackTaskTemplate(
            id="s_research",
            agent="research",
            title="Buyer and market map",
            instruction="Research the buyer, market segment, competitors, budgets, purchase triggers, and objections for this sales goal.",
            artifacts=["buyer_brief", "competitor_sales_map"],
        ),
        StackTaskTemplate(
            id="s_sales",
            agent="sales",
            title="Pipeline system",
            instruction="Create the sales operating system: lead criteria, prospect list strategy, CRM stages, qualification rubric, discovery script, and follow-up cadence.",
            depends_on=["s_research"],
            artifacts=["lead_strategy", "crm_pipeline", "sales_script", "followup_cadence"],
        ),
        StackTaskTemplate(
            id="s_marketing",
            agent="marketing",
            title="Outbound messaging",
            instruction="Turn the buyer research into cold email, LinkedIn, and nurture messaging with clear pain, proof, offer, and CTA variants.",
            depends_on=["s_research"],
            artifacts=["outbound_sequence", "message_tests"],
        ),
        StackTaskTemplate(
            id="s_ops",
            agent="ops",
            title="Sales operating rhythm",
            instruction="Create the weekly sales rhythm, metrics dashboard, approval checklist, handoff rules, and next actions for executing the pipeline.",
            depends_on=["s_sales", "s_marketing"],
            artifacts=["sales_dashboard_spec", "weekly_sales_rhythm", "approval_checklist"],
        ),
    ],
    artifacts=[
        StackArtifact("buyer_brief", "Buyer brief", "research", "Buyer profile, budget, triggers, objections, and market context."),
        StackArtifact("competitor_sales_map", "Competitor sales map", "research", "Competitors, alternatives, positioning gaps, and sales angles."),
        StackArtifact("lead_strategy", "Lead strategy", "sales", "Prospect criteria, source channels, and prioritization rules."),
        StackArtifact("crm_pipeline", "CRM pipeline", "sales", "Stages, fields, statuses, and next-step rules."),
        StackArtifact("sales_script", "Sales script", "sales", "Discovery flow, qualification questions, objections, and close path."),
        StackArtifact("followup_cadence", "Follow-up cadence", "sales", "Follow-up timing, channel mix, and copy direction."),
        StackArtifact("outbound_sequence", "Outbound sequence", "marketing", "Email and LinkedIn sequence drafts."),
        StackArtifact("message_tests", "Message tests", "marketing", "Messaging variants to test by persona or pain point."),
        StackArtifact("sales_dashboard_spec", "Sales dashboard spec", "ops", "Metrics, views, and reporting cadence."),
        StackArtifact("weekly_sales_rhythm", "Weekly sales rhythm", "ops", "Weekly operating schedule and review structure."),
        StackArtifact("approval_checklist", "Approval checklist", "ops", "Required founder approvals before live outreach."),
    ],
    approval_gates=[
        StackApprovalGate("prospect_import", "Import prospects", "lead list is ready", "CRM import or enrichment", "Prospect data handling and targeting need approval."),
        StackApprovalGate("send_outbound", "Send outbound", "sequence is drafted", "email or LinkedIn sending", "Outbound affects brand, deliverability, and compliance."),
    ],
    connector_requirements=[
        StackConnectorRequirement("crm", "CRM", "sales_system", "Store accounts, contacts, stages, notes, and follow-up state.", True),
        StackConnectorRequirement("gmail", "Gmail", "outreach", "Draft or send founder-approved outbound sequences.", True),
        StackConnectorRequirement("linkedin", "LinkedIn", "outreach", "Prepare social selling actions and account research.", False),
        StackConnectorRequirement("google_sheets", "Google Sheets", "data", "Export lead lists, qualification scores, and pipeline views.", False),
        StackConnectorRequirement("slack", "Slack", "notifications", "Post sales alerts, daily pipeline updates, and approval requests.", False),
    ],
    dashboard_sections=["Pipeline", "Prospects", "Sequences", "CRM handoff", "Approval queue", "Outcome ledger"],
    completion_rules=[
        "ICP, pipeline stages, and outbound copy are ready for founder review.",
        "No prospect is contacted until the outbound approval gate is cleared.",
        "Sales operating rhythm and tracked metrics are defined.",
    ],
)


MARKETING_STACK = AgentStackTemplate(
    stack_id="marketing",
    name="Marketing Stack",
    target_user="Teams that need campaigns, positioning, content, and launch execution.",
    primary_outcome="Turn a growth goal into a campaign engine with assets, channels, and measurement.",
    description=(
        "Creates positioning, audience research, campaign angles, content calendar, landing "
        "page recommendations, ad/social creative direction, and launch measurement."
    ),
    input_prompts=["What are you launching or trying to grow?", "Who should see it?", "Which channels matter most?"],
    tasks=[
        StackTaskTemplate("m_research", "research", "Audience insight", "Research audience pain, category alternatives, keywords, channels, and competitor messaging.", artifacts=["audience_brief", "channel_map"]),
        StackTaskTemplate("m_design", "design", "Campaign creative system", "Create campaign visual direction, creative principles, ad style, landing page hierarchy, and content design guidance.", depends_on=["m_research"], artifacts=["campaign_creative_direction"]),
        StackTaskTemplate("m_marketing", "marketing", "Campaign plan", "Build campaign messaging, content calendar, social posts, email angles, ad concepts, and testing plan.", depends_on=["m_research", "m_design"], artifacts=["campaign_plan", "content_calendar", "creative_briefs"]),
        StackTaskTemplate("m_web", "web", "Conversion surface", "Recommend or build the campaign landing page structure, CTA flow, proof points, and conversion copy based on the campaign plan.", depends_on=["m_research", "m_design"], artifacts=["landing_recommendations", "conversion_copy"]),
        StackTaskTemplate("m_ops", "ops", "Launch control room", "Create the launch checklist, measurement plan, owner map, reporting cadence, and post-launch optimization loop.", depends_on=["m_marketing", "m_web"], artifacts=["launch_checklist", "measurement_plan"]),
    ],
    artifacts=[
        StackArtifact("audience_brief", "Audience brief", "research", "Audience segments, pains, jobs, and triggers."),
        StackArtifact("channel_map", "Channel map", "research", "Best acquisition channels and rationale."),
        StackArtifact("campaign_creative_direction", "Campaign creative direction", "design", "Visual and creative system for the campaign."),
        StackArtifact("campaign_plan", "Campaign plan", "marketing", "Messaging, channels, calendar, and test plan."),
        StackArtifact("content_calendar", "Content calendar", "marketing", "Sequenced content schedule and formats."),
        StackArtifact("creative_briefs", "Creative briefs", "marketing", "Briefs for social, ads, email, and launch assets."),
        StackArtifact("landing_recommendations", "Landing recommendations", "web", "Landing page structure and conversion recommendations."),
        StackArtifact("conversion_copy", "Conversion copy", "web", "CTA, hero, proof, FAQ, and campaign copy."),
        StackArtifact("launch_checklist", "Launch checklist", "ops", "Execution checklist and owner map."),
        StackArtifact("measurement_plan", "Measurement plan", "ops", "KPIs, dashboard, cadence, and optimization loop."),
    ],
    approval_gates=[
        StackApprovalGate("publish_campaign", "Publish campaign", "campaign assets are ready", "public posting or ad launch", "Public claims and spend need approval."),
        StackApprovalGate("paid_spend", "Start paid spend", "ad concepts are ready", "paid campaign activation", "Budget and targeting need founder control."),
    ],
    connector_requirements=[
        StackConnectorRequirement("website_cms", "Website CMS", "publishing", "Publish or prepare campaign pages and content updates.", True),
        StackConnectorRequirement("meta_ads", "Meta Ads", "paid_media", "Prepare paid campaign structure and creative handoff.", False),
        StackConnectorRequirement("linkedin", "LinkedIn", "social", "Draft social launch posts and distribution tasks.", False),
        StackConnectorRequirement("gmail", "Gmail", "email", "Draft campaign emails and launch announcements.", False),
        StackConnectorRequirement("analytics", "Analytics", "measurement", "Track conversion, traffic, and campaign performance.", True),
    ],
    dashboard_sections=["Audience", "Campaigns", "Creative", "Landing page", "Measurement", "Approvals"],
    completion_rules=["Campaign plan and launch checklist are ready.", "Measurement loop is defined.", "Paid/public actions remain approval-gated."],
)


FOUNDER_OPS_STACK = AgentStackTemplate(
    stack_id="founder_ops",
    name="Founder Ops Stack",
    target_user="Founders who need an operating system for priorities, fundraising, decisions, and execution.",
    primary_outcome="Turn company context into a weekly operating cadence and founder command center.",
    description="Creates the founder operating rhythm: goals, decisions, investor materials, team rituals, knowledge base, and execution tracking.",
    input_prompts=["What part of the company feels disorganized?", "What decisions or deadlines are coming up?", "Where does the team currently work?"],
    tasks=[
        StackTaskTemplate("o_research", "research", "Company context map", "Research and structure the company context, market pressure, current priorities, risks, and open questions.", artifacts=["company_context_brief"]),
        StackTaskTemplate("o_ops", "ops", "Operating system", "Create the operating cadence, weekly review, decision log, metrics, owner map, investor update, and 30-day execution calendar.", depends_on=["o_research"], artifacts=["operating_cadence", "decision_log", "investor_update", "thirty_day_execution_calendar"]),
        StackTaskTemplate("o_technical", "technical", "Systems architecture", "Define the lightweight internal systems, data model, integrations, and automation handoffs needed for the founder ops command center.", depends_on=["o_research"], artifacts=["ops_system_architecture", "integration_plan"]),
        StackTaskTemplate("o_legal", "legal", "Risk and compliance checklist", "Identify legal, compliance, privacy, hiring, and fundraising risks that should be tracked in the founder operating system.", depends_on=["o_research"], artifacts=["risk_register"]),
    ],
    artifacts=[
        StackArtifact("company_context_brief", "Company context brief", "research", "Structured context, priorities, risks, and questions."),
        StackArtifact("operating_cadence", "Operating cadence", "ops", "Weekly/monthly operating rhythm and rituals."),
        StackArtifact("decision_log", "Decision log", "ops", "Decision register and escalation rules."),
        StackArtifact("investor_update", "Investor update", "ops", "Investor update draft and metrics narrative."),
        StackArtifact("thirty_day_execution_calendar", "30-day execution calendar", "ops", "Calendar of actions, owners, and milestones."),
        StackArtifact("ops_system_architecture", "Ops system architecture", "technical", "Internal system and automation design."),
        StackArtifact("integration_plan", "Integration plan", "technical", "Connector plan for docs, chat, tasks, and CRM."),
        StackArtifact("risk_register", "Risk register", "legal", "Legal/compliance risks and owner rules."),
    ],
    approval_gates=[
        StackApprovalGate("send_investor_update", "Send investor update", "investor update is drafted", "sending to investors", "Investor communications must be founder-approved."),
    ],
    connector_requirements=[
        StackConnectorRequirement("slack", "Slack", "team_context", "Read team updates and deliver operating cadence reminders.", False),
        StackConnectorRequirement("notion", "Notion", "knowledge", "Maintain company operating docs, decisions, and weekly plans.", False),
        StackConnectorRequirement("google_drive", "Google Drive", "documents", "Store investor updates, board docs, and planning artifacts.", True),
        StackConnectorRequirement("google_calendar", "Google Calendar", "cadence", "Coordinate weekly reviews, deadlines, and execution rituals.", False),
        StackConnectorRequirement("obsidian", "Obsidian", "company_brain", "Persist the founder knowledge base and decision history.", False),
    ],
    dashboard_sections=["Command center", "Decisions", "Metrics", "Investor updates", "Risks", "Connectors"],
    completion_rules=["Operating cadence is defined.", "Risks and decisions are tracked.", "Investor/update drafts are approval-gated."],
)


SUPPORT_STACK = AgentStackTemplate(
    stack_id="support",
    name="Customer Support Stack",
    target_user="Teams that need support workflows, knowledge base, and customer feedback loops.",
    primary_outcome="Turn support chaos into a support operating system with triage, answers, and escalation.",
    description="Builds ticket taxonomy, macros, knowledge base outline, escalation rules, feedback reporting, and customer-facing response guidelines.",
    input_prompts=["What support requests repeat most often?", "Where do tickets/messages arrive?", "What needs escalation to humans?"],
    tasks=[
        StackTaskTemplate("c_research", "research", "Customer issue map", "Research customer segments, common support categories, competitor support patterns, and self-serve expectations.", artifacts=["support_issue_map"]),
        StackTaskTemplate("c_ops", "ops", "Support workflow", "Create ticket triage, SLA rules, escalation workflow, reporting cadence, and feedback loop into product.", depends_on=["c_research"], artifacts=["triage_workflow", "sla_policy", "feedback_loop"]),
        StackTaskTemplate("c_marketing", "marketing", "Customer communication", "Draft support macros, tone rules, onboarding emails, and customer-facing help copy.", depends_on=["c_research"], artifacts=["support_macros", "customer_comms"]),
        StackTaskTemplate("c_technical", "technical", "Support system plan", "Define knowledge base structure, support tooling, integration points, data capture, and automation boundaries.", depends_on=["c_research"], artifacts=["knowledge_base_plan", "support_integration_plan"]),
    ],
    artifacts=[
        StackArtifact("support_issue_map", "Support issue map", "research", "Common issues, categories, and customer expectations."),
        StackArtifact("triage_workflow", "Triage workflow", "ops", "Ticket routing, priority, owners, and escalation."),
        StackArtifact("sla_policy", "SLA policy", "ops", "Response times and severity definitions."),
        StackArtifact("feedback_loop", "Feedback loop", "ops", "How support insights become product work."),
        StackArtifact("support_macros", "Support macros", "marketing", "Reusable customer response drafts."),
        StackArtifact("customer_comms", "Customer comms", "marketing", "Tone, onboarding, and help copy."),
        StackArtifact("knowledge_base_plan", "Knowledge base plan", "technical", "Help center structure and content map."),
        StackArtifact("support_integration_plan", "Support integration plan", "technical", "Tools, connectors, and automation boundaries."),
    ],
    approval_gates=[
        StackApprovalGate("customer_response", "Send customer responses", "macros are ready", "automated or bulk customer messaging", "Customer communication needs tone and policy approval."),
    ],
    connector_requirements=[
        StackConnectorRequirement("helpdesk", "Helpdesk", "support_system", "Read tickets and apply triage, macros, and escalation rules.", True),
        StackConnectorRequirement("slack", "Slack", "escalation", "Route urgent customer issues to the right internal channel.", False),
        StackConnectorRequirement("notion", "Notion", "knowledge_base", "Maintain support docs and internal playbooks.", False),
        StackConnectorRequirement("product_tracker", "Product tracker", "feedback", "Turn repeated support issues into product backlog signals.", False),
    ],
    dashboard_sections=["Tickets", "Knowledge base", "Macros", "Escalations", "Feedback", "Approvals"],
    completion_rules=["Support categories and escalation rules are clear.", "Knowledge base and macros are ready for review.", "Automated customer messaging is approval-gated."],
)


PRODUCT_STACK = AgentStackTemplate(
    stack_id="product",
    name="Product Stack",
    target_user="Teams that need product strategy, roadmap, specs, and delivery coordination.",
    primary_outcome="Turn product ambiguity into a roadmap, specs, architecture, and delivery plan.",
    description="Creates product research, user stories, requirements, technical architecture, design direction, roadmap, and release plan.",
    input_prompts=["What product outcome are you trying to ship?", "Who is the user?", "What constraints or current stack exist?"],
    tasks=[
        StackTaskTemplate("p_research", "research", "User and market research", "Research users, jobs-to-be-done, alternatives, feature expectations, market gaps, and success metrics.", artifacts=["product_research_brief", "success_metrics"]),
        StackTaskTemplate("p_design", "design", "Experience direction", "Create product UX principles, user flows, screen map, visual direction, and usability risks.", depends_on=["p_research"], artifacts=["ux_flow", "screen_map"]),
        StackTaskTemplate("p_technical", "technical", "Technical delivery plan", "Define architecture, data model, API shape, repo plan, implementation sequence, and release risks.", depends_on=["p_research", "p_design"], artifacts=["technical_spec", "implementation_plan"]),
        StackTaskTemplate("p_ops", "ops", "Roadmap and release plan", "Create roadmap, milestones, sprint plan, owner map, release checklist, and decision log.", depends_on=["p_research", "p_design", "p_technical"], artifacts=["product_roadmap", "release_plan", "decision_log"]),
    ],
    artifacts=[
        StackArtifact("product_research_brief", "Product research brief", "research", "User, problem, market, and competitor findings."),
        StackArtifact("success_metrics", "Success metrics", "research", "Product KPIs and measurement plan."),
        StackArtifact("ux_flow", "UX flow", "design", "Primary user flows and interaction model."),
        StackArtifact("screen_map", "Screen map", "design", "Key screens, states, and layout guidance."),
        StackArtifact("technical_spec", "Technical spec", "technical", "Architecture, data model, APIs, and implementation risks."),
        StackArtifact("implementation_plan", "Implementation plan", "technical", "Build sequence and repo/deployment plan."),
        StackArtifact("product_roadmap", "Product roadmap", "ops", "Milestones, priorities, and sequencing."),
        StackArtifact("release_plan", "Release plan", "ops", "Release checklist and handoff plan."),
        StackArtifact("decision_log", "Decision log", "ops", "Open decisions and owner rules."),
    ],
    approval_gates=[
        StackApprovalGate("release_scope", "Approve release scope", "roadmap is ready", "implementation or launch", "Scope and sequencing should be founder/product-owner approved."),
    ],
    connector_requirements=[
        StackConnectorRequirement("github", "GitHub", "code", "Inspect codebase context, create issues, and prepare implementation handoff.", True),
        StackConnectorRequirement("linear", "Linear/Jira", "task_tracking", "Create roadmap issues, milestones, and delivery status.", False),
        StackConnectorRequirement("figma", "Figma", "design", "Connect design context and screen specs.", False),
        StackConnectorRequirement("analytics", "Analytics", "product_data", "Tie roadmap and success metrics to product usage.", False),
        StackConnectorRequirement("slack", "Slack", "team_context", "Summarize engineering/product updates and blockers.", False),
    ],
    dashboard_sections=["Research", "Specs", "Design", "Architecture", "Roadmap", "Release"],
    completion_rules=["Specs and roadmap are coherent.", "Implementation sequence is clear.", "Release scope is approval-gated."],
)


ECOMM_STACK = AgentStackTemplate(
    stack_id="ecomm",
    name="Ecommerce Stack",
    target_user="Founders launching or scaling an online store (physical goods, digital products, subscriptions, or print-on-demand).",
    primary_outcome="Launch a complete ecommerce operation: store, product copy, email flows, paid + organic acquisition, and supply chain basics.",
    description=(
        "End-to-end ecommerce launch kit: Shopify store setup, product catalog, brand and visual direction, "
        "email marketing flows, social + paid acquisition strategy, SEO, legal/compliance, and a 30-day launch plan."
    ),
    input_prompts=[
        "What are you selling and to whom?",
        "Do you have inventory/supply ready or are you still sourcing?",
        "What does success look like at the end of this run?",
    ],
    tasks=[
        StackTaskTemplate(
            id="t_research",
            agent="research",
            title="Market & product validation",
            instruction=(
                "Research the product category, target buyer, top competitors (Shopify stores, Amazon listings), "
                "pricing benchmarks, supplier options (Alibaba/Printful/Printify if relevant), and winning ad angles. "
                "Produce a product brief, ICP, and channel hypothesis."
            ),
            artifacts=["market_brief", "icp_brief", "product_brief", "pricing_hypothesis"],
        ),
        StackTaskTemplate(
            id="t_design",
            agent="design",
            title="Store brand direction",
            instruction=(
                "Create brand direction for an ecommerce store: color palette, typography, product image style, "
                "homepage layout, and packaging/unboxing concept. Shopify theme recommendation."
            ),
            depends_on=["t_research"],
            artifacts=["brand_direction", "theme_recommendation"],
        ),
        StackTaskTemplate(
            id="t_web",
            agent="web",
            title="Store build",
            instruction=(
                "Build and deploy the ecommerce storefront. Options in priority order: "
                "(1) Shopify store via Shopify API/CLI (preferred — most reliable, best conversion), "
                "(2) Next.js + Stripe + Supabase custom store if Shopify token unavailable. "
                "Include: homepage, product pages with compelling copy, cart/checkout, email capture, "
                "about page, and contact. All pages must be demo-accessible without account creation."
            ),
            depends_on=["t_research", "t_design"],
            artifacts=["store_url", "product_pages", "checkout_flow"],
        ),
        StackTaskTemplate(
            id="t_marketing",
            agent="marketing",
            title="Acquisition & retention",
            instruction=(
                "Design the ecommerce acquisition and retention system: paid social angles (Meta/TikTok), "
                "SEO product descriptions, email welcome + abandoned cart + post-purchase flows (Klaviyo-compatible), "
                "influencer/UGC brief, and launch sequence. Deliverable: ready-to-run email sequences + ad copy."
            ),
            depends_on=["t_research"],
            artifacts=["email_flows", "ad_copy", "seo_descriptions", "launch_sequence"],
        ),
        StackTaskTemplate(
            id="t_sales",
            agent="sales",
            title="Revenue & wholesale",
            instruction=(
                "Map the revenue model: pricing tiers, bundle/upsell strategy, wholesale/B2B channel if relevant, "
                "affiliate program brief, and customer lifetime value model. Include initial outreach for any B2B wholesale."
            ),
            depends_on=["t_research"],
            artifacts=["revenue_model", "upsell_strategy"],
        ),
        StackTaskTemplate(
            id="t_legal",
            agent="legal",
            title="Ecommerce compliance",
            instruction=(
                "Draft ecommerce legal essentials: return/refund policy, shipping policy, privacy policy (GDPR/CCPA), "
                "terms of service, sales tax obligations summary, and any product-specific compliance notes "
                "(FDA if consumables, FTC if supplements/claims, age verification if needed)."
            ),
            depends_on=["t_research"],
            artifacts=["return_policy", "privacy_policy", "terms", "compliance_notes"],
        ),
        StackTaskTemplate(
            id="t_ops",
            agent="ops",
            title="Launch operating plan",
            instruction=(
                "Synthesize into a founder launch plan: 30-day execution plan, supply chain checklist, "
                "fulfilment/shipping setup steps, weekly revenue targets, and post-launch review cadence."
            ),
            depends_on=["t_research", "t_web", "t_marketing", "t_sales", "t_legal"],
            artifacts=["thirty_day_plan", "supply_chain_checklist", "founder_next_actions"],
        ),
    ],
    artifacts=[
        StackArtifact("market_brief", "Market brief", "research", "Category, buyer, competitive landscape, pricing."),
        StackArtifact("icp_brief", "ICP brief", "research", "Target buyer, purchase trigger, objections."),
        StackArtifact("product_brief", "Product brief", "research", "Product positioning, key claims, differentiation."),
        StackArtifact("pricing_hypothesis", "Pricing hypothesis", "research", "Pricing and margin model."),
        StackArtifact("brand_direction", "Brand direction", "design", "Visual identity, theme rec, packaging concept."),
        StackArtifact("theme_recommendation", "Theme recommendation", "design", "Shopify theme + customisation notes."),
        StackArtifact("store_url", "Store URL", "web", "Live store or preview URL."),
        StackArtifact("product_pages", "Product pages", "web", "Built and copy-complete product pages."),
        StackArtifact("checkout_flow", "Checkout flow", "web", "Cart + checkout configured."),
        StackArtifact("email_flows", "Email flows", "marketing", "Welcome, abandoned cart, post-purchase sequences."),
        StackArtifact("ad_copy", "Ad copy", "marketing", "Meta/TikTok ad creative and copy."),
        StackArtifact("seo_descriptions", "SEO descriptions", "marketing", "Optimised product and collection descriptions."),
        StackArtifact("launch_sequence", "Launch sequence", "marketing", "Day-by-day launch playbook."),
        StackArtifact("revenue_model", "Revenue model", "sales", "Pricing, bundles, LTV, wholesale tier."),
        StackArtifact("upsell_strategy", "Upsell strategy", "sales", "Post-purchase and bundle upsell flows."),
        StackArtifact("return_policy", "Return policy", "legal", "Published returns and refund policy."),
        StackArtifact("privacy_policy", "Privacy policy", "legal", "GDPR/CCPA compliant privacy policy."),
        StackArtifact("terms", "Terms of service", "legal", "Ecommerce terms of service."),
        StackArtifact("compliance_notes", "Compliance notes", "legal", "Product-specific legal and regulatory notes."),
        StackArtifact("thirty_day_plan", "30-day plan", "ops", "Launch execution plan."),
        StackArtifact("supply_chain_checklist", "Supply chain checklist", "ops", "Supplier, inventory, and fulfilment steps."),
        StackArtifact("founder_next_actions", "Founder next actions", "ops", "Prioritised actions after this run."),
    ],
    approval_gates=[
        StackApprovalGate("store_publish", "Publish store", "store is built and ready", "going live on custom domain", "Public store launch needs founder sign-off."),
        StackApprovalGate("outbound_send", "Send outbound email", "email sequences are drafted", "sending to real subscribers", "Email sends affect deliverability and legal compliance."),
        StackApprovalGate("legal_publish", "Publish legal docs", "policies are drafted", "publishing policies to live store", "Policies must be founder-reviewed before they bind customers."),
    ],
    connector_requirements=[
        StackConnectorRequirement("shopify", "Shopify", "ecomm_platform", "Create and configure the store, products, and checkout.", True),
        StackConnectorRequirement("stripe", "Stripe", "payments", "Payment processing if building a custom store (fallback to Shopify Payments if Shopify).", False),
        StackConnectorRequirement("github", "GitHub", "code", "Store codebase if building custom Next.js store.", False),
        StackConnectorRequirement("vercel", "Vercel", "deployment", "Deploy custom store if not using Shopify hosting.", False),
        StackConnectorRequirement("klaviyo", "Klaviyo", "email_marketing", "Email flows, abandoned cart, post-purchase automation.", False),
        StackConnectorRequirement("gmail", "Gmail", "outreach", "Founder-approved transactional and launch emails.", False),
        StackConnectorRequirement("meta_ads", "Meta Ads", "paid_social", "Run paid acquisition campaigns.", False),
    ],
    dashboard_sections=["Store", "Products", "Acquisition", "Email flows", "Revenue model", "Operations"],
    completion_rules=[
        "Store is live or has a deployable preview.",
        "Email flows are drafted and ready to activate.",
        "Legal policies are drafted and approval-gated.",
        "30-day launch plan is produced.",
    ],
)


LOCAL_SERVICE_STACK = AgentStackTemplate(
    stack_id="local_service",
    name="Local Service Stack",
    target_user="Small service businesses: salons, barbershops, gyms, restaurants, cleaning, tutoring, pet care, and other local/appointment-based operations.",
    primary_outcome="Launch a complete local service operation: booking site, Google Business presence, local acquisition, and operational playbook.",
    description=(
        "End-to-end local service launch kit: booking website with Square/Acuity integration, Google Business Profile, "
        "local SEO and reviews strategy, SMS/email reminders, social content calendar, pricing model, "
        "compliance basics, and a 30-day customer acquisition plan."
    ),
    input_prompts=[
        "What service do you offer and where?",
        "How do customers currently book or find you?",
        "What does a successful first month look like?",
    ],
    tasks=[
        StackTaskTemplate(
            id="t_research",
            agent="research",
            title="Local market research",
            instruction=(
                "Research the local service category: typical pricing in the area, top competitors (Yelp, Google Maps), "
                "customer acquisition channels (Instagram, Google, word-of-mouth, Yelp), review strategies, "
                "and peak demand patterns. Produce a local ICP and positioning brief."
            ),
            artifacts=["local_market_brief", "icp_brief", "competitive_landscape"],
        ),
        StackTaskTemplate(
            id="t_design",
            agent="design",
            title="Brand & visual identity",
            instruction=(
                "Create brand direction for a local service business: logo concept, color palette, social media templates "
                "(Instagram grid style, story templates), booking confirmation email design, and signage brief."
            ),
            depends_on=["t_research"],
            artifacts=["brand_direction", "social_templates"],
        ),
        StackTaskTemplate(
            id="t_web",
            agent="web",
            title="Booking website",
            instruction=(
                "Build and deploy a local service booking website. Must include: "
                "hero with service name + location + CTA, services menu with pricing, "
                "online booking integration (embed Acuity Scheduling widget, or Square Appointments, or Calendly), "
                "staff/team section, photo gallery placeholder, customer reviews section, contact + map embed, "
                "and a mobile-first layout. Deploy via Vercel on Next.js. "
                "All pages must be accessible without login — demo mode with sample data."
            ),
            depends_on=["t_research", "t_design"],
            artifacts=["website_url", "booking_flow"],
        ),
        StackTaskTemplate(
            id="t_marketing",
            agent="marketing",
            title="Local acquisition",
            instruction=(
                "Design the local customer acquisition system: "
                "Google Business Profile optimisation guide (hours, photos, posts, review asks), "
                "Yelp listing setup steps, Instagram content calendar (30 posts), "
                "SMS reminder template for appointments (Twilio/SimpleTexting), "
                "referral program design (e.g. refer a friend, get 20% off), "
                "and Google/Meta local ad campaign brief. "
                "Output: ready-to-post captions, review-ask SMS templates, and ad creative brief."
            ),
            depends_on=["t_research"],
            artifacts=["google_business_guide", "social_calendar", "sms_templates", "referral_program", "local_ad_brief"],
        ),
        StackTaskTemplate(
            id="t_sales",
            agent="sales",
            title="Pricing & retention",
            instruction=(
                "Design the pricing model and retention system: service menu pricing, membership/package tiers "
                "(e.g. 10-session pack, monthly unlimited), upsell opportunities at point of service, "
                "loyalty program brief, gift card strategy, and corporate/group booking angle if applicable."
            ),
            depends_on=["t_research"],
            artifacts=["pricing_menu", "membership_tiers", "retention_playbook"],
        ),
        StackTaskTemplate(
            id="t_legal",
            agent="legal",
            title="Local business compliance",
            instruction=(
                "Draft local service legal essentials: service agreement / waiver template (especially for beauty, "
                "fitness, or food), cancellation and no-show policy, privacy policy for booking data, "
                "local business license checklist for the relevant service category and state, "
                "health and safety compliance notes (if beauty/food/fitness), and tip/gratuity policy."
            ),
            depends_on=["t_research"],
            artifacts=["service_agreement", "cancellation_policy", "license_checklist", "compliance_notes"],
        ),
        StackTaskTemplate(
            id="t_ops",
            agent="ops",
            title="Operations playbook",
            instruction=(
                "Synthesize into a 30-day launch operating plan: staff scheduling template, daily opening/closing "
                "checklist, supply/product inventory list, customer onboarding flow (first visit experience), "
                "weekly revenue targets, and review/feedback collection process."
            ),
            depends_on=["t_research", "t_web", "t_marketing", "t_sales", "t_legal"],
            artifacts=["thirty_day_plan", "ops_checklist", "founder_next_actions"],
        ),
    ],
    artifacts=[
        StackArtifact("local_market_brief", "Local market brief", "research", "Category pricing, competitors, acquisition channels."),
        StackArtifact("icp_brief", "ICP brief", "research", "Target customer, booking trigger, retention drivers."),
        StackArtifact("competitive_landscape", "Competitive landscape", "research", "Top local competitors on Yelp/Google."),
        StackArtifact("brand_direction", "Brand direction", "design", "Logo concept, palette, social templates."),
        StackArtifact("social_templates", "Social templates", "design", "Instagram grid and story templates."),
        StackArtifact("website_url", "Website URL", "web", "Live booking site URL."),
        StackArtifact("booking_flow", "Booking flow", "web", "Configured online booking integration."),
        StackArtifact("google_business_guide", "Google Business guide", "marketing", "Profile optimisation checklist."),
        StackArtifact("social_calendar", "Social calendar", "marketing", "30-post Instagram content calendar."),
        StackArtifact("sms_templates", "SMS templates", "marketing", "Appointment reminder and review-ask SMS."),
        StackArtifact("referral_program", "Referral program", "marketing", "Refer-a-friend mechanics and copy."),
        StackArtifact("local_ad_brief", "Local ad brief", "marketing", "Google/Meta local campaign brief."),
        StackArtifact("pricing_menu", "Pricing menu", "sales", "Service menu with prices."),
        StackArtifact("membership_tiers", "Membership tiers", "sales", "Package and membership pricing."),
        StackArtifact("retention_playbook", "Retention playbook", "sales", "Loyalty, upsell, and rebooking strategy."),
        StackArtifact("service_agreement", "Service agreement", "legal", "Client waiver and service terms."),
        StackArtifact("cancellation_policy", "Cancellation policy", "legal", "No-show and cancellation terms."),
        StackArtifact("license_checklist", "License checklist", "legal", "Local permits and license requirements."),
        StackArtifact("compliance_notes", "Compliance notes", "legal", "Health, safety, and regulatory notes."),
        StackArtifact("thirty_day_plan", "30-day plan", "ops", "Launch week-by-week execution plan."),
        StackArtifact("ops_checklist", "Ops checklist", "ops", "Daily/weekly operations checklist."),
        StackArtifact("founder_next_actions", "Founder next actions", "ops", "Prioritised actions after this run."),
    ],
    approval_gates=[
        StackApprovalGate("site_publish", "Publish booking site", "site is built and tested", "going live on custom domain", "Public site with booking needs founder sign-off."),
        StackApprovalGate("legal_publish", "Use legal docs with clients", "docs are drafted", "presenting to real clients or posting publicly", "Client-facing legal docs must be founder-reviewed."),
        StackApprovalGate("paid_ads", "Run paid local ads", "ad creative is ready", "spending real ad budget", "Ad spend needs founder approval."),
    ],
    connector_requirements=[
        StackConnectorRequirement("github", "GitHub", "code", "Host and version the booking site codebase.", True),
        StackConnectorRequirement("vercel", "Vercel", "deployment", "Deploy the booking website.", True),
        StackConnectorRequirement("square", "Square", "payments_pos", "In-person and online payments, appointments, and POS.", False),
        StackConnectorRequirement("acuity", "Acuity Scheduling", "booking", "Online appointment booking and calendar sync.", False),
        StackConnectorRequirement("twilio", "Twilio", "sms", "Automated appointment reminder and confirmation SMS.", False),
        StackConnectorRequirement("instagram", "Instagram", "social", "Post organic content and run local paid campaigns.", False),
        StackConnectorRequirement("gmail", "Gmail", "email", "Booking confirmations and marketing emails.", False),
    ],
    dashboard_sections=["Booking site", "Local presence", "Acquisition", "Pricing & retention", "Operations", "Legal"],
    completion_rules=[
        "Booking site is live or has a deployable preview.",
        "Google Business and social setup guides are produced.",
        "30-day acquisition plan is complete.",
        "Legal docs are drafted and approval-gated.",
    ],
)


STACK_TEMPLATES: dict[str, AgentStackTemplate] = {
    IDEA_TO_REVENUE_STACK.stack_id: IDEA_TO_REVENUE_STACK,
    SALES_STACK.stack_id: SALES_STACK,
    MARKETING_STACK.stack_id: MARKETING_STACK,
    FOUNDER_OPS_STACK.stack_id: FOUNDER_OPS_STACK,
    SUPPORT_STACK.stack_id: SUPPORT_STACK,
    PRODUCT_STACK.stack_id: PRODUCT_STACK,
    ECOMM_STACK.stack_id: ECOMM_STACK,
    LOCAL_SERVICE_STACK.stack_id: LOCAL_SERVICE_STACK,
}

# Product contract: Astra must cover "start from zero" founders plus existing
# businesses that need deployable AI departments for core operating functions.
PROMISED_AGENT_STACK_IDS = (
    "idea_to_revenue",
    "sales",
    "marketing",
    "founder_ops",
    "support",
    "product",
)

DEFAULT_STACK_ID = IDEA_TO_REVENUE_STACK.stack_id


def get_stack_template(stack_id: str | None = None) -> AgentStackTemplate:
    return STACK_TEMPLATES.get(stack_id or DEFAULT_STACK_ID, IDEA_TO_REVENUE_STACK)


def list_stack_templates() -> list[dict[str, Any]]:
    return [template.to_public_dict() for template in STACK_TEMPLATES.values()]
