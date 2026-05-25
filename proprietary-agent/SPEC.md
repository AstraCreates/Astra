# Proprietary Agent Intelligence Layer — Build Spec

What we're building, why, and exactly how each system works.

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
