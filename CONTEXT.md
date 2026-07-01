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

The production deployment is containerized and fronted by a reverse proxy. Hostnames, server access details, deploy shortcuts, and persistent-volume locations are intentionally kept out of tracked docs and maintained in a local private operator note.

Durable storage must live outside ephemeral containers, and deployment changes should preserve workspace, vault, and evidence data.

---

## Key Config Fields (`.env`)

Keep model credentials, connector tokens, encryption keys, tunnel URLs, and environment-specific auth settings in local untracked env files only. Use `backend/config.py` as the source of truth for the available configuration surface.

---

## Recent Architectural Decisions

**LLM stack inference** (replaced keyword regex): `_analyze_goal()` sends full goal to DeepSeek, returns structured `{stack_id, business_profile}`. Profile injected into instruction so all agents understand the business, not just the literal goal text.

**Stack-aware planner**: `_initial_plan()` reads stack template tasks to build agent roster. Previously force-added web+technical to every goal regardless of stack — broke ecomm/local_service goals.

**Parallel research** (4 agents): Each covers one lane (`research`, `research_competitors`, `research_customers`, `research_gtm`). All read from same Obsidian note via `obsidian_read` to skip already-fetched URLs. Single local GPU → 1 comprehensive agent instead.

**Copilot error redaction**: Tool errors (credential issues, API failures) are replaced with `{"ok": false, "note": "tool unavailable"}` before the LLM sees them. Copilot never surfaces internal failures to founders.

**`generate_ad_image` wrapper**: Marketing agent calls `generate_ad_image(prompt=...)` but underlying `generate_image()` requires positional `description`. Wrapper accepts `description`/`prompt`/`concept` aliases.

---

## Security Findings (open)

Tracked docs keep the long-lived remediation roadmap in [`docs/Security_Alignment_Roadmap.md`](/Users/ishaangubbala/Documents/Astra/docs/Security_Alignment_Roadmap.md). Environment-specific findings, host-level exposure notes, and active incident-response details live in local private operational notes instead.

Current hardening priorities remain:

- production auth enforcement on all privileged surfaces
- outbound fetch and browser protections against private-network access
- secret handling that avoids plaintext persistence and log leakage

---

## Development Patterns

- Agents are `Agent(name, role, tools, model, ...)` instances built in `backend/specialists/*.py`
- All agents get `company_brain_*` tools injected in `factory.py` after construction
- `obsidian_log` = final step for every agent (writes structured output to vault)
- Tool files follow pattern: thin HTTP wrappers with `settings.*` for credentials
- New connectors need: tool file + `config.py` fields + `connector_validation.py` + `stacks/readiness.py`
- MVPs built via `run_mvp_loop` (openclaude CLI, `--print` mode, session ID persisted to `.oc_session_id`)
- Research agents auto-log every tool result to Obsidian via `_make_auto_logging_tool` wrappers
