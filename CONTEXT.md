# Astra — Project Context

## What This Is

Astra is an AI co-founder platform. Founders describe a business goal; an orchestrator decomposes it into specialist agent tasks (research, design, marketing, technical, legal, ops, sales, finance). Agents run autonomously, write outputs to an Obsidian vault, and return structured results.

---

## Architecture

```
Frontend (Next.js 14, App Router)   →   FastAPI backend   →   Agent orchestrator
                                                            ↓
                                              Specialist agents (LLM + tools)
                                                            ↓
                                         Obsidian vault / Supabase / external APIs
```

**Key directories:**
- `backend/core/` — orchestrator, agent loop, session/workspace stores, cancellation, key rotator
- `backend/specialists/` — one file per agent (research, marketing, technical, design, legal, ops, sales, finance, web, + sub-agents)
- `backend/tools/` — all tool functions (browser, LLM, image gen, email, social, legal docs, company brain, etc.)
- `backend/api/routes.py` — all FastAPI endpoints (~2500 lines)
- `backend/stacks/` — stack templates (`idea_to_revenue`, `ecomm`, `local_service`) + readiness checks
- `backend/missions/` — company goal engine, goal store, roadmap
- `backend/provisioning/` — credential store (encrypted per founder), connector validation
- `frontend/components/` — UI (GoalWorkspace, ChecklistPage, SessionView, Terminal tab, etc.)

---

## Model Routing

| Role | Model | Via |
|---|---|---|
| Planner / orchestrator | `deepseek/deepseek-v4-pro` | OpenRouter |
| High-output agents (legal, finance, marketing_content, etc.) | `deepseek/deepseek-v4-pro` | OpenRouter |
| Light agents (research, marketing, design, sales) | `xiaomi/mimo-v2.5` | OpenRouter |
| Technical wrapper | `deepseek/deepseek-v4-pro` | OpenRouter |
| Technical MVP build (openclaude) | `xiaomi/mimo-v2.5-pro` | OpenRouter |
| Web agent | `xiaomi/mimo-v2.5-pro` | OpenRouter |
| Build plan (pre-build spec) | `minimax/minimax-m3` | OpenRouter |
| Research (when local GPU active) | `Qwen3.6-35B-A3B-UD-Q4_K_M.gguf` | Local llama.cpp |
| Image generation | DALL-E 3 / fal.ai | Direct |
| Browser vision loop | `google/gemini-2.5-flash` | OpenRouter |

**Local research model**: when `LOCAL_RESEARCH_BASE_URL` + `LOCAL_RESEARCH_MODEL` set in `.env`, research agents route to the self-hosted llama.cpp endpoint (Cloudflare tunnel). Single GPU = serial inference → only 1 research agent runs (comprehensive all-4-areas pass). On OpenRouter: 4 parallel focused agents (`research`, `research_competitors`, `research_customers`, `research_gtm`).

---

## Stack System

Three stacks select which agents run and which integrations are required:

| Stack | Trigger | Agents | Key integrations |
|---|---|---|---|
| `idea_to_revenue` | SaaS/app ideas | research + design + marketing + technical + web + legal + ops + sales + finance | Vercel, GitHub, Stripe, Resend |
| `ecomm` | E-commerce, physical/digital products | research + design + marketing + ops + legal + finance | Klaviyo, Printful, Lemon Squeezy, Stripe |
| `local_service` | Service businesses, brick-and-mortar | research + marketing + ops + legal + finance | Square, Twilio, Yelp |

Stack inference: `_analyze_goal()` in `routes.py` calls LLM (DeepSeek fast, JSON mode) to return `{stack_id, business_profile}`. The business profile (2-3 sentences) is prepended to the goal instruction so agents have full context. Quiz `contextBlock` bypasses LLM inference (detected by `"---"` in first 80 chars).

---

## Goal Execution Flow

1. Founder submits goal → `POST /goals`
2. `_analyze_goal()` infers stack + generates business profile
3. Orchestrator `_initial_plan()` builds agent roster from stack template tasks
4. Each agent runs in a child session, writes to Obsidian vault, calls `agent_done`
5. Results flow back to orchestrator; outcomes extracted to ledger
6. `company_brain` synced post-run (GraphRAG over all session outputs)

**Force-add rule**: only `idea_to_revenue` stack force-adds `web` + `technical` agents. Other stacks trust their template.

---

## Credential Store

- Per-founder encrypted JSON at `{vault}/credentials/{founder_id}.json`
- Encrypted with `ASTRA_CREDS_KEY` (Fernet, stable key from `.env`)
- `CredentialsUnreadable` raised (not swallowed) when decryption fails — prevents silent overwrite of encrypted data
- Key must be set in `.env` before any write; `_ensure_creds_key()` generates + persists on first write if missing

---

## Server / Deployment

**VPS**: `root@178.105.231.73`

**Repo on server**: `/opt/astra/repo`

**Deploy workflow**:
```bash
# Backend Python change (live-mounted):
docker compose restart backend

# Frontend change:
docker compose build frontend && docker compose up -d frontend

# .env change:
docker compose up -d --force-recreate backend
```

**Containers**: `repo-backend-1`, `repo-frontend-1`, nginx, redis

**Ports**: nginx 80/443 public; backend 8000 (currently 0.0.0.0 — audit finding); frontend 3000

**Durable data**: Obsidian vault volume at `/data/astra_docs` in container — never wipe

---

## Key Config Fields (`.env`)

```
# OpenRouter
OPENROUTER_API_KEY=...
OR_PLANNER_MODEL=deepseek/deepseek-v4-pro
OR_HIGHOUTPUT_MODEL=deepseek/deepseek-v4-pro
OR_LIGHT_MODEL=xiaomi/mimo-v2.5

# Local research GPU (optional — Cloudflare tunnel URL changes on restart)
LOCAL_RESEARCH_BASE_URL=https://<tunnel>.trycloudflare.com/v1
LOCAL_RESEARCH_MODEL=Qwen3.6-35B-A3B-UD-Q4_K_M.gguf
LOCAL_RESEARCH_API_KEY=none

# Credential store (generate once, never change)
ASTRA_CREDS_KEY=<fernet-key>

# Auth (set true in prod)
ASTRA_REQUIRE_AUTH=false

# Obsidian vault
OBSIDIAN_VAULT=~/agent-workspace
```

---

## Recent Architectural Decisions

**LLM stack inference** (replaced keyword regex): `_analyze_goal()` sends full goal to DeepSeek, returns structured `{stack_id, business_profile}`. Profile injected into instruction so all agents understand the business, not just the literal goal text.

**Stack-aware planner**: `_initial_plan()` reads stack template tasks to build agent roster. Previously force-added web+technical to every goal regardless of stack — broke ecomm/local_service goals.

**Parallel research** (4 agents): Each covers one lane (`research`, `research_competitors`, `research_customers`, `research_gtm`). All read from same Obsidian note via `obsidian_read` to skip already-fetched URLs. Single local GPU → 1 comprehensive agent instead.

**Copilot error redaction**: Tool errors (credential issues, API failures) are replaced with `{"ok": false, "note": "tool unavailable"}` before the LLM sees them. Copilot never surfaces internal failures to founders.

**`generate_ad_image` wrapper**: Marketing agent calls `generate_ad_image(prompt=...)` but underlying `generate_image()` requires positional `description`. Wrapper accepts `description`/`prompt`/`concept` aliases.

---

## Security Findings (open)

| Severity | Finding | Status |
|---|---|---|
| 🔴 Critical | Prod API open to internet (`ASTRA_REQUIRE_AUTH=false`, backend on `0.0.0.0:8000`) | Open |
| 🔴 Critical | Founder impersonation via `x-astra-user-id` header (no auth validation) | Open |
| 🟠 High | Root SSH password auth on VPS | Open |
| 🟠 High | SSRF in URL fetchers (`page_fetcher.py`, browser tools) — no private-IP filtering | Open |
| 🟠 High | CORS `allow_origins=["*"]` | Open |
| 🟡 Medium | `.env` injection via `_write_env_key` (newline in value) | Open |
| 🟡 Medium | `/admin/logs` leaks API keys in docker log output | Open |

Fix #1-#2 first: bind backend to `127.0.0.1:8000` in compose + set `ASTRA_REQUIRE_AUTH=true` + add JWT config.

---

## Development Patterns

- Agents are `Agent(name, role, tools, model, ...)` instances built in `backend/specialists/*.py`
- All agents get `company_brain_*` tools injected in `factory.py` after construction
- `obsidian_log` = final step for every agent (writes structured output to vault)
- Tool files follow pattern: thin HTTP wrappers with `settings.*` for credentials
- New connectors need: tool file + `config.py` fields + `connector_validation.py` + `stacks/readiness.py`
- MVPs built via `run_mvp_loop` (openclaude CLI, `--print` mode, session ID persisted to `.oc_session_id`)
- Research agents auto-log every tool result to Obsidian via `_make_auto_logging_tool` wrappers
