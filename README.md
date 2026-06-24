# Astra

Astra is an AI company-building platform. A founder gives Astra a goal, and Astra turns it into a coordinated operating run: planning the work, dispatching specialist agents, streaming progress, producing artifacts, tracking workspace history, and gating risky actions behind approvals.

The project has grown from a single "six agents build a startup" prototype into a broader platform for AI departments, company memory, missions, workspaces, deployment tracking, credits, teams, model routing, and production-readiness operations.

---

## Current Capabilities

- **Goal-to-run orchestration**: `POST /goal` creates a durable session, streams Server-Sent Events, dispatches agents, and records artifacts.
- **Specialist agent team**: research, market research, regulatory research, legal, web, web navigation, design, technical, infra, data, marketing, SEO, paid marketing, outreach, sales, sales enablement, finance/fundraise, finance modeling, ops, and more under `backend/specialists/`.
- **Agent Stack Platform**: compile business outcomes into deployable AI department packages with lanes, artifacts, connectors, approval gates, quality checks, and readiness checks.
- **Custom agents**: founder-defined agents with selector-based tool catalogs, scheduled runs, auto-emailing results.
- **Workspaces and chapters**: each goal can create or extend a founder workspace so related sessions stay grouped.
- **Missions and company goals**: persistent operating goals, task lists, approvals, scheduled follow-up runs, and Notion sync support.
- **Company brain / context layer**: durable memory, session digesting, workboards, subteam reports, company reports, and connector-aware context.
- **Library and attachments**: upload or persist reusable files for agent-readable context.
- **Deliverables**: PDF/TXT generation, vault storage, email delivery to founder via Resend or Gmail.
- **Skills**: founder-defined skills can be attached to specific agents.
- **Credits and billing hooks**: token/credit accounting, Stripe checkout/webhook support, and plan-based limits.
- **Deployments**: staging/production deployment records and publish endpoints for generated projects.
- **Integrations**: Stripe, Vercel, GitHub, Composio (Gmail, LinkedIn, Calendar), Notion, Hunter, Apollo, Klaviyo, Twilio, Square, Printful, Yelp, Lemon Squeezy, direct Gmail OAuth, Resend.
- **Teams and auth boundaries**: founder/team access controls, invites, org usage, and optional JWT/header-based auth.
- **Production operations**: health, readiness, metrics, alerts, smoke checks, production launch, production verification, and admin observability endpoints.
- **Frontend**: Next.js app with real-time SSE updates, dark/light themes, responsive design, custom agent UI.

---

## How A Run Works

```text
Founder goal
    |
    v
POST /goal
    |
    v
Session + workspace/chapter registration
    |
    v
Orchestrator planner (or bypass for custom agents)
    |
    v
Specialist agents run with shared context, tools, memory, and approval gates
    |
    v
SSE stream: goal_start, plan_done, agent_start, actions, artifacts, approvals, done/error
    |
    v
Durable session store, vault, workboard, costs, deployments, company goal updates
    |
    v
Auto-email result summary to founder (custom agents only)
```

### Deliverables Flow

Generated files (PDFs, TXT reports) are stored in the vault and made available for:
- Download via the Deliverables tab
- Email delivery from Astra's no-reply address to the founder's registered Gmail
- Attachment to run-result summary emails (custom agent runs)

The backend is intentionally direct: FastAPI routes, Python agent loops, tool dispatch, Redis/SSE where needed, and local-first JSON/file stores for many product surfaces. External services are optional unless the requested workflow needs them.

---

## Core Backend Areas

| Area | Purpose |
|---|---|
| `backend/main.py` | FastAPI app, routers, startup jobs, health/readiness/metrics, MCP HTTP endpoint |
| `backend/api/` | Public product APIs for goals, sessions, stacks, workspaces, teams, missions, skills, library, deliverables, deployments, credits, admin |
| `backend/core/` | Orchestration, events, session store, cancellation, usage, workspace state, company brain integrations |
| `backend/specialists/` | Domain agents and their prompts/tool contracts |
| `backend/tools/` | Search, document/PDF generation, deployment, GitHub, Stripe, Gmail API, Resend, browser/computer-use, integrations (Klaviyo, Twilio, Square, Printful, Yelp, Lemon Squeezy), CRM/prospecting, local previews |
| `backend/stacks/` | Agent Stack catalog, compiler, manifests, operating plans, execution blueprints, readiness, quality audits |
| `backend/missions/` | Persistent missions, company goals, task scheduling, approval workflow integration |
| `backend/library/` | Founder file library |
| `backend/skills/` | Agent-attached reusable skills |
| `backend/deliverables.py` | Generated artifact storage, email delivery, run-result summaries |
| `backend/custom_agents/` | Custom agent definitions, runner, tool catalog, scheduling |
| `backend/credits/` | Credit ledger, checkout, token-to-credit accounting |
| `backend/deployments/` | Staging/production deployment records |
| `backend/provisioning/` | Connector/account provisioning helpers, credentials store |
| `backend/safety/` | Content filtering and SafeRun approval gates |
| `frontend/` | Next.js app with dashboard, sessions, custom agents, library, integrations UI |
| `deploy/` | nginx and production helper scripts |
| `tests/` | Backend tests for agents, storage, billing, production checks, policies, and workflows |

---

## API Overview

### Runs and Sessions

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/goal` | Start a coordinated agent run |
| `GET` | `/stream/{session_id}` | SSE stream for live session events |
| `GET` | `/sessions` | List founder sessions |
| `GET` | `/sessions/{session_id}/state` | Rebuild current session state |
| `GET` | `/sessions/{session_id}/replay` | Replay the durable event log as SSE |
| `GET` | `/sessions/{session_id}/meta` | Session metadata |
| `GET` | `/sessions/{session_id}/cost` | Token and cost accounting |
| `GET` | `/sessions/{session_id}/digest` | Session digest |
| `GET` | `/sessions/{session_id}/workboard` | Workboard view |
| `GET` | `/sessions/{session_id}/completion-audit` | Completion audit |
| `POST` | `/sessions/{session_id}/kill` | Stop a run and clean up previews/workspace files |
| `POST` | `/sessions/{session_id}/pause` | Pause a run |
| `POST` | `/sessions/{session_id}/resume` | Resume a paused run |
| `DELETE` | `/sessions/{session_id}` | Delete a session and related run artifacts |

### Agent Stacks

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/stacks` | List available stack templates |
| `GET` | `/agents/catalog` | Full specialist catalog |
| `POST` | `/stacks/recommend` | Recommend a stack for an instruction |
| `POST` | `/stacks/package` | Compile an outcome into a deployable stack package |
| `POST` | `/stacks/custom` | Build a package from selected agents |
| `GET` | `/stacks/{stack_id}/manifest` | Stack manifest |
| `GET` | `/stacks/{stack_id}/operating-plan` | Operating plan |
| `GET` | `/stacks/{stack_id}/execution-blueprint` | Execution blueprint |
| `GET` | `/stacks/{stack_id}/quality` | Template quality audit |
| `GET` | `/stacks/{stack_id}/readiness/{founder_id}` | Founder readiness for a stack |
| `GET` | `/stacks/{stack_id}/connector-coverage/{founder_id}` | Connector coverage |
| `GET` | `/stacks/{stack_id}/connector-setup/{founder_id}` | Connector setup plan |
| `GET` | `/stacks/{stack_id}/connector-validation/{founder_id}` | Connector validation |

### Product Surfaces Under `/api`

| Area | Endpoints |
|---|---|
| Workspaces | `/workspaces`, `/workspaces/{workspace_id}`, chapters, vault |
| Teams | `/api/teams`, `/api/teams/me`, invites, member removal |
| Missions | `/api/missions`, company goal, task approval/postpone/run, Notion sync |
| Skills | `/api/skills`, attach/detach to agents |
| Library | `/api/library`, file CRUD |
| Custom agents | `/api/agents`, create/list/update/delete/run, scheduled execution, tool selection |
| Deliverables | `/api/founders/{founder_id}/deliverables/email`, email generated artifacts |
| Deployments | `/api/deployments`, publish staged deployment |
| Credits | `/api/credits`, add/deduct/checkout/webhook |
| Model settings | `/api/model-settings` |
| Integrations | `/api/connectors`, connector status, setup, validation, readiness |

### Platform Operations

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Platform health |
| `GET` | `/ready` | Readiness check |
| `GET` | `/metrics` | Prometheus metrics |
| `POST` | `/mcp` | HTTP MCP bridge |
| `GET` | `/admin/*` | Admin observability, smoke checks, production launch/verification, alerts, logs, git/env/system info |

---

## SSE Events

The session UI is driven by an event stream. Common event types include:

```text
goal_start
plan_done
agent_start
agent_action
agent_action_result
agent_done
agent_error
stack_artifact
approval_required
approval_resolved
goal_done
goal_error
replay_complete
```

---

## Frontend

The frontend is a Next.js 15+ TypeScript app in `frontend/`, with:

- **Pages**: goal creation, session workspace, custom agents, integrations, library, deliverables
- **Real-time updates**: SSE-driven session state, approval gates, progress streams
- **Components**: DashboardView, GoalWorkspace, SessionView, CustomAgentSessionView, LibraryPanel, IntegrationsPage, and specialized tiles/editors
- **Styling**: CSS-in-JS with orbital motion effects, dark/light themes, responsive design
- **Build**: Next.js with TypeScript, uses `docker compose` for local development and production

Run locally:

```bash
cd frontend
npm install
npm run dev
```

Then visit `http://localhost:3000`.

---

## Setup

### Requirements

- Python 3.13+
- Redis, for the default event bus/cache path
- Node.js/npm 18+, used by frontend and generated app builds
- Optional: Supabase, Stripe, GitHub, Vercel, Composio, Google OAuth (Gmail), SendGrid/Resend, Cloudflare, PostHog, Notion, Hunter, Apollo, Klaviyo, Twilio, Square, Printful, Yelp, Lemon Squeezy, browser automation credentials

### Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

### Environment

The backend reads `.env` through `backend/config.py`. Most values are optional for local development, but real agent runs need at least model credentials and any service credentials required by the tools you invoke.

Common variables:

```env
REDIS_URL=redis://localhost:6379
OBSIDIAN_VAULT=~/agent-workspace

OPENROUTER_API_KEY=
AGENT_MODEL_API_KEY=
PLANNER_MODEL_API_KEY=

GITHUB_TOKEN=
VERCEL_TOKEN=
COMPOSIO_API_KEY=
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
RESEND_API_KEY=

ASTRA_REQUIRE_AUTH=false
ASTRA_ALLOW_DEV_AUTH=true
ASTRA_PLATFORM_ADMINS=
```

See [`backend/config.py`](backend/config.py) for the full configuration surface.

---

## Desktop Shell (Optional)

The repo includes an optional Tauri desktop shell in [`desktop/`](/Users/ishaangubbala/Documents/Astra/desktop) for local development:

- Loads the local Next.js dev server for hot reload
- Shares auth and API configuration with the web version
- Requires Rust and Cargo

```bash
cd desktop
npm install
npm run dev
```

Not required for web-only deployments.

The frontend also exposes a desktop installer endpoint at `/api/downloads/desktop`.

- Set `DESKTOP_DOWNLOAD_URL` to redirect the button to a hosted DMG.
- Or set `DESKTOP_DMG_PATH` to serve a local DMG directly from the server filesystem.
- If neither is set, the route falls back to `desktop/src-tauri/target/release/bundle/dmg/Astra Desktop_0.1.0_aarch64.dmg`.

### Run The Backend

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Useful checks:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
curl http://localhost:8000/stacks
```

### Run The Frontend

```bash
cd frontend
npm install
npm run dev
```

Then visit `http://localhost:3000`.

### Run Tests

```bash
pytest
```

### Docker

The backend image is defined in `Dockerfile.backend` and installs Python dependencies, Playwright Chromium, Node/npm, and the OpenClaude CLI used by generated builds.

`docker-compose.yml` defines Redis, backend, frontend (Next.js), and nginx services. Run with:

```bash
docker compose build
docker compose up
```

Then visit `http://localhost` (nginx on port 80 proxies to frontend and API).

---

## Production And Ops

Astra includes operator-facing checks and runbooks under `backend/production_*`, `backend/platform_status.py`, `backend/alerts.py`, `backend/deploy_evidence.py`, and `deploy/`.

Notable surfaces:

- `/health`, `/ready`, `/metrics`
- `/admin/overview`
- `/admin/system`
- `/admin/sessions`
- `/admin/runs`
- `/admin/alerts`
- `/admin/smoke`
- `/admin/production-verification`
- `/admin/production-launch`

Startup jobs also handle interrupted-session recovery, platform alert checks, 30-day PII purge, company-brain scheduling, and mission scheduling.

Key docs:

- [Production Launch Runbook](/Users/ishaangubbala/Documents/Astra/docs/Production_Launch_Runbook.md)
- [Security Alignment Roadmap](/Users/ishaangubbala/Documents/Astra/docs/Security_Alignment_Roadmap.md)
- [Desktop Signing And Release](/Users/ishaangubbala/Documents/Astra/docs/Desktop_Release_Signing.md)

---

## Design Principles

- **Durable by default**: sessions, events, credits, deployments, missions, library files, and workspaces are persisted so the UI can replay state.
- **Founder control**: high-risk actions such as deploys, emails, account actions, and production changes flow through approval gates.
- **Local-first where practical**: many stores are file-backed, with Supabase and external providers layered in where production needs them.
- **Agent stacks over loose prompts**: repeatable business outcomes compile into stack manifests, operating plans, quality gates, connector requirements, and execution blueprints.
- **Observable runs**: token usage, costs, event logs, workboards, digests, completion audits, production checks, and admin endpoints make agent behavior inspectable.

---

## Repository Notes

- The worktree may contain generated artifacts such as `__pycache__`, local previews, vault files, and `.DS_Store`; avoid committing those. See `.gitignore`.
- `_archive/` keeps older orchestrator/agent experiments for reference.
- `proprietary_agent/` and `proprietary-agent/` contain experimental intelligence-layer concepts.
- `frontend/` is the primary Next.js frontend app; `mockup/` contains older static prototypes for reference.
- `desktop/` is an optional Tauri shell for local development; not required for deployment.

---

## License

Proprietary. All rights reserved.
