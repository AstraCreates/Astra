# Proprietary Agent Intelligence Layer — Build Spec

What we're building, why, and exactly how each system works.

---

## The Astra Agent Harness

### Problem With The Current Loop

`backend/core/agent.py` is a hand-rolled loop: call LLM → parse tool call → execute → repeat. It works but it's fragile, has no observability, no security layer, no multi-model routing, and no structured output validation. Every agent runs on the same model with the same retry logic with no ability to swap, fallback, or audit.

### What We're Building Instead

A proprietary agentic harness. Not from scratch — that's wasted effort. The right approach is to own the loop logic, security, and observability while standing on proven infrastructure for the parts that are commodity:

```
┌─────────────────────────────────────────────────────────┐
│                  Astra Agent Harness                     │
│                                                         │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │  Loop Core  │  │  Tool Layer  │  │  Observability │  │
│  │  (custom)   │  │  (custom)    │  │  (custom)      │  │
│  └──────┬──────┘  └──────┬───────┘  └───────┬───────┘  │
│         │                │                   │           │
│  ┌──────▼──────────────────────────────────▼─────────┐  │
│  │              LiteLLM Router (commodity)            │  │
│  │  100+ models, fallbacks, spend tracking, retries   │  │
│  └────────────────────────────────────────────────────┘  │
│         │                │                               │
│  ┌──────▼──────┐  ┌──────▼──────────────────────────┐   │
│  │  Instructor │  │  Composio + MCP + Direct APIs    │   │
│  │  (struct.   │  │  200+ app integrations           │   │
│  │  outputs)   │  └─────────────────────────────────┘   │
│  └─────────────┘                                         │
└─────────────────────────────────────────────────────────┘
```

### Layer Decisions

**LiteLLM as the model router (not from scratch)**
- Supports 100+ providers: OpenAI, Anthropic, DeepInfra, Groq, Mistral, Vertex, Bedrock, local Ollama
- Per-agent model assignment: research runs on Llama 3.3, legal runs on Claude Sonnet, web runs on whatever is fastest at deploy time
- Automatic fallback: if DeepInfra is down, route to Groq without code changes
- Built-in spend tracking per agent, per session, per founder
- Rate limiting and budget caps per founder
- We own the agent loop that calls LiteLLM — we don't use LiteLLM's agent abstractions

**Instructor for structured outputs (not from scratch)**
- Forces every LLM response into a validated Pydantic model
- No more manual JSON parsing or tool call extraction
- Tool calls become typed function signatures — if the model hallucinates a field, Instructor catches it and retries
- Works on top of LiteLLM so we get both benefits

**Custom loop logic (proprietary)**
- Tool dispatch, iteration control, one-shot guards
- Security validation before every tool execution
- Output sanitization before returning to LLM context
- Integration with the four intelligence systems (graph, observer, fingerprints, mirror)
- Streaming event emission at every step

**Composio + MCP + direct APIs (integrations layer)**
- Composio already integrated: Gmail, LinkedIn, GitHub, Linear, Notion, Calendar (200+ apps)
- MCP (Model Context Protocol) — Anthropic's emerging standard for agent↔tool communication. Add an MCP server layer so any MCP-compatible tool works with zero integration code
- Direct APIs for latency-critical tools: Vercel, GitHub repos, SendGrid (bypass Composio overhead)

### Security Layer (proprietary)

This is where we build real moat. No one else has per-tool, per-agent, per-founder security enforcement at the loop level.

```python
class ToolSecurityLayer:
    def validate_call(self, agent: str, tool: str, args: dict, founder_id: str) -> ValidationResult:
        # 1. Allowlist check — agent can only call its declared tools
        if tool not in AGENT_TOOL_ALLOWLIST[agent]:
            return ValidationResult.block(f"{agent} is not permitted to call {tool}")

        # 2. Input sanitization — strip prompt injection attempts
        args = self._sanitize_inputs(args)

        # 3. Founder isolation — tool cannot access another founder's data
        if "founder_id" in args and args["founder_id"] != founder_id:
            return ValidationResult.block("Cross-founder data access denied")

        # 4. Rate limit — per tool per founder per hour
        if self._rate_exceeded(founder_id, tool):
            return ValidationResult.block(f"{tool} rate limit exceeded for this founder")

        # 5. Destructive action check — flag any tool that writes external state
        if tool in DESTRUCTIVE_TOOLS:
            return ValidationResult.flag("Destructive tool — logging for audit")

        return ValidationResult.allow(args)

    def sanitize_output(self, tool: str, result: dict) -> dict:
        # Strip secrets, tokens, PII from tool results before they enter LLM context
        return self._redact_sensitive_fields(result)
```

**Tool allowlists per agent — hardcoded, not LLM-configurable:**
```python
AGENT_TOOL_ALLOWLIST = {
    "research":   {"web_search", "news_search", "patent_search", "obsidian_log", "obsidian_read", "done"},
    "legal":      {"format_legal_document", "generate_pdf", "obsidian_log", "obsidian_read", "done"},
    "web":        {"generate_landing_page_html", "vercel_deploy", "github_create_repo", "web_search", "obsidian_log", "obsidian_read", "done"},
    "marketing":  {"generate_reel_package", "generate_tiktok_package", "generate_meta_ad", "send_email_campaign", "obsidian_log", "obsidian_read", "done"},
    "technical":  {"github_create_repo", "claude_code_scaffold", "composio_linear_create_issue", "composio_notion_create_page", "obsidian_log", "obsidian_read", "done"},
    "ops":        {"generate_pdf", "send_email_campaign", "composio_linear_create_issue", "composio_notion_create_page", "obsidian_log", "obsidian_read", "done"},
}
```

### Per-Agent Model Routing

Different tasks call for different models. LiteLLM makes this free:

```python
AGENT_MODELS = {
    "research":   "deepinfra/meta-llama/Llama-3.3-70B-Instruct-Turbo",  # fast, cheap
    "legal":      "anthropic/claude-sonnet-4-5",                         # best reasoning, high stakes
    "web":        "deepinfra/meta-llama/Llama-3.3-70B-Instruct-Turbo",  # fast
    "marketing":  "deepinfra/meta-llama/Llama-3.3-70B-Instruct-Turbo",  # creative, fast
    "technical":  "anthropic/claude-sonnet-4-5",                         # code quality matters
    "ops":        "deepinfra/meta-llama/Llama-3.3-70B-Instruct-Turbo",  # structured output, fast
    "mirror":     "anthropic/claude-sonnet-4-5",                         # adversarial needs best model
    "planner":    "deepinfra/meta-llama/Llama-3.3-70B-Instruct-Turbo",  # fast planning
}

AGENT_MODEL_FALLBACKS = {
    "legal":     ["openai/gpt-4o", "deepinfra/meta-llama/Llama-3.3-70B-Instruct-Turbo"],
    "technical": ["openai/gpt-4o", "deepinfra/meta-llama/Llama-3.3-70B-Instruct-Turbo"],
    "mirror":    ["openai/gpt-4o", "deepinfra/meta-llama/Llama-3.3-70B-Instruct-Turbo"],
}
```

### Observability (proprietary)

Every LLM call, tool execution, and agent event is traced with full context. Built in-house — no Langfuse, no Helicone, no DataDog. Stored in Supabase.

```python
@dataclass
class AgentTrace:
    session_id: str
    agent: str
    iteration: int
    event_type: str          # "llm_call" | "tool_call" | "tool_result" | "done"
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    tool_name: str | None
    tool_args: dict | None
    tool_result: dict | None
    error: str | None
    timestamp: str
```

Dashboard query: "Show me every tool call that took > 60s in the last 30 days, grouped by agent." Answer in milliseconds from Supabase.

### MCP Integration

MCP (Model Context Protocol) is the emerging standard for agent↔tool communication — Anthropic, OpenAI, and Google are all aligning on it. Build an MCP server layer now so any MCP-compatible tool (from any vendor) works with Astra agents with zero integration code.

```python
class MCPToolBridge:
    """Wraps any MCP server as a native Astra tool."""
    async def discover_tools(self, mcp_server_url: str) -> list[AstraTool]:
        # Connect to MCP server, fetch tool schemas
        # Return as native Astra tools — agents see no difference

    async def call(self, tool_name: str, args: dict) -> dict:
        # Route call to appropriate MCP server
        # Apply security layer before and after
```

When a new MCP tool ships (Stripe, Salesforce, Shopify, etc.), it works with Astra in minutes — not weeks of integration work.

### New Dependencies

```
litellm>=1.40
instructor>=1.3
mcp>=1.0          # when stable
```

### What This Gives Us

| Capability | Current | With Harness |
|---|---|---|
| Model providers | 1 (DeepInfra) | 100+ via LiteLLM |
| Per-agent models | No | Yes — legal on Claude, others on Llama |
| Structured outputs | Manual JSON parse | Pydantic-validated via Instructor |
| Tool security | None | Allowlist + rate limit + sanitization |
| Fallbacks | None | Automatic per-agent |
| Observability | SSE events only | Full trace per LLM call and tool |
| Tool integrations | ~15 custom + Composio | Composio + MCP (unbounded) |
| Spend tracking | None | Per agent, per founder, per session |

### What Stays Proprietary

- The loop logic and iteration control
- The security validation layer
- The intelligence systems (A/E/F/G)
- The per-agent model routing config
- The observability schema and queries
- The tool allowlists

LiteLLM and Instructor are open source primitives — the value we build on top of them is not.

---

## The Problem With Current Astra

Every run starts cold. Agents have no memory of prior decisions beyond flat Obsidian notes. There's no learning between sessions, no cross-founder pattern recognition, no proactive intelligence, and no quality gate before outputs ship. The system is as smart on run 100 as it was on run 1.

This layer fixes that. Four systems that compound with every run.

---

## System A — Causal Decision Graph

### What
A persistent directed graph where every agent decision is a node connected to what caused it and what it caused. Not a log — a living knowledge structure that agents query before acting and write to after completing.

### Why
After 10 runs, Astra knows WHY things were decided, not just what was decided. After 50 runs it knows which decisions held, which got reversed, and what external events triggered changes. No other platform builds causal memory — they build flat logs. The graph IS the moat because it's founder-specific and time-compounding.

### Data Model

```
Node types:
  decision      — a choice an agent made (e.g. "chose Delaware C-Corp")
  entity        — a named thing (company, person, competitor, product, market)
  outcome       — a result that happened (e.g. "investor term sheet received")
  agent_action  — a tool call with its result
  external_event — something the Silent Observer detected

Edge types:
  triggered_by  — this decision was caused by X
  led_to        — this decision caused Y
  contradicts   — this decision conflicts with prior decision Z
  supports      — this decision reinforces prior decision Z
  invalidates   — new information makes prior decision Z obsolete
  references    — this node is about entity X
```

### Storage
- NetworkX DiGraph, serialized to disk as JSON per founder
- Path: `.graph/{founder_id}.json`
- Loaded at session start, written at session end
- Append-only during a run (no mid-run rewrites)

### Agent Interface

```python
# Before acting — agent gets relevant prior context
context = graph.query_relevant(
    founder_id="founder_001",
    query="legal entity structure",
    limit=5
)
# Returns: list of decision nodes with their causal chains

# After acting — agent writes what it decided
graph.add_decision(
    founder_id="founder_001",
    agent="legal",
    session_id="abc123",
    decision="Drafted Delaware C-Corp incorporation agreement",
    reasoning="Founder indicated intent to raise institutional capital",
    triggered_by=["research:market_analysis_abc123"],
    entities=["Delaware", "C-Corp"],
)
```

### Query Strategy
- Keyword overlap between query and node `decision` field
- Walk edges backward: surface nodes that led to current context
- Return top-N by recency × relevance score
- No vector embeddings — pure graph traversal + keyword match

### What Agents Get
Injected into system prompt before each run:

```
[DECISION GRAPH — prior context for legal agent]
Session 2026-05-01: Chose Delaware C-Corp over LLC
  Reason: Planning to raise institutional capital
  Outcome: Investor term sheet received 2026-05-15 ✓
  Note: Same structure rejected by investor in session 2026-03-08 (solo founder, no traction)

Session 2026-04-20: Rejected NDA with 5-year non-compete
  Reason: Founder said "too aggressive for early-stage partnerships"
  Outcome: Partner signed modified 2-year version ✓
```

---

## System E — Silent Observer

### What
A background asyncio task that runs on a schedule (every 6 hours by default) without the founder asking. Monitors competitor activity, funding announcements, regulatory changes, job board signals, and industry news across all active founder domains. Surfaces relevant alerts proactively.

### Why
Every other agent platform waits to be asked. Silent Observer flips this. The founder doesn't need to know what to ask — Astra already watched the world on their behalf while they slept. Over time, the Observer learns which signals each founder actually acted on and adjusts its relevance scoring accordingly.

### Architecture

```python
class SilentObserver:
    async def run_cycle(self, founder_id: str):
        # 1. Load founder's active goals and entities from graph
        context = graph.get_founder_context(founder_id)

        # 2. Build targeted search queries from context
        queries = self._build_queries(context)

        # 3. Execute searches (reuses existing web_search tool)
        findings = await self._search_all(queries)

        # 4. Deduplicate against seen content hashes
        new_findings = self._dedup(findings, founder_id)

        # 5. Score relevance against founder context
        scored = self._score_relevance(new_findings, context)

        # 6. Write high-relevance findings to graph as external_event nodes
        for finding in scored:
            if finding.relevance > 0.7:
                graph.add_external_event(founder_id, finding)

        # 7. Queue alerts for high-relevance findings
        await self._queue_alerts(founder_id, scored)
```

### What It Monitors
- Competitor funding, product launches, pricing changes
- Regulatory filings relevant to the founder's industry
- Job postings at competitors (signal of strategic direction)
- Patent filings in the founder's space
- News mentions of entities in the founder's graph

### Relevance Scoring
- Keyword overlap with founder's active entities (companies, markets, people)
- Recency weight (last 24h = 1.0, last week = 0.6, last month = 0.3)
- Action weight: findings the founder previously acted on boost similar future findings
- Threshold: only surface findings with score > 0.7

### Alert Format

```
[Silent Observer — 2026-05-24 06:14 AM]
Competitor "RangeLead" raised $2.1M seed (TechCrunch)
  Relevance: 0.91 — matches your active entity "RangeLead" and goal "getweb platform"
  Implication: Competitor is now funded; timeline pressure increased
  Suggested action: Accelerate landing page launch, differentiate on verified contact data
  Source: https://techcrunch.com/...
```

### Learning Loop
After each alert, track whether the founder's next session addressed it.
- Addressed within 2 sessions → increase weight for similar signals
- Never addressed → decrease weight, eventually stop surfacing that signal type

---

## System F — Execution Fingerprinting

### What
Every completed Astra run is compressed into a structured fingerprint stored in SQLite. When a new run begins, the fingerprint engine matches the goal against historical runs and surfaces what worked and what failed in similar situations — before execution starts.

### Why
Astra stops estimating and starts predicting based on production evidence. "Claude Code scaffold takes 8 minutes for FastAPI + Next.js projects" is now a fact derived from 20 prior runs, not a guess. Planner adjusts timing, tool selection, and dependency order based on historical performance.

### Fingerprint Schema

```sql
CREATE TABLE fingerprints (
    id TEXT PRIMARY KEY,
    founder_id TEXT,
    session_id TEXT,
    goal_text TEXT,
    goal_vector TEXT,          -- JSON: TF-IDF sparse vector
    agents_used TEXT,          -- JSON: ["research", "web", "technical"]
    tool_outcomes TEXT,        -- JSON: {"vercel_deploy": "success", "format_legal_document": "timeout"}
    tool_timings TEXT,         -- JSON: {"claude_code_scaffold": 487, "vercel_deploy": 23}
    agent_timings TEXT,        -- JSON: {"research": 65, "web": 142, "technical": 510}
    success_score REAL,        -- 0.0–1.0: did agents complete and produce real outputs
    goal_type TEXT,            -- "saas", "marketplace", "agency", "ecommerce", etc.
    timestamp TEXT,
    elapsed_seconds REAL
);
```

### Vectorization
- TF-IDF on goal text using a vocabulary built from all prior goals
- No external API — pure Python `sklearn.feature_extraction.text.TfidfVectorizer`
- Updated after every run as vocabulary grows

### Matching Algorithm

```python
def match(self, goal: str, top_n: int = 3) -> list[FingerprintMatch]:
    query_vec = self.vectorizer.transform([goal])
    
    # Cosine similarity on goal vectors
    goal_scores = cosine_similarity(query_vec, self.goal_matrix)
    
    # Jaccard similarity on agents_used sets
    agent_scores = self._jaccard_agents(goal)
    
    # Combined score
    combined = 0.7 * goal_scores + 0.3 * agent_scores
    
    top_indices = combined.argsort()[-top_n:][::-1]
    return [self.fingerprints[i] for i in top_indices if combined[i] > 0.55]
```

### What the Orchestrator Gets Before Each Run

```
[FINGERPRINT MATCH — 78% similar to session d2e410a3]
Goal: "SaaS platform for businesses without websites" (2026-05-20)
  ✓ claude_code_scaffold: 487s, 30 files, success
  ✓ vercel_deploy: 23s, deployed to production
  ✗ format_legal_document: called twice, 2nd call blocked by one-shot guard (127s wasted)
  ✗ research: 9 searches before done, 4 were redundant
  Adjusted plan: cap research at 3 searches, pre-warn legal agent about one-shot guard
  Estimated total time: 14 min (vs 13.5 min actual on matched run)
```

### Success Score Calculation

```python
def score_run(results: dict) -> float:
    score = 0.0
    for agent, result in results.items():
        if not result:
            continue
        if result.get("error"):
            score += 0.0
        elif result.get("deployed") or result.get("commit") or result.get("generated"):
            score += 1.0  # concrete artifact produced
        else:
            score += 0.5  # completed but no verifiable artifact
    return score / len(results) if results else 0.0
```

---

## System G — Founder Mirror

### What
A dedicated adversarial agent that runs after every specialist and attacks its output. Not a reviewer — a red-teamer. Its only job is to find what's wrong, weak, or likely to fail. Returns a structured verdict: `pass`, `flag`, or `block`. Critique is stored in the decision graph.

### Why
Every other platform ships whatever the agent produces. Mirror forces outputs to survive adversarial scrutiny before they reach the founder. Over time, the quality bar rises because agents (via prompt engineering iteration) learn what passes the Mirror. The critique history in the graph is an audit trail of every near-miss.

### Architecture

```python
class FounderMirror:
    def review(self, agent: str, output: dict, goal: str) -> MirrorVerdict:
        prompt = self._build_prompt(agent, output, goal)
        response = llm.generate(prompt)
        return self._parse_verdict(response)

    def _build_prompt(self, agent: str, output: dict, goal: str) -> str:
        questions = AGENT_ATTACK_QUESTIONS[agent]
        return f"""You are a brutally honest advisor reviewing AI agent output.
Goal: {goal}
Agent: {agent}
Output: {json.dumps(output, indent=2)}

Attack this output. Ask:
{questions}

Return JSON:
{{
  "verdict": "pass" | "flag" | "block",
  "critique": "what specifically is wrong or weak",
  "questions": ["unanswered question 1", "unanswered question 2"],
  "revised_recommendation": "what the agent should do instead"
}}

verdict=pass: output survives scrutiny
verdict=flag: output is weak but acceptable, founder should know
verdict=block: output has a critical flaw, must be revised"""
```

### Attack Questions Per Agent

```python
AGENT_ATTACK_QUESTIONS = {
    "research": """
- Is this market size number credible? What's the primary source quality?
- What did you NOT find that a real analyst would have found?
- Are the competitors actually competing in this exact space or adjacent?
- What assumption in this analysis would kill the business if wrong?""",

    "legal": """
- Does any clause in this document expose the founder to unexpected liability?
- What would a Series A investor's lawyer flag immediately?
- Is the entity structure correct for the stated fundraising intent?
- What's missing that would make this unenforceable?""",

    "web": """
- Would a real customer who has never heard of this product understand the headline in 3 seconds?
- Is any value prop generic enough to apply to 5 competitors?
- What would make someone close this tab in the first 5 seconds?
- Is the CTA specific enough to drive action or just a generic button?""",

    "marketing": """
- Who specifically is this content for? Name the person, not the demographic.
- What makes this different from content any SaaS company would post?
- Would this stop a scroll or get ignored? Why?
- What claim in this content is unsubstantiated?""",

    "technical": """
- Is this scaffold production-ready or a demo that breaks at 100 users?
- What's the first thing that fails when a real developer clones and runs this?
- What security vulnerability is most obvious in this architecture?
- What's missing that would make this actually shippable?""",

    "ops": """
- What's the single biggest operational risk not addressed here?
- Is the fundraising narrative specific enough to pass a first VC filter?
- What would make an investor say 'come back in 6 months'?
- What's the weakest assumption in the execution plan?""",
}
```

### Verdict Thresholds

| Verdict | Meaning | Action |
|---|---|---|
| `pass` | Output survives scrutiny | Proceed, log critique to graph |
| `flag` | Output is weak but acceptable | Proceed, founder notified in dashboard |
| `block` | Critical flaw detected | Agent must revise before proceeding (max 1 retry) |

### What Gets Stored in Graph

```python
graph.add_edge(
    from_node=agent_action_node_id,
    to_node=mirror_verdict_node_id,
    edge_type="mirror_review",
    data={
        "verdict": "flag",
        "critique": "Headline is generic...",
        "questions": [...],
    }
)
```

---

## engine.py — Integration Point

### How It Plugs Into the Orchestrator

```python
from proprietary_agent.engine import ProprietaryEngine

engine = ProprietaryEngine(founder_id=founder_id)

# 1. Pre-run: load intelligence
pre_context = await engine.pre_run(goal=instruction, session_id=session_id)
# Returns: {graph_context, fingerprint_matches, observer_alerts}
# Injected into every agent's shared state

# 2. Run: Mirror wraps each agent
# Orchestrator calls engine.mirror_check(agent, output) after each specialist
# Flag → append to SSE stream
# Block → re-run agent with critique injected (1 retry max)

# 3. Post-run: write everything back
await engine.post_run(
    session_id=session_id,
    goal=instruction,
    results=results,
    elapsed=elapsed_seconds,
)
# Writes: graph nodes, fingerprint record, observer learning signal
```

### Pre-Run Context Format (injected into agent system prompts)

```
[ASTRA INTELLIGENCE — session abc123]

DECISION GRAPH (relevant prior decisions):
  [content from graph.query_relevant()]

FINGERPRINT MATCH (similar past runs):
  [content from fingerprinter.match()]

OBSERVER ALERTS (pending intelligence):
  [content from observer.get_pending_alerts()]
```

---

## Ruflo Compatibility

Ruflo is an MCP-based multi-agent orchestration platform. Astra's proprietary harness must be compatible so agents can run inside Ruflo swarms, use Ruflo's AgentDB memory, and expose tools via MCP.

### What Ruflo Provides That We Use

| Ruflo Feature | How Astra Uses It |
|---|---|
| MCP tool registry (~210 tools) | Expose each Astra agent as an MCP tool via `agent_spawn` |
| AgentDB (HNSW vector memory) | Replace/augment Obsidian vault — agents write to named namespaces |
| SONA self-learning | Feed agent outcomes into trajectory tracker for pattern improvement |
| Multi-provider routing | Supplement LiteLLM — Ruflo handles Claude/GPT/Gemini failover |
| Swarm coordination (Raft consensus) | Orchestrator delegates to Ruflo queen when running parallel swarms |
| Memory namespace isolation | Per-founder, per-agent namespaces prevent cross-contamination |
| 27 hooks + 12 auto-workers | Hook Silent Observer into Ruflo's background worker system |

### MCP Exposure — Each Astra Agent As A Tool

```python
# Each specialist registers as an MCP tool
# Ruflo can spawn them like any other agent_spawn call

MCP_TOOL_MANIFEST = {
    "astra_research":   {"description": "Market research, TAM/SAM/SOM, competitor analysis"},
    "astra_legal":      {"description": "Legal document drafting, entity setup, PDF generation"},
    "astra_web":        {"description": "Landing page generation and Vercel deployment"},
    "astra_marketing":  {"description": "Social content, ad copy, email campaigns"},
    "astra_technical":  {"description": "Codebase scaffolding via Claude Code, Linear/Notion"},
    "astra_ops":        {"description": "Executive summaries, fundraising docs, investor outreach"},
    "astra_mirror":     {"description": "Adversarial quality review — returns pass/flag/block"},
    "astra_observer":   {"description": "Proactive intelligence monitoring and alerts"},
}
```

### AgentDB Memory Integration

```python
# Instead of (or alongside) Obsidian flat files
# Agents write to Ruflo's HNSW-indexed vector store

class RufloMemoryAdapter:
    def write(self, agent: str, founder_id: str, session_id: str, content: dict):
        namespace = f"astra_{founder_id}_{agent}"
        agentdb.upsert(namespace=namespace, doc=content, session_id=session_id)

    def query(self, agent: str, founder_id: str, query: str, top_k: int = 5):
        namespace = f"astra_{founder_id}_{agent}"
        return agentdb.search(namespace=namespace, query=query, top_k=top_k)
```

### SONA Trajectory Tracking

Feed Astra's execution fingerprints into Ruflo's self-learning system:

```python
# After each run, emit trajectory to SONA
sona.record_trajectory(
    agent="astra_technical",
    task_type="saas_scaffold",
    actions=["github_create_repo", "claude_code_scaffold"],
    outcome_score=fingerprint.success_score,
    latency_ms=fingerprint.elapsed_seconds * 1000,
)
# SONA learns which action sequences produce best outcomes per task type
```

---

## Specialized Tools Per Agent

Beyond the current generic tool set, each agent gets domain-specific tools that make outputs substantially better.

### Research Agent — Deep Intelligence Tools

| Tool | What It Does |
|---|---|
| `academic_search` | Query Semantic Scholar, arXiv, PubMed for domain research |
| `patent_search` | USPTO + EPO search for IP landscape mapping |
| `competitor_intel` | Pull funding, headcount, job posts, pricing from Crunchbase + LinkedIn |
| `market_sizing_model` | Build TAM/SAM/SOM from multiple data sources, return structured model |
| `trend_detector` | Google Trends + Reddit + HN to surface emerging signals in a space |
| `regulatory_scanner` | Check FDA, FTC, SEC, GDPR, CCPA filings relevant to a market |

### Legal Agent — Compliance-Grade Tools

| Tool | What It Does |
|---|---|
| `entity_formation_lookup` | State-by-state entity type comparison (C-Corp, LLC, PBC, etc.) |
| `compliance_checker` | Flag GDPR, CCPA, HIPAA, SOC2 requirements for a given product |
| `contract_clause_library` | Pull battle-tested clause variants from a curated legal library |
| `jurisdiction_analyzer` | Recommend optimal state/country for incorporation given founder profile |
| `ip_clearance_check` | Trademark search for company name, product name, domain |
| `term_sheet_analyzer` | Parse a VC term sheet, flag founder-unfriendly clauses |

### Web Agent — Conversion-Optimized Tools

| Tool | What It Does |
|---|---|
| `seo_keyword_research` | Surface high-intent, low-competition keywords for the product |
| `competitor_page_analyzer` | Scrape and analyze competitor landing pages — structure, copy, CTAs |
| `domain_availability` | Check domain availability + suggest alternatives |
| `conversion_benchmarks` | Pull industry-average conversion rates for comparison |
| `a_b_variant_generator` | Generate 3 headline/CTA variants for testing |
| `page_speed_optimizer` | Analyze and fix HTML/CSS for Core Web Vitals compliance |

### Marketing Agent — Distribution Tools

| Tool | What It Does |
|---|---|
| `audience_persona_builder` | Build ICP profile from market research + product description |
| `competitor_ad_spy` | Surface competitor Facebook/Google ad copy via Meta Ad Library |
| `content_calendar_builder` | Generate 30-day content calendar with platform-specific posts |
| `influencer_finder` | Identify micro-influencers in the product's niche |
| `email_sequence_builder` | Write full 5-email welcome/onboarding sequence |
| `growth_channel_ranker` | Score top 10 acquisition channels by fit for this specific product |

### Technical Agent — Engineering-Grade Tools

| Tool | What It Does |
|---|---|
| `stack_recommender` | Recommend tech stack based on product type, team size, scale targets |
| `security_scanner` | Run OWASP top-10 check on generated scaffold |
| `dependency_auditor` | Check for known CVEs in requirements.txt / package.json |
| `architecture_diagram_gen` | Generate Mermaid diagram of the scaffold architecture |
| `api_spec_generator` | Auto-generate OpenAPI spec from scaffold routes |
| `infra_cost_estimator` | Estimate AWS/GCP/Vercel monthly cost at 100/1k/10k users |

### Ops Agent — Business Intelligence Tools

| Tool | What It Does |
|---|---|
| `runway_calculator` | Model burn rate vs runway given team size and costs |
| `kpi_dashboard_builder` | Define and structure the 10 most important KPIs for the business |
| `investor_matcher` | Match product to relevant VCs/angels by thesis and stage |
| `cap_table_modeler` | Model dilution across seed → Series A → Series B |
| `competitive_positioning_map` | Place product on a 2x2 vs top 5 competitors |
| `board_deck_generator` | Generate investor update deck structure from ops data |

---

## Build Order

1. `graph/decision_graph.py` — foundation everything else builds on
2. `fingerprint/fingerprinter.py` — standalone, needs only SQLite + sklearn
3. `mirror/founder_mirror.py` — standalone, needs only the LLM wrapper
4. `observer/silent_observer.py` — needs graph + web_search tool
5. `engine.py` — wires all four together
6. Integration into `backend/core/orchestrator.py`

---

## Dependencies

```
networkx>=3.0
scikit-learn>=1.4
sqlite3  (stdlib)
```

No new external APIs. Reuses existing `web_search` tool and `_llm.generate()`.

---

## Files To Create

```
proprietary-agent/
├── README.md                    ✓ done
├── SPEC.md                      ✓ this file
├── __init__.py
├── engine.py
├── graph/
│   ├── __init__.py
│   └── decision_graph.py
├── observer/
│   ├── __init__.py
│   └── silent_observer.py
├── fingerprint/
│   ├── __init__.py
│   └── fingerprinter.py
└── mirror/
    ├── __init__.py
    └── founder_mirror.py
```
