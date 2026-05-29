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
            title="Product roadmap",
            instruction=(
                "Define the MVP product architecture and build path. Produce a practical "
                "technical roadmap with core entities, auth/data needs, repo structure, and "
                "first usable product scope."
            ),
            depends_on=["t_research"],
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


STACK_TEMPLATES: dict[str, AgentStackTemplate] = {
    IDEA_TO_REVENUE_STACK.stack_id: IDEA_TO_REVENUE_STACK,
    SALES_STACK.stack_id: SALES_STACK,
    MARKETING_STACK.stack_id: MARKETING_STACK,
    FOUNDER_OPS_STACK.stack_id: FOUNDER_OPS_STACK,
    SUPPORT_STACK.stack_id: SUPPORT_STACK,
    PRODUCT_STACK.stack_id: PRODUCT_STACK,
}

DEFAULT_STACK_ID = IDEA_TO_REVENUE_STACK.stack_id


def get_stack_template(stack_id: str | None = None) -> AgentStackTemplate:
    return STACK_TEMPLATES.get(stack_id or DEFAULT_STACK_ID, IDEA_TO_REVENUE_STACK)


def list_stack_templates() -> list[dict[str, Any]]:
    return [template.to_public_dict() for template in STACK_TEMPLATES.values()]
