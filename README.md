# Astra

Astra is an AI company-building platform for founders, startup teams, and operator-heavy businesses. Give Astra a business objective and it turns that objective into a coordinated operating run: planning the work, dispatching specialist agents, streaming progress live, producing artifacts, tracking company context, gating risky actions behind approvals, and keeping the whole company operating layer durable and inspectable.

The pitch in one line: Astra is turning "build my company" from a prompt into an executable system.

## Pitch-Friendly Framing

- **AI operating system for founders**: go from idea, to plan, to execution, to deliverables inside one coordinated system.
- **More than a chatbot**: Astra routes work across specialist agents, preserves durable company context, and ties outputs to durable runs.
- **Built for serious operations**: approvals, memory, deployments, billing hooks, automations, and observability make it infrastructure, not a demo.

---

## Why Astra Stands Out

- **From goal to execution**: Astra creates a durable run, plans the work, coordinates agents, and records outcomes — it does not stop at chat.
- **A full specialist bench**: research, market/regulatory/financial research, legal (entity, docs, IP), web, web navigation, design, technical (scaffold, data, infra), finance (fundraise, modeling), ops, sales (pipeline, enablement), marketing (content, paid, SEO, outreach) — each a dedicated agent surface under `backend/specialists/`.
- **A durable company operating layer**: initiatives, squads, missions, a routing copilot, and research artifacts persist as an event-sourced log that always replays to current state.
- **Artifacts over answers**: Astra generates deliverables, keeps workspace history, stores reusable files, and turns work into something a founder can act on.
- **AI departments, not one-off prompts**: the Agent Stack platform compiles business outcomes into deployable execution packages with lanes, connectors, approval gates, and verification.
- **Visual automations**: a React Flow canvas builds trigger → agent → action flows, backed by a server-side integration registry (adding an integration needs no frontend change).
- **Founder control built in**: risky actions flow through approvals; teams stay scoped; runs stay inspectable through digests, workboards, receipts, and completion audits.

---

## Core Capabilities

- **Goal-to-run orchestration**: `POST /goal` creates a durable run, streams Server-Sent Events, dispatches specialists in lanes, and records artifacts. A legacy asyncio path and a Temporal workflow path (`AstraRunWorkflow`, durable state + cancel/steer/approval signals) both exist behind a per-run feature assignment.
- **Company operating layer**: an event-sourced store (`backend/company_os.py`) of initiatives, squads, missions, tasks, and artifacts. Every change is a checksummed append-only JSONL event; snapshots materialize state and segments auto-compact. Soft-deletes archive rather than destroy.
- **Routing copilot**: incoming founder messages are LLM-classified (`company_os_copilot.py`) as *answer* (reply directly), *continue* (reuse an existing initiative/squad), or *new* (dispatch fresh work) against live company state, so a follow-up like "what were the results?" reuses the running squad instead of spawning a duplicate.
- **Research missions**: internal analysis tasks gather evidence via MCP, then an LLM synthesizes a proper markdown decision brief. Raw evidence and mid-pipeline synthesis are kept as archived internal artifacts (hidden from the Library); only the final brief surfaces to founders.
- **Agent Stack platform**: compile a plain-language outcome into a deployable, verifiable department package — catalog → compiler → manifest → operating plan / execution blueprint → readiness / quality / verification gates → package + approvals.
- **Company Brain**: a company knowledge graph (graph-RAG) that syncs connected sources (Slack, Discord, GitHub, Notion, Google Workspace, and more), answers agent queries, and feeds run context.
- **Visual automations**: React Flow builder (`AutomationCanvas.tsx`) over a backend block/graph runtime (`automation_blocks.py`, `automation_graph.py`, `automation_runtime.py`, Windmill-backed) with webhook, agent, HTTP/action, condition, delay, and generic-integration nodes.
- **Custom agents & skills**: founder-defined agents with selector-based tool catalogs, scheduled runs, and attachable reusable skills.
- **Library, deliverables, deployments**: reusable file store, PDF/TXT/PPTX generation with founder delivery flows, and staging/production deployment records.
- **Credits & billing hooks**: token-to-credit accounting, checkout/webhook support, plan-based limits.
- **Teams & auth boundaries**: founder/team access controls, org invites, usage, and header/JWT auth.
- **MCP server**: `backend/astra_mcp.py` exposes Astra over Model Context Protocol (stdio JSON-RPC) so external agents can submit goals, query sessions, steer agents, approve work, and query the brain.
- **Production operations**: health, readiness, metrics, alerts, smoke checks, production launch/verification, and admin observability.

---

## How A Run Works

```text
Founder goal
    |
    v
POST /goal  ──►  RunCreateRequest ──► feature assign (legacy | temporal)
    |
    v
Durable run + session (JSONL events + meta; Redis + optional Supabase dual-write)
    |
    v
Orchestrator planner  (goal → stack → task DAG)   [or AstraRunWorkflow on the Temporal path]
    |
    v
Specialist agents fan out in lanes with shared context, tools, memory, approval gates
    |
    v
SSE stream: goal_start, plan_done, agent_start/action/done, stack_*, research_review,
            approval_required, outcome_recorded, goal_done | goal_error
    |
    v
Durable event store, vault, workboard, costs, deployments, company-layer updates
```

### SSE Event Types

The session UI is driven by an event stream. Real event strings include:

```text
goal_start · plan_done · company_name · agent_start · agent_thinking · agent_action ·
agent_tool_call · agent_done · agent_error · stack_selected · stack_operating_plan ·
stack_manifest · stack_execution_contract · stack_execution_blueprint · stack_approval_decision ·
research_review · research_direction_decision · approval_required · approval_resolved ·
tool_guardrail_warning · tool_guardrail_blocked · context_compression_started ·
subagent_spawned · subagent_completed · web_task_started · web_task_completed ·
deployment_check_failed · outcome_recorded · goal_done · goal_error · replay_complete
```

---

## Core Backend Areas

| Area | Purpose |
|---|---|
| `backend/main.py` | FastAPI app, routers, startup jobs, health/readiness/metrics, MCP HTTP endpoint |
| `backend/api/` | Product APIs for goals, sessions/runs, stacks, workspaces, teams, missions, skills, library, deliverables, deployments, credits, the company operating layer, and admin |
| `backend/core/` | Orchestrator planner, agent loop, event bus, session store, cancellation, usage, company-brain integration |
| `backend/control_plane/` | Durable run models, run initialization, and the Temporal path (`temporal/workflows.py` → `AstraRunWorkflow`, multi-phase execution, dispatch client) |
| `backend/company_os.py` + `company_os_copilot.py` / `_dispatch.py` / `_runner.py` | Event-sourced company operating layer: store, copilot turn routing, work dispatch, async mission executor |
| `backend/company_goal.py`, `company_brain.py` | Founder company-scoped operating goal; company knowledge graph + agent query tools |
| `backend/specialists/` | Domain agents and their prompts/tool contracts |
| `backend/stacks/` | Agent Stack catalog, compiler, manifests, operating plans, execution blueprints, readiness, quality/verification gates, approvals |
| `backend/tools/` | Search/browser research, doc/PDF/PPTX generation, deploy (Vercel/Cloudflare/local preview), GitHub/git, computer-use browser, CRM/prospecting, integration wrappers, automations, graph-RAG ingest |
| `backend/missions/` | Legacy mission persistence + company-goal lifecycle |
| `backend/provisioning/` | Connector/account provisioning + credentials store |
| `backend/custom_agents/`, `backend/skills/`, `backend/library/` | Custom agents + scheduling; agent-attached skills; founder file library |
| `backend/credits/`, `backend/deployments/`, `backend/safety/` | Credit ledger/checkout; deployment records; content filtering + SafeRun approval gates |
| `backend/astra_mcp.py` | Model Context Protocol server (stdio JSON-RPC) exposing Astra to external agents |
| `frontend/` | Next.js app (see below) |
| `deploy/`, `tests/` | nginx + production helpers; backend tests for agents, storage, billing, control plane, and policies |

---

## API Overview

### Runs and Sessions

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/goal`, `/runs` | Start a coordinated agent run |
| `GET` | `/stream/{session_id}` | SSE stream for live events (Last-Event-ID replay) |
| `GET` | `/runs/{run_id}`, `/runs/{run_id}/events` | Run status + event list |
| `POST` | `/runs/{run_id}/cancel` | Request run cancellation |
| `GET` | `/sessions` | List founder sessions |
| `GET` | `/sessions/{session_id}/state` | Rebuild session state from events |
| `GET` | `/sessions/{session_id}/meta` / `/cost` | Session metadata; token usage & cost |
| `POST` | `/sessions/{session_id}/kill` / `/pause` / `/resume` | Cancel, pause, resume dispatch |
| `POST` | `/sessions/{session_id}/stop-agent/{agent}` / `/rerun/{agent}` | Stop or re-run one agent |
| `DELETE` | `/sessions/{session_id}` | Delete a session and related artifacts |

### Company Operating Layer (`/companies/{company_id}/os`)

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/company-os` | Create the company operating layer (lazy init) |
| `GET` | `.../os` | Materialized state + reconciled initiatives |
| `POST` | `.../os/copilot` | Send a founder message → classify + route |
| `PATCH`/`DELETE` | `.../os/initiatives/{id}` | Edit / archive an initiative |
| `DELETE` | `.../os/squads/{id}` | Archive a squad |
| `GET`/`DELETE` | `.../os/artifacts/{id}` (+ `/download`) | Fetch, archive, or download an artifact as `.md` |
| `PATCH`/`DELETE` | `.../os/messages/{id}` | Edit / archive a founder message |
| `POST` | `.../os/messages/clear` | Archive the whole conversation |
| `POST` | `.../os/operations/tick` | Run the internal-analysis scheduler |

### Agent Stacks

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/stacks`, `/agents/catalog` | Stack templates; full specialist catalog |
| `POST` | `/stacks/recommend`, `/stacks/package`, `/stacks/custom` | Recommend / compile / build a stack package |
| `GET` | `/stacks/{id}/manifest` · `/operating-plan` · `/execution-blueprint` · `/quality` | Stack detail surfaces |
| `GET` | `/stacks/{id}/readiness/{founder_id}` · `/connector-coverage` · `/connector-setup` · `/connector-validation` | Founder readiness + connector checks |

### Other Product Surfaces (`/api`, `/missions`, `/brain`, ...)

| Area | Endpoints |
|---|---|
| Missions & company goal | `/missions`, `/missions/company-goal` (+ `/run`, `/approve-next`) |
| Company Brain | `/brain/{founder_id}` (+ `/sync`, `/graph-sync`, `/graph-rag`, `/search`, `/ask`, `/agent-context`) |
| Workspaces | `/workspaces`, chapters, vault |
| Teams / orgs | `/api/teams`, invites, members, org usage |
| Custom agents & skills | `/api/agents` (CRUD, scheduled run, tool selection); `/api/skills` (attach/detach) |
| Library / deliverables | `/api/library` (file CRUD); `/api/founders/{id}/deliverables/email` |
| Deployments / credits | `/api/deployments` (publish); `/api/credits` (add/deduct/checkout/webhook) |
| Automations | `/automations/flows` (CRUD + `/run` + `/draft`), `/automations/runs/{id}`, `/automations/hooks/{token}`, `/automations/integration-catalog` |

### Platform Operations

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` · `/ready` · `/metrics` | Health, readiness, Prometheus metrics |
| `POST` | `/mcp` | HTTP MCP bridge |
| `GET` | `/admin/*` | Observability, smoke checks, production launch/verification, alerts, logs, git/env/system info |

---

## Frontend

A Next.js 16 / React 19 / TypeScript app in `frontend/` (Tailwind CSS 4 + an `astra-redesign.css` design-token layer that reskins the whole app for light/dark without touching component code).

**Pages** (`app/`, App Router): `/` sign-in, `/dashboard` (the main app surface → `CompanyHome`), `/automations` + `/automations/canvas/[flowId]`, `/integrations`, `/library`, `/onboarding`, `/brain`, `/outreach`, `/credits`, `/payments`, `/settings`, `/proof/[token]` (public receipt viewer), `/invite/[token]`.

**Major components** (`components/`):
- `CompanyHome.tsx` — the home screen: initiatives, squads, approvals, brain summary, and the copilot conversation feed.
- `GoalWorkspace.tsx` / `SessionView.tsx` — the live run/session workspace and monitor (research/site previews, agent output panes, phase workboard).
- `AutomationCanvas.tsx` + `AutomationsPage.tsx` — visual automation builder + flow list.
- `CompanyBrainPage.tsx` — knowledge-graph sync/search/records UI.
- `IntegrationsPage.tsx`, `LibraryPanel.tsx`, `OnboardingWizard.tsx`, `MissionsPanel.tsx`, `SettingsPage.tsx`, `OutreachPage.tsx`, `PaymentsPage.tsx`.
- `CustomAgentsPanel.tsx` / `CustomAgentSessionView.tsx`, `SkillsPanel.tsx`, `ModelSettingsPanel.tsx`, `PhaseWorkboard.tsx` (+ `ReceiptTrail`).
- Shell & atoms: `AppChrome.tsx`, `RedesignSidebar.tsx`, `NotificationBell.tsx`, `ThemeToggle.tsx`, `RunStatusBadge.tsx`.

**API client** (`lib/`): `api.ts` (core fetch client — auth header injection, `streamGoal`/SSE, ~90 typed endpoint wrappers), `company-os.ts` (company operating layer), `control-plane-api.ts` (run polling/trace/approvals), `dashboard-api.ts`, `session-events.ts` (shared SSE subscription manager), `automation-draft.ts`, `auth.ts` (NextAuth).

**Real-time**: Server-Sent Events via `EventSource` (`streamGoal`, centralized in `session-events.ts`), with a polling fallback for run events in `control-plane-api.ts`.

Run locally:

```bash
cd frontend
npm install
npm run dev   # http://localhost:3000
```

---

## Setup

### Requirements

- Python 3.13+
- Redis (default event bus/cache path)
- Node.js/npm 18+ (frontend and generated app builds)
- Optional: Supabase, Temporal, Stripe, GitHub, Vercel, Composio, Google OAuth (Gmail/Workspace), SendGrid/Resend, Cloudflare, PostHog, Notion, Hunter, Apollo, Klaviyo, Twilio, Square, Printful, Yelp, Lemon Squeezy, browser automation credentials

### Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

### Environment

The backend reads local environment configuration through `backend/config.py`. Keep credentials, provider tokens, encryption material, and deployment-specific values in local untracked env files only. For local dev, set the minimal model/storage values for the flows you want, and add provider credentials only for integrations you are actively using. See [`backend/config.py`](backend/config.py) for the full surface.

### Run

```bash
# Backend
uvicorn backend.main:app --host 127.0.0.1 --port 8000

# Checks
curl http://localhost:8000/health
curl http://localhost:8000/ready
curl http://localhost:8000/stacks

# MCP server (stdio)
python -m backend.astra_mcp

# Tests
pytest
```

### Docker

The backend image (`Dockerfile.backend`) installs Python deps, Playwright Chromium, Node/npm, and the CLI used by generated builds. `docker-compose.yml` defines Redis, backend, frontend, and nginx:

```bash
docker compose build
docker compose up   # http://localhost (nginx proxies frontend + API)
```

### Desktop Shell (Optional)

An optional Tauri desktop shell lives in [`desktop/`](desktop) — loads the local Next.js dev server, shares auth/API config, requires Rust and Cargo. Not needed for web-only deployments.

```bash
cd desktop && npm install && npm run dev
```

---

## Production And Ops

Astra includes operator-facing checks and runbooks under `backend/production_*`, `backend/platform_status.py`, `backend/alerts.py`, `backend/deploy_evidence.py`, and `deploy/`. Tracked docs keep the product and architecture story; environment-specific release steps and secret inventories stay in local untracked notes.

Key docs:

- [One-Person Company Showcase](docs/One_Person_Company_Showcase.md)
- [Production Launch Runbook](docs/Production_Launch_Runbook.md)
- [Security Alignment Roadmap](docs/Security_Alignment_Roadmap.md)
- [Desktop Signing And Release](docs/Desktop_Release_Signing.md)

---

## Design Principles

- **Durable by default**: runs, events, the company operating layer, credits, deployments, missions, and library files persist so the UI can always replay state.
- **Founder control**: high-risk actions (deploys, emails, account actions, production changes) flow through approval gates.
- **Local-first where practical**: many stores are file-backed, with Supabase/Temporal and external providers layered in where production needs them.
- **Agent stacks over loose prompts**: repeatable outcomes compile into manifests, operating plans, quality/verification gates, connector requirements, and execution blueprints.
- **Observable runs**: token usage, costs, event logs, workboards, digests, receipts, completion audits, and admin endpoints make agent behavior inspectable.

---

## Repository Notes

- The worktree may contain generated artifacts (`__pycache__`, local previews, vault files, `.DS_Store`); avoid committing those. See `.gitignore`.
- `_archive/` keeps older orchestrator/agent experiments for reference.
- `proprietary_agent/` / `proprietary-agent/` hold experimental intelligence-layer concepts.
- `frontend/` is the primary Next.js app; `mockup/` holds older static prototypes.
- `desktop/` is an optional Tauri shell; not required for deployment.

---

## License

Proprietary. All rights reserved.
