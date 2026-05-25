# Astra Proprietary Agent Intelligence Layer

Four systems that give Astra a compounding intelligence advantage no competitor can replicate — because the value is in the accumulated data, not the code.

---

## Overview

The current Astra agent loop is stateless: each run starts cold, completes tasks, and discards most of what it learned. This layer changes that. Every session feeds four interlocking systems that make the next session smarter, faster, and more aligned with the specific founder running it.

```
┌─────────────────────────────────────────────────────────────┐
│                    Astra Orchestrator                        │
│                                                             │
│  ┌──────────────┐    ┌──────────────────────────────────┐  │
│  │   Pre-Run    │    │           Agent Execution         │  │
│  │              │    │                                   │  │
│  │ • Load graph │    │  research → legal → web →        │  │
│  │   context    │───▶│  marketing → technical → ops     │  │
│  │ • Match      │    │                                   │  │
│  │   fingerprint│    │  [Mirror runs after each agent]  │  │
│  │ • Brief      │    │                                   │  │
│  │   observer   │    └──────────────────────────────────┘  │
│  └──────────────┘                      │                    │
│                                        ▼                    │
│                           ┌────────────────────┐           │
│                           │     Post-Run        │           │
│                           │                     │           │
│                           │ • Write graph nodes │           │
│                           │ • Store fingerprint │           │
│                           │ • Observer digest   │           │
│                           └────────────────────┘           │
└─────────────────────────────────────────────────────────────┘
```

---

## System A — Causal Decision Graph

**What it is:** A persistent knowledge graph where every agent decision is a node with causal edges connecting what triggered it, what it triggered, and what the outcome was.

**Why it's proprietary:** The graph accumulates over time per founder. After 10 runs, Astra knows why the company name was chosen, why pricing changed, what a competitor did that prompted a pivot, which legal structure was rejected and why. This is not retrievable from flat session logs — the causal structure is the value.

**Architecture:**
- NetworkX directed graph, serialized to disk as JSON
- Node types: `decision`, `entity`, `outcome`, `agent_action`, `external_event`
- Edge types: `triggered_by`, `led_to`, `contradicts`, `supports`, `invalidates`
- Agents call `graph.query_relevant(context)` before acting — surfaces related prior decisions
- Agents call `graph.add_decision(...)` after acting — writes the new node and edges

**What agents get before each run:**
```
Prior decision: Chose Delaware C-Corp over LLC on 2026-04-12
  Reason: Planning to raise institutional capital
  Outcome: Positive — investor term sheet received 2026-05-01
  Caution: Same structure failed for solo-founder in 2026-03-08 run (no investor interest)
```

**Graph grows into:** A queryable company brain. "What have we decided about pricing?" returns a causal chain of every pricing decision, what triggered each one, and whether it held.

---

## System E — Silent Observer

**What it is:** A background agent that runs continuously without being asked. Monitors competitor activity, regulatory changes, funding announcements, job board signals, and industry news in every founder's domain — then surfaces relevant intelligence proactively.

**Why it's proprietary:** Every other agent platform is reactive. You ask, they answer. Silent Observer flips this. It watches the world on the founder's behalf and interrupts when something matters. The signal-to-noise filtering is what's hard — it learns what each founder actually cares about from the decision graph.

**Architecture:**
- asyncio background task, configurable polling interval (default: 6 hours)
- Sources: web search, news APIs, patent filings, regulatory feeds
- Deduplication: content hash index prevents re-surfacing seen items
- Relevance scoring: matches against the founder's decision graph + active goals
- Output: writes `external_event` nodes to the decision graph + queues founder alerts

**What a founder sees:**
```
[Silent Observer — 06:14 AM]
Competitor "RangeLead" raised $2.1M seed (TechCrunch, 2026-05-23)
  Relevant to: your getweb platform, active marketing campaign
  Suggested action: Accelerate launch timeline, differentiate on pricing page
  Confidence: 0.91
```

**Observer learns over time:** Which signals the founder acted on vs ignored. Adjusts relevance weights accordingly. Stops alerting on noise, amplifies signal.

---

## System F — Execution Fingerprinting

**What it is:** Every completed Astra run is compressed into a fingerprint — a structured record of the goal, which agents ran, which tools succeeded and failed, timing per step, and a success score. New runs are matched against historical fingerprints before execution begins.

**Why it's proprietary:** This is a cross-founder learning dataset that no competitor can replicate without running Astra at scale. The fingerprints encode what actually happens in production, not what the docs say should happen. After 100 runs, Astra can predict with measurable accuracy which approaches work for which goal types.

**Architecture:**
- SQLite database, one row per completed run
- Fingerprint schema: `{goal_vector, agents_used[], tool_outcomes{}, timing{}, success_score, founder_id, timestamp}`
- Goal vectorization: TF-IDF on goal text (no external embedding API)
- Similarity matching: cosine similarity on goal vectors + Jaccard on tool outcome sets
- Match threshold: top-3 similar runs surfaced if similarity > 0.65

**What the orchestrator gets before each run:**
```
Fingerprint match: 78% similar to run d2e410a3 (2026-05-20)
  That run: "SaaS for businesses without websites"
  What worked: claude_code_scaffold (30 files, 1942 insertions), vercel_deploy (live in 4min)
  What failed: legal agent timed out on format_legal_document (2nd call blocked)
  Adjusted plan: pre-block legal duplicate calls, allocate +90s to scaffold step
```

**Fingerprinting compounds into:** A production-calibrated execution model. Astra stops estimating and starts predicting based on what actually happened.

---

## System G — Founder Mirror

**What it is:** A dedicated adversarial agent whose only job is to attack every other agent's output before it reaches the founder. Runs after each specialist, asks the hard questions a skeptical investor or co-founder would ask, and returns a critique + pass/flag/block verdict.

**Why it's proprietary:** Other platforms ship whatever the agent produces. Mirror forces every output to survive adversarial scrutiny first. Over time, the quality bar rises because agents learn (through prompt engineering and output scoring) what passes the Mirror. The critique history is also stored in the decision graph — a record of every near-miss.

**Architecture:**
- Separate LLM call with a red-team system prompt — same model, different role
- Input: agent name + full output
- Output: `{verdict: pass|flag|block, critique: str, questions: [], revised_recommendation: str}`
- Verdict thresholds:
  - `pass` — output survives scrutiny, proceed
  - `flag` — output is weak but acceptable, founder is notified
  - `block` — output has a critical flaw, agent must revise before proceeding
- Mirror critique stored as `mirror_review` edge in the decision graph

**What Mirror asks per agent:**
- Research: "Is this market size credible? What's the source quality? What did you miss?"
- Legal: "Does this document expose the founder? What clause would kill a deal?"
- Web: "Would a real customer click this CTA? Is the value prop specific or generic?"
- Marketing: "Who specifically is this for? What makes this different from competitor copy?"
- Technical: "Is this scaffold production-ready or a demo? What breaks at 1000 users?"
- Ops: "What's the single biggest operational risk not addressed here?"

**Mirror output example:**
```
Agent: web
Verdict: FLAG
Critique: Headline is generic ("Identify Businesses Without Websites in Seconds") —
  could apply to 12 competitors. Value props use filler ("save time", "easy to use").
  CTA is weak ("Get Started Now" has no specificity).
Questions:
  - What is the one thing GetWeb does that no competitor does?
  - Who specifically is the first customer — a freelancer? An agency? A sales team?
Revised recommendation: Rewrite headline around the verified contact data differentiator.
  Change CTA to "Find Your First 50 Leads Free".
```

---

## Integration

All four systems plug into the existing `Orchestrator` via `engine.py`:

```python
from proprietary_agent.engine import ProprietaryEngine

engine = ProprietaryEngine(founder_id="founder_001")

# Pre-run: load context from graph + fingerprint match
pre_context = await engine.pre_run(goal=instruction)

# Pass pre_context into orchestrator shared state
result = await orchestrator.run(goal=instruction, shared=pre_context)

# Post-run: write everything back
await engine.post_run(session_id=result["session_id"], results=result["results"])
```

The orchestrator gains:
- Graph context injected into every agent's system prompt
- Fingerprint-based plan adjustments before dispatch
- Mirror verdict after each agent (flag/block triggers retry or founder alert)
- Observer alerts surfaced at run start if relevant signals pending

---

## What This Builds Over Time

| Sessions | What Astra Gains |
|---|---|
| 1–5 | Baseline graph, first fingerprints, Mirror calibrating |
| 10–25 | Fingerprint matches start predicting failures accurately |
| 25–50 | Observer learns each founder's signal preferences |
| 50+ | Graph becomes a queryable company brain; Astra knows the company better than any new hire |
| 100+ | Cross-founder fingerprint dataset enables benchmark predictions |

No competitor can replicate this without running at scale for years. The moat is the data, not the architecture.

---

## Files

```
proprietary-agent/
├── README.md                        # This document
├── engine.py                        # Main integration point
├── graph/
│   ├── __init__.py
│   └── decision_graph.py            # Causal graph (NetworkX + JSON persistence)
├── observer/
│   ├── __init__.py
│   └── silent_observer.py           # Background monitoring agent
├── fingerprint/
│   ├── __init__.py
│   └── fingerprinter.py             # Run compression + similarity matching
└── mirror/
    ├── __init__.py
    └── founder_mirror.py            # Adversarial red-team agent
```

---

## Status

| System | Status |
|---|---|
| A — Causal Decision Graph | Planned |
| E — Silent Observer | Planned |
| F — Execution Fingerprinting | Planned |
| G — Founder Mirror | Planned |
| engine.py integration | Planned |
