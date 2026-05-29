# Astra Execution Priorities

This is the implementation translation of the Agent Stack Platform strategy and the attached execution docs. It exists to keep engineering focused on the product systems that make Astra defensible.

## Non-Negotiable Product Systems

### 1. Company Genome

The Company Genome is the system of record for company-specific operating context.

It should store:

- Company name, domain, and category
- ICP and buyer personas
- Core offers
- Positioning and brand voice
- Competitors and alternatives
- Customer objections
- Pricing and packaging assumptions
- Team, roles, and responsibilities
- Metrics and goals
- Decisions and rationale
- Connected sources and confidence levels

The Genome must be visible in the UI. If users do not see it growing, they will treat Astra like a chatbot instead of a compounding operating system.

### 2. Missing Team Map

The Missing Team Map diagnoses which business functions the company lacks.

Initial functions:

- Sales
- Marketing
- Founder Ops
- Customer Success
- Product
- Finance
- Legal
- Data/Analytics

Each function should show:

- Gap score
- Business risk
- Cost of not filling the role
- Recommended stack
- First action Astra can take

This should happen before broad stack deployment because it creates the "Astra understands my company" moment.

### 3. Stack Compiler

The Stack Compiler turns a goal into a configured stack.

It should produce:

- Selected stack template
- Agents included
- Workflow graph
- Required connectors
- Approval gates
- Expected artifacts
- Dashboard sections
- Completion rules

The user should not manually design the workflow. The compiler should explain why the selected stack fits the goal.

### 4. SafeRun

SafeRun governs agent actions before they affect the outside world.

It should record:

- Intended action
- Source context
- Tool used
- Target object
- Risk level
- Field diff, if applicable
- Approval requirement
- Execution result
- Rollback path, if available

Required approval actions:

- Sending outbound email
- Publishing public content
- Updating CRM/customer records
- Deploying public websites
- Spending money
- Filing legal or financial documents

SafeRun is not only safety infrastructure. It is a trust feature.

### 5. Outcome Ledger

The Outcome Ledger proves the value of Astra.

It should track:

- Leads found
- Emails drafted
- Emails approved
- CRM records created
- Meetings booked
- Pages deployed
- Artifacts produced
- Tasks completed
- Founder time saved
- Estimated business value

The dashboard and weekly digest should lead with outcomes, not agent activity. "Agents ran" is weak. "Astra created 42 qualified leads and drafted 18 personalized emails" is strong.

## First Stack Priorities

### Founder/Demo Wedge: Idea to Revenue Stack

Purpose:

Turn a rough startup idea into a launch-ready company foundation.

Required outputs:

- Positioning
- ICP
- Competitor map
- Pricing hypothesis
- Landing page copy
- Landing page or deployable surface
- Product roadmap
- CRM structure
- Cold email sequence
- Legal starter checklist
- Investor memo outline
- 30-day execution plan

This stack is the strongest demo and founder wedge.

### Commercial Wedge: Sales Stack

Purpose:

Produce measurable revenue activity for existing businesses.

Required outputs:

- ICP refinement
- Lead list
- Lead scores
- Personalized email drafts
- Follow-up sequence
- CRM records or import file
- Weekly sales report
- Outcome Ledger attribution

This stack is the strongest first paid wedge because ROI is concrete.

## Build Order

1. Normalize stack templates in backend.
2. Emit selected stack, expected artifacts, and approval gates in every run.
3. Show selected stack in the dashboard.
4. Add typed artifacts to the run state.
5. Add SafeRun action records before risky tools.
6. Add Outcome Ledger events for material outputs.
7. Build Company Genome UI from existing company brain records.
8. Build Missing Team Map from Genome data.
9. Add Sales Stack template once the stack runtime is stable.
10. Use the Outcome Ledger as the main retention and sales proof.

## What To Avoid

- Do not build a custom agent builder first.
- Do not build a stack marketplace first.
- Do not build every department stack shallowly.
- Do not position Astra as replacing every tool.
- Do not let agents write externally without SafeRun.
- Do not hide the Company Genome as backend-only memory.
- Do not optimize for agent activity instead of business outcomes.

## Success Criteria

The product is moving in the right direction when:

- Every run has a selected stack.
- Every stack has expected artifacts.
- Every high-risk action has a SafeRun record.
- Every finished run writes Outcome Ledger events.
- The dashboard shows company context, stack progress, approvals, and outcomes.
- The user can ask what happened last week and Astra answers from Genome, artifacts, actions, and outcomes.

