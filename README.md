# Astra — AI Founding Team

Astra turns a single plain-English instruction into a coordinated company-building operation. Six specialized AI agents run in parallel — doing market research, drafting legal documents, deploying landing pages, scaffolding codebases, creating marketing content, and managing operations — without any further input from the founder.

---

## What It Does

Submit one goal. Astra plans, dispatches, and executes across six domains simultaneously:

| Agent | What It Produces |
|---|---|
| **Research** | Market sizing, competitor analysis, TAM/SAM/SOM, customer profile, data sources |
| **Legal** | NDAs, privacy policies, terms of service, founder agreements — full PDFs |
| **Web** | Landing page designed and deployed to Vercel, GitHub repo created |
| **Marketing** | Instagram Reels scripts, TikTok content, Meta ad copy, email campaigns |
| **Technical** | Full codebase scaffolded via Claude Code CLI, Linear tickets, Notion pages |
| **Ops** | Executive summary, investor outreach emails, fundraising docs, SOPs |

Everything runs in under 15 minutes. Results are streamed live to the dashboard and logged to an Obsidian vault.

---

## Architecture

```
POST /goal
    │
    ▼
Orchestrator (planner LLM)
    │  Decomposes goal into agent tasks with dependency order
    ▼
Wave Scheduler (asyncio.gather)
    │
    ├── research agent ──────────────────────────────────┐
    │                                                    │
    ├── (waits for research) ──────────────────────────  │
    │       ├── web agent                                │
    │       ├── legal agent                              │  parallel
    │       ├── marketing agent                          │
    │       └── technical agent                          │
    │                                                    │
    └── ops agent (runs last, sees all results) ─────────┘
    │
    ▼
SSE stream → Next.js dashboard (live agent cards)
    │
    ▼
Obsidian vault (persistent session notes per agent)
```

Each agent is a hand-rolled agentic loop:
1. LLM receives system prompt + tool schemas
2. LLM outputs tool call
3. Tool executes, result appended to messages
4. Repeat until `done` called or 20-iteration cap hit

No LangChain. No LlamaIndex. No Agents SDK. Raw OpenAI-compatible chat completions + tool dispatch.

---

## Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI, Python 3.13, asyncio |
| Frontend | Next.js 16, Tailwind CSS v4, SSE streaming |
| LLM | Llama 3.3 70B Instruct Turbo via DeepInfra ($0.10 in / $0.32 out per 1M) |
| Database | Supabase (PostgreSQL) |
| Memory | Obsidian vault at `~/agent-workspace/` |
| OAuth Tools | Composio (Gmail, LinkedIn, GitHub, Linear, Notion, Google Calendar) |
| Deploy | Vercel (landing pages), GitHub (repos + scaffolding via Claude Code CLI) |
| Docs | ReportLab (PDF generation) |
| Search | SerpAPI / DuckDuckGo web search |

---

## Agent Tools

**Research:** `web_search`, `news_search`, `patent_search`, `obsidian_log`

**Legal:** `format_legal_document`, `generate_pdf`, `obsidian_log`

**Web:** `generate_landing_page_html`, `vercel_deploy`, `github_create_repo`, `web_search`, `obsidian_log`

**Marketing:** `generate_reel_package`, `generate_tiktok_package`, `generate_meta_ad`, `send_email_campaign`, `obsidian_log`

**Technical:** `github_create_repo`, `claude_code_scaffold`, `composio_linear_create_issue`, `composio_notion_create_page`, `obsidian_log`

**Ops:** `generate_pdf`, `send_email_campaign`, `composio_linear_create_issue`, `composio_notion_create_page`, `obsidian_log`

---

## Key Design Decisions

**One-shot tool guard** — Expensive tools (`format_legal_document`, `vercel_deploy`, `claude_code_scaffold`) are hard-blocked after first successful execution per session. Prevents the LLM from calling them twice and doubling cost/time.

**Iteration pressure** — After iteration 5, the agent receives a message nudging it toward `done`. Prevents infinite tool loops.

**Claude Code CLI scaffold** — Technical agent clones the GitHub repo, runs Claude Code non-interactively inside it, then commits and pushes. Produces 20-30 real files with working code, not stubs.

**Obsidian vault** — Each agent writes structured session notes. Prior notes are loaded before each new run, giving agents cross-session memory without a vector database.

**Vercel deploy** — Fetches the Vercel team ID dynamically before each deploy (required for hobby accounts). Landing page HTML generated from a premium dark-theme template, optionally enhanced by LLM with no token cap.

**No token caps in the wrapper** — `_llm.py` never sets `max_tokens`. Limits are the responsibility of individual callers when needed.

---

## Proprietary Intelligence Layer

Four compounding systems under `proprietary-agent/` that make Astra smarter with every run:

- **Causal Decision Graph** — NetworkX graph tracking every agent decision, its causes, and outcomes. Agents query it before acting. Becomes a queryable company brain over time.
- **Silent Observer** — 24/7 background agent monitoring competitor activity, regulatory changes, and industry signals. Surfaces proactive alerts without being asked.
- **Execution Fingerprinting** — Every run compressed into a fingerprint. New runs matched against history: "78% similar to a run that succeeded — here's what worked and what failed."
- **Founder Mirror** — Adversarial agent that attacks every specialist output before it ships. Returns pass/flag/block verdict. Forces outputs to survive scrutiny.

See `proprietary-agent/README.md` for full design.

---

## Setup

### Requirements

- Python 3.13+
- Node.js 20+
- Redis (for SSE event bus)
- Supabase project

### Install

```bash
# Backend
pip install -r requirements.txt

# Frontend
cd frontend && npm install
```

### Environment

```bash
cp .env.example .env
```

Required variables:

```env
SUPABASE_URL=
SUPABASE_KEY=
REDIS_URL=redis://localhost:6379
AGENT_MODEL_BASE_URL=https://api.deepinfra.com/v1/openai
AGENT_MODEL_API_KEY=
AGENT_MODEL_NAME=meta-llama/Llama-3.3-70B-Instruct-Turbo
COMPOSIO_API_KEY=
GITHUB_TOKEN=
VERCEL_TOKEN=
SENDGRID_API_KEY=
```

### Run

```bash
# Backend (port 8000)
python -m uvicorn backend.main:app --port 8000 --reload

# Frontend (port 3000)
cd frontend && npm run dev
```

Open `http://localhost:3000`, enter a goal, click Launch.

---

## API

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/goal` | Submit a goal, returns `session_id` |
| `GET` | `/stream/{session_id}` | SSE stream of agent events |
| `GET` | `/status/{goal_id}` | Goal + task status from DB |
| `POST` | `/setup` | Provision GitHub/Vercel/SendGrid accounts |
| `GET` | `/setup/{founder_id}` | Check which services are connected |
| `GET` | `/setup/composio/connect/{founder_id}` | Get OAuth URLs for Composio apps |

### SSE Event Types

```
goal_start           — run acknowledged
plan_done            — planner finished, tasks list available
agent_start          — specialist began
agent_action         — tool call in progress
agent_action_result  — tool returned
agent_done           — specialist finished, result available
goal_done            — all agents complete
goal_error           — unrecoverable failure
```

---

## Project Structure

```
Astra/
├── backend/
│   ├── core/
│   │   ├── agent.py           # Agentic loop — LLM + tool dispatch
│   │   ├── orchestrator.py    # Planner + wave scheduler
│   │   ├── factory.py         # Singleton orchestrator with all specialists
│   │   ├── events.py          # SSE pub/sub via Redis
│   │   └── bus.py             # Agent message bus
│   ├── specialists/
│   │   ├── research.py
│   │   ├── legal.py
│   │   ├── web.py
│   │   ├── marketing.py
│   │   ├── technical.py
│   │   └── ops.py
│   ├── tools/
│   │   ├── _llm.py            # Sync LLM wrapper (no token cap)
│   │   ├── vercel_deploy.py   # Landing page generation + Vercel deploy
│   │   ├── claude_scaffold.py # Claude Code CLI repo scaffolding
│   │   ├── github_scaffold.py # GitHub repo creation
│   │   ├── doc_generator.py   # Legal document generation
│   │   ├── pdf_generator.py   # PDF rendering via ReportLab
│   │   ├── social_content.py  # Reels, TikTok, Meta ad copy
│   │   ├── email_campaign.py  # SendGrid email campaigns
│   │   ├── web_search.py      # Web + news search
│   │   ├── patent_search.py   # Patent search
│   │   ├── composio_tools.py  # OAuth tool execution via Composio
│   │   └── obsidian_logger.py # Vault read/write/append
│   ├── api/
│   │   └── routes.py
│   ├── db/
│   │   └── client.py          # Supabase client + goal/task helpers
│   └── provisioning/
│       ├── account_provisioner.py
│       └── credentials_store.py
├── frontend/
│   └── app/
│       ├── page.tsx            # Goal submission
│       ├── goal/[id]/page.tsx  # Live agent dashboard
│       └── setup/page.tsx      # Account connection
├── proprietary-agent/          # Compounding intelligence layer
├── supabase/                   # Schema migrations
└── tests/
```

---

## Cost

A full 6-agent run costs approximately **$0.03–0.08** in LLM tokens at current DeepInfra pricing for Llama 3.3 70B Turbo. Claude Code scaffold (technical agent) uses Anthropic credits separately.

---

## License

Proprietary. All rights reserved.
