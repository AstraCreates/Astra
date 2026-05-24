# Stage 2: All 6 Agents Running

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Register all 5 remaining agents (research, web, marketing, technical, ops) so `/goal "launch my startup AcmeCo"` completes the full 6-agent dependency DAG and returns structured output from every agent.

**Architecture:** Each new agent is an `AstraAgent` instantiation — same base class, same OpenAI SDK pointed at `AGENT_MODEL_BASE_URL`, different `system_prompt`/`tools`/`memory_namespaces`. The DAG builder prompt already encodes the correct dependency ordering (legal+research parallel → web+marketing → technical → ops). This plan also fixes a PK collision bug in the DAG builder where multiple goals both produce tasks with id `t_001`, and updates the stale DAG builder tests that still mock the old Gemini client.

**Tech Stack:** Python 3.12, FastAPI, OpenAI SDK (MLX-compatible or Fireworks), pytest-asyncio, existing `AstraAgent` base class.

---

## File Map

**Create:**
- `backend/agents/research.py` — Research agent singleton
- `backend/agents/web.py` — Web agent singleton
- `backend/agents/marketing.py` — Marketing agent singleton
- `backend/agents/technical.py` — Technical agent singleton
- `backend/agents/ops.py` — Ops agent singleton
- `tests/test_research_agent.py`
- `tests/test_web_agent.py`
- `tests/test_marketing_agent.py`
- `tests/test_technical_agent.py`
- `tests/test_ops_agent.py`
- `tests/test_agent_registry.py`
- `tests/test_e2e_six_agents.py`

**Modify:**
- `backend/orchestrator/loop.py` — Add 5 imports + 5 AGENTS entries
- `backend/orchestrator/dag_builder.py` — Fix ID normalization (always goal-prefix, remap depends_on)
- `tests/test_dag_builder.py` — Update mocks from old Gemini `_get_model` to OpenAI SDK

---

### Task 1: Research Agent

**Files:**
- Create: `backend/agents/research.py`
- Create: `tests/test_research_agent.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_research_agent.py
import json
import pytest
from unittest.mock import MagicMock, AsyncMock
from backend.agents.base import AgentTask


@pytest.fixture
def mock_research_model(mocker):
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=json.dumps({
            "status": "done",
            "output": {
                "report_title": "AcmeCo Market Analysis",
                "tam_usd": "4B",
                "sam_usd": "400M",
                "som_usd": "40M",
                "competitors": ["CompA — incumbent SaaS", "CompB — VC-backed"],
                "icp": "Bootstrapped B2B SaaS founders, <5 employees",
                "key_insights": "Market growing 23% YoY; no self-serve player under $500/mo",
            },
            "confidence": 0.85,
            "reasoning": "Based on available market context",
        })))]
    )
    mocker.patch("backend.agents.base.openai.OpenAI", return_value=mock_client)
    mocker.patch("backend.agents.base.vector_store.retrieve", new=AsyncMock(return_value=[]))
    return mock_client


def test_research_agent_id():
    from backend.agents.research import RESEARCH_AGENT
    assert RESEARCH_AGENT.agent_id == "research"


def test_research_agent_namespaces():
    from backend.agents.research import RESEARCH_AGENT
    assert "research" in RESEARCH_AGENT.memory_namespaces
    assert "shared" in RESEARCH_AGENT.memory_namespaces


def test_research_agent_has_web_search_tool():
    from backend.agents.research import RESEARCH_AGENT
    assert "web_search" in RESEARCH_AGENT.tools


@pytest.mark.asyncio
async def test_research_agent_run_returns_done(mock_research_model):
    from backend.agents.research import RESEARCH_AGENT
    RESEARCH_AGENT._client = None  # force fresh client from mock
    task = AgentTask(
        task_id="t_001", goal_id="g_001", founder_id="f_001",
        agent="research", instruction="Research the AI productivity tools market for AcmeCo",
        context_bundle={"company_name": "AcmeCo", "problem": "founders waste time on admin"},
        constraints={}, tools_available=["web_search", "market_analyzer"],
    )
    result = await RESEARCH_AGENT.run(task)
    assert result.status == "done"
    assert "report_title" in result.output
    assert "tam_usd" in result.output
    assert "competitors" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_research_agent.py -v
```
Expected: `ModuleNotFoundError: No module named 'backend.agents.research'`

- [ ] **Step 3: Implement research agent**

```python
# backend/agents/research.py
from backend.agents.base import AstraAgent
from backend.config import settings

RESEARCH_AGENT = AstraAgent(
    agent_id="research",
    system_prompt=(
        "You are the Research Agent for Astra, an AI founding team for first-time startup founders. "
        "Given a startup concept, produce a structured market research report. "
        "Output must be a JSON object with these exact keys: "
        "report_title ('{Company} Market Analysis'), "
        "tam_usd (Total Addressable Market as string like '4B' or '400M'), "
        "sam_usd (Serviceable Addressable Market), "
        "som_usd (Serviceable Obtainable Market in year 1-2), "
        "competitors (list of 3-5 strings, each '<Name> — <one-line description>'), "
        "icp (Ideal Customer Profile as one sentence), "
        "key_insights (2-3 sentence paragraph with specific numbers and named trends). "
        "Use specific numbers and named companies. Avoid vague statements. "
        "Return status 'done' unless you lack enough context to produce any useful analysis."
    ),
    model=settings.agent_model_name,
    tools=["web_search", "market_analyzer"],
    memory_namespaces=["research", "shared"],
)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_research_agent.py -v
```
Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/agents/research.py tests/test_research_agent.py
git commit -m "feat: add research agent"
```

---

### Task 2: Web Agent

**Files:**
- Create: `backend/agents/web.py`
- Create: `tests/test_web_agent.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_web_agent.py
import json
import pytest
from unittest.mock import MagicMock, AsyncMock
from backend.agents.base import AgentTask


@pytest.fixture
def mock_web_model(mocker):
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=json.dumps({
            "status": "done",
            "output": {
                "page_title": "AcmeCo — AI for Founders",
                "headline": "Your AI founding team, on demand.",
                "subheadline": "Handle legal, research, and launch in days, not months.",
                "value_props": [
                    "Draft founder agreements in minutes",
                    "Know your market before you build",
                    "Launch a landing page this week",
                ],
                "cta_text": "Start Your Company",
                "cta_url": "/signup",
            },
            "confidence": 0.9,
            "reasoning": "Landing page copy based on ICP pain points",
        })))]
    )
    mocker.patch("backend.agents.base.openai.OpenAI", return_value=mock_client)
    mocker.patch("backend.agents.base.vector_store.retrieve", new=AsyncMock(return_value=[]))
    return mock_client


def test_web_agent_id():
    from backend.agents.web import WEB_AGENT
    assert WEB_AGENT.agent_id == "web"


def test_web_agent_namespaces():
    from backend.agents.web import WEB_AGENT
    assert "web" in WEB_AGENT.memory_namespaces
    assert "research" in WEB_AGENT.memory_namespaces


def test_web_agent_has_landing_page_tool():
    from backend.agents.web import WEB_AGENT
    assert "landing_page_generator" in WEB_AGENT.tools


@pytest.mark.asyncio
async def test_web_agent_run_returns_done(mock_web_model):
    from backend.agents.web import WEB_AGENT
    WEB_AGENT._client = None
    task = AgentTask(
        task_id="t_003", goal_id="g_001", founder_id="f_001",
        agent="web", instruction="Create landing page copy for AcmeCo targeting B2B SaaS founders",
        context_bundle={"company_name": "AcmeCo", "icp": "B2B SaaS founders"},
        constraints={}, tools_available=["landing_page_generator"],
    )
    result = await WEB_AGENT.run(task)
    assert result.status == "done"
    assert "headline" in result.output
    assert "cta_text" in result.output
    assert "value_props" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_web_agent.py -v
```
Expected: `ModuleNotFoundError: No module named 'backend.agents.web'`

- [ ] **Step 3: Implement web agent**

```python
# backend/agents/web.py
from backend.agents.base import AstraAgent
from backend.config import settings

WEB_AGENT = AstraAgent(
    agent_id="web",
    system_prompt=(
        "You are the Web Agent for Astra, an AI founding team for first-time startup founders. "
        "Given a company concept and market research, produce complete landing page copy. "
        "Output must be a JSON object with these exact keys: "
        "page_title ('{Company} — {tagline}', under 60 chars), "
        "headline (under 10 words, punchy, names the specific pain or outcome), "
        "subheadline (one sentence expanding on the headline, under 20 words), "
        "value_props (list of exactly 3 bullet point strings, each under 10 words), "
        "cta_text (button label, 2-4 words), "
        "cta_url (always '/signup'). "
        "Be specific — name the company, name the pain. "
        "Never write generic copy like 'Empower your business' or 'Drive results'. "
        "Return status 'done' with all fields populated."
    ),
    model=settings.agent_model_name,
    tools=["landing_page_generator"],
    memory_namespaces=["web", "research", "shared"],
)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_web_agent.py -v
```
Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/agents/web.py tests/test_web_agent.py
git commit -m "feat: add web agent"
```

---

### Task 3: Marketing Agent

**Files:**
- Create: `backend/agents/marketing.py`
- Create: `tests/test_marketing_agent.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_marketing_agent.py
import json
import pytest
from unittest.mock import MagicMock, AsyncMock
from backend.agents.base import AgentTask


@pytest.fixture
def mock_marketing_model(mocker):
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=json.dumps({
            "status": "done",
            "output": {
                "gtm_summary": "Target bootstrapped SaaS founders via cold email + ProductHunt launch in week 3",
                "channels": ["cold_email", "product_hunt", "indie_hackers"],
                "email_sequence": [
                    {"subject": "Quick question about {company}", "body": "Hi {first_name}, saw you're building {company}. One question: how much time do you spend on legal and admin? We cut that to zero. Worth 15 min?"},
                    {"subject": "Re: Quick question", "body": "Following up — happy to show you a 5-minute demo. No pitch, just the product."},
                    {"subject": "Last one", "body": "Not the right time? No worries. I'll leave you with this: founders who use Astra launch 3x faster. Link if you change your mind."},
                ],
                "messaging_pillars": ["Speed — days not months", "Founder-first — built for non-lawyers", "Full stack — legal + research + launch in one"],
            },
            "confidence": 0.87,
            "reasoning": "GTM plan based on ICP and market research context",
        })))]
    )
    mocker.patch("backend.agents.base.openai.OpenAI", return_value=mock_client)
    mocker.patch("backend.agents.base.vector_store.retrieve", new=AsyncMock(return_value=[]))
    return mock_client


def test_marketing_agent_id():
    from backend.agents.marketing import MARKETING_AGENT
    assert MARKETING_AGENT.agent_id == "marketing"


def test_marketing_agent_namespaces():
    from backend.agents.marketing import MARKETING_AGENT
    assert "marketing" in MARKETING_AGENT.memory_namespaces
    assert "research" in MARKETING_AGENT.memory_namespaces


def test_marketing_agent_has_email_tool():
    from backend.agents.marketing import MARKETING_AGENT
    assert "email_sequence_generator" in MARKETING_AGENT.tools


@pytest.mark.asyncio
async def test_marketing_agent_run_returns_done(mock_marketing_model):
    from backend.agents.marketing import MARKETING_AGENT
    MARKETING_AGENT._client = None
    task = AgentTask(
        task_id="t_004", goal_id="g_001", founder_id="f_001",
        agent="marketing", instruction="Create GTM plan for AcmeCo targeting bootstrapped B2B SaaS founders",
        context_bundle={"company_name": "AcmeCo", "icp": "B2B SaaS founders"},
        constraints={}, tools_available=["email_sequence_generator", "gtm_planner"],
    )
    result = await MARKETING_AGENT.run(task)
    assert result.status == "done"
    assert "gtm_summary" in result.output
    assert "email_sequence" in result.output
    assert len(result.output["email_sequence"]) >= 3
    assert all("subject" in e and "body" in e for e in result.output["email_sequence"])
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_marketing_agent.py -v
```
Expected: `ModuleNotFoundError: No module named 'backend.agents.marketing'`

- [ ] **Step 3: Implement marketing agent**

```python
# backend/agents/marketing.py
from backend.agents.base import AstraAgent
from backend.config import settings

MARKETING_AGENT = AstraAgent(
    agent_id="marketing",
    system_prompt=(
        "You are the Marketing Agent for Astra, an AI founding team for first-time startup founders. "
        "Given a company concept and target market, produce a go-to-market plan and cold email sequence. "
        "Output must be a JSON object with these exact keys: "
        "gtm_summary (one sentence: channel + launch timing + key hook), "
        "channels (list of 3 channel strings from: cold_email, product_hunt, twitter, linkedin, indie_hackers, hacker_news, reddit), "
        "email_sequence (list of 3-5 objects, each with 'subject' and 'body' fields; "
        "body is 2-4 sentences max; personalization tokens like {first_name} and {company} are OK; "
        "email 1 is cold outreach, email 2 is follow-up, email 3 is breakup), "
        "messaging_pillars (list of 3 strings, format '<Pillar name> — <one sentence description>'). "
        "Be specific and actionable. Avoid generic advice like 'use social media'. "
        "Return status 'done' with all fields populated."
    ),
    model=settings.agent_model_name,
    tools=["email_sequence_generator", "gtm_planner"],
    memory_namespaces=["marketing", "research", "shared"],
)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_marketing_agent.py -v
```
Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/agents/marketing.py tests/test_marketing_agent.py
git commit -m "feat: add marketing agent"
```

---

### Task 4: Technical Agent

**Files:**
- Create: `backend/agents/technical.py`
- Create: `tests/test_technical_agent.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_technical_agent.py
import json
import pytest
from unittest.mock import MagicMock, AsyncMock
from backend.agents.base import AgentTask


@pytest.fixture
def mock_technical_model(mocker):
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=json.dumps({
            "status": "done",
            "output": {
                "spec_title": "AcmeCo MVP Technical Spec",
                "stack": {"backend": "FastAPI + Python 3.12", "frontend": "Next.js 14", "db": "Supabase (Postgres)", "hosting": "Vercel + Railway"},
                "mvp_features": [
                    {"name": "User auth (email + Google)", "priority": "must"},
                    {"name": "Goal submission form", "priority": "must"},
                    {"name": "Agent results dashboard", "priority": "must"},
                    {"name": "Stripe payment integration", "priority": "must"},
                    {"name": "Email notifications", "priority": "nice"},
                ],
                "architecture_summary": "REST API backend with async task processing, React SPA frontend, Postgres for persistence. No microservices — monolith until $10k MRR.",
                "timeline_weeks": 4,
            },
            "confidence": 0.88,
            "reasoning": "Standard SaaS stack, proven for 0-to-launch",
        })))]
    )
    mocker.patch("backend.agents.base.openai.OpenAI", return_value=mock_client)
    mocker.patch("backend.agents.base.vector_store.retrieve", new=AsyncMock(return_value=[]))
    return mock_client


def test_technical_agent_id():
    from backend.agents.technical import TECHNICAL_AGENT
    assert TECHNICAL_AGENT.agent_id == "technical"


def test_technical_agent_namespaces():
    from backend.agents.technical import TECHNICAL_AGENT
    assert "technical" in TECHNICAL_AGENT.memory_namespaces
    assert "web" in TECHNICAL_AGENT.memory_namespaces


def test_technical_agent_has_spec_tool():
    from backend.agents.technical import TECHNICAL_AGENT
    assert "spec_generator" in TECHNICAL_AGENT.tools


@pytest.mark.asyncio
async def test_technical_agent_run_returns_done(mock_technical_model):
    from backend.agents.technical import TECHNICAL_AGENT
    TECHNICAL_AGENT._client = None
    task = AgentTask(
        task_id="t_005", goal_id="g_001", founder_id="f_001",
        agent="technical", instruction="Create MVP tech spec for AcmeCo based on the landing page design",
        context_bundle={"company_name": "AcmeCo"},
        constraints={}, tools_available=["spec_generator"],
    )
    result = await TECHNICAL_AGENT.run(task)
    assert result.status == "done"
    assert "spec_title" in result.output
    assert "stack" in result.output
    assert "mvp_features" in result.output
    assert all("name" in f and "priority" in f for f in result.output["mvp_features"])
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_technical_agent.py -v
```
Expected: `ModuleNotFoundError: No module named 'backend.agents.technical'`

- [ ] **Step 3: Implement technical agent**

```python
# backend/agents/technical.py
from backend.agents.base import AstraAgent
from backend.config import settings

TECHNICAL_AGENT = AstraAgent(
    agent_id="technical",
    system_prompt=(
        "You are the Technical Agent for Astra, an AI founding team for first-time startup founders. "
        "Given a product concept and landing page design, produce a startup MVP technical specification. "
        "Output must be a JSON object with these exact keys: "
        "spec_title ('{Company} MVP Technical Spec'), "
        "stack (dict with keys: backend, frontend, db, hosting — each a string naming the technology), "
        "mvp_features (list of 4-8 objects, each with 'name' string and 'priority': 'must'|'nice'), "
        "architecture_summary (2-3 sentences, plain English, no jargon — explain to a non-technical founder), "
        "timeline_weeks (integer, realistic weeks to MVP, typically 4-8). "
        "Recommend boring, proven technology. No Kubernetes, no microservices at MVP stage. "
        "Return status 'done' with all fields populated."
    ),
    model=settings.agent_model_name,
    tools=["spec_generator", "code_scaffolder"],
    memory_namespaces=["technical", "web", "shared"],
)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_technical_agent.py -v
```
Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/agents/technical.py tests/test_technical_agent.py
git commit -m "feat: add technical agent"
```

---

### Task 5: Ops Agent

**Files:**
- Create: `backend/agents/ops.py`
- Create: `tests/test_ops_agent.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ops_agent.py
import json
import pytest
from unittest.mock import MagicMock, AsyncMock
from backend.agents.base import AgentTask


@pytest.fixture
def mock_ops_model(mocker):
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=json.dumps({
            "status": "done",
            "output": {
                "weekly_digest": "Week 1: Founder agreement drafted, market research complete (TAM $4B), landing page copy ready, cold email sequence built, tech spec written. Ready to review and ship.",
                "priorities": [
                    "Review and sign founder agreement (Legal Agent output)",
                    "Publish landing page — approve copy before deploy",
                    "Send first 20 cold emails to ICP list",
                ],
                "blockers": [],
                "next_actions": [
                    {"action": "Review founder agreement", "owner": "Founder", "due": "48 hours"},
                    {"action": "Approve landing page copy", "owner": "Founder", "due": "3 days"},
                    {"action": "Deploy landing page", "owner": "Astra", "due": "3 days"},
                    {"action": "Send cold email batch 1", "owner": "Astra", "due": "1 week"},
                ],
            },
            "confidence": 0.92,
            "reasoning": "Synthesized all 5 agent outputs into prioritized action plan",
        })))]
    )
    mocker.patch("backend.agents.base.openai.OpenAI", return_value=mock_client)
    mocker.patch("backend.agents.base.vector_store.retrieve", new=AsyncMock(return_value=[]))
    return mock_client


def test_ops_agent_id():
    from backend.agents.ops import OPS_AGENT
    assert OPS_AGENT.agent_id == "ops"


def test_ops_agent_reads_all_namespaces():
    from backend.agents.ops import OPS_AGENT
    expected = {"shared", "legal", "research", "web", "marketing", "technical", "ops"}
    assert expected.issubset(set(OPS_AGENT.memory_namespaces))


def test_ops_agent_has_digest_tool():
    from backend.agents.ops import OPS_AGENT
    assert "digest_generator" in OPS_AGENT.tools


@pytest.mark.asyncio
async def test_ops_agent_run_returns_done(mock_ops_model):
    from backend.agents.ops import OPS_AGENT
    OPS_AGENT._client = None
    task = AgentTask(
        task_id="t_006", goal_id="g_001", founder_id="f_001",
        agent="ops", instruction="Synthesize all agent outputs into ops plan for AcmeCo",
        context_bundle={"company_name": "AcmeCo"},
        constraints={}, tools_available=["task_manager", "digest_generator"],
    )
    result = await OPS_AGENT.run(task)
    assert result.status == "done"
    assert "weekly_digest" in result.output
    assert "priorities" in result.output
    assert "next_actions" in result.output
    assert all("action" in a and "owner" in a and "due" in a for a in result.output["next_actions"])
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_ops_agent.py -v
```
Expected: `ModuleNotFoundError: No module named 'backend.agents.ops'`

- [ ] **Step 3: Implement ops agent**

```python
# backend/agents/ops.py
from backend.agents.base import AstraAgent
from backend.config import settings

OPS_AGENT = AstraAgent(
    agent_id="ops",
    system_prompt=(
        "You are the Ops Agent for Astra, an AI founding team for first-time startup founders. "
        "You run last, after all other agents complete. You have access to all company memory. "
        "Synthesize everything — legal docs, market research, landing page copy, GTM plan, tech spec — "
        "into a concrete weekly operations plan. "
        "Output must be a JSON object with these exact keys: "
        "weekly_digest (2-3 sentence summary of what was accomplished, name the specific deliverables), "
        "priorities (list of exactly 3 strings, each naming a specific action the founder must take, ordered by impact), "
        "blockers (list of strings describing open questions or blockers — empty list [] if none), "
        "next_actions (list of objects each with 'action' string, 'owner': 'Founder'|'Astra', 'due' string like '48 hours'|'3 days'|'1 week'). "
        "Be specific — reference the actual documents and decisions from other agents. "
        "Return status 'done' with all fields populated."
    ),
    model=settings.agent_model_name,
    tools=["task_manager", "digest_generator"],
    memory_namespaces=["shared", "legal", "research", "web", "marketing", "technical", "ops"],
)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_ops_agent.py -v
```
Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/agents/ops.py tests/test_ops_agent.py
git commit -m "feat: add ops agent"
```

---

### Task 6: Register All Agents in Orchestrator

**Files:**
- Modify: `backend/orchestrator/loop.py`
- Create: `tests/test_agent_registry.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agent_registry.py
from backend.orchestrator.loop import AGENTS


def test_all_six_agents_registered():
    expected = {"legal", "research", "web", "marketing", "technical", "ops"}
    assert set(AGENTS.keys()) == expected, f"Missing agents: {expected - set(AGENTS.keys())}"


def test_each_agent_has_correct_agent_id():
    for key, agent in AGENTS.items():
        assert agent.agent_id == key, f"AGENTS['{key}'].agent_id == '{agent.agent_id}'"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_agent_registry.py -v
```
Expected: `AssertionError: Missing agents: {'research', 'web', 'marketing', 'technical', 'ops'}`

- [ ] **Step 3: Update loop.py — replace agent imports and AGENTS dict**

In `backend/orchestrator/loop.py`, replace:
```python
from backend.agents.legal import LEGAL_AGENT
```
with:
```python
from backend.agents.legal import LEGAL_AGENT
from backend.agents.research import RESEARCH_AGENT
from backend.agents.web import WEB_AGENT
from backend.agents.marketing import MARKETING_AGENT
from backend.agents.technical import TECHNICAL_AGENT
from backend.agents.ops import OPS_AGENT
```

Replace:
```python
AGENTS = {
    "legal": LEGAL_AGENT,
    # stages 2+ add: research, web, marketing, technical, ops
}
```
with:
```python
AGENTS = {
    "legal": LEGAL_AGENT,
    "research": RESEARCH_AGENT,
    "web": WEB_AGENT,
    "marketing": MARKETING_AGENT,
    "technical": TECHNICAL_AGENT,
    "ops": OPS_AGENT,
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_agent_registry.py -v
```
Expected: 2 tests PASS

- [ ] **Step 5: Run full suite to check for regressions**

```bash
python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```
Expected: all existing tests still pass

- [ ] **Step 6: Commit**

```bash
git add backend/orchestrator/loop.py tests/test_agent_registry.py
git commit -m "feat: register all 6 agents in orchestrator AGENTS dict"
```

---

### Task 7: Fix DAG Builder ID Normalization + Update Stale Tests

**Problem 1:** The DAG builder only renames task IDs when they're missing or duplicate within the current list. It never prefixes with `goal_id`. Two concurrent goals both produce tasks with id `t_001`, causing a Supabase primary key collision on the `tasks` table.

**Problem 2:** When the ID-rename path fires, `depends_on` lists still reference the old IDs (e.g. `t_002`) which no longer exist under the renamed IDs — breaking dependency resolution.

**Problem 3:** `tests/test_dag_builder.py` still patches `backend.orchestrator.dag_builder._get_model` (old Gemini path). The module now uses OpenAI SDK. Those mocks are wiring to nothing, making the tests meaningless.

**Fix:** Always normalize all task IDs to `{goal_id}_t_{N:03d}` format via an old→new mapping, then remap all `depends_on` references through that same mapping. Update `test_dag_builder.py` to mock `backend.orchestrator.dag_builder.openai.OpenAI`.

**Files:**
- Modify: `backend/orchestrator/dag_builder.py`
- Modify: `tests/test_dag_builder.py`

- [ ] **Step 1: Add new tests to test_dag_builder.py**

Replace the entire content of `tests/test_dag_builder.py` with:

```python
# tests/test_dag_builder.py
import json
import pytest
from unittest.mock import MagicMock


def _make_mock_client(response_json: str):
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=response_json))]
    )
    return mock_client


@pytest.fixture
def mock_three_task_dag(mocker):
    payload = json.dumps({
        "tasks": [
            {"task_id": "t_001", "agent": "legal", "depends_on": [], "instruction": "Draft agreement", "tools_available": [], "constraints": {}},
            {"task_id": "t_002", "agent": "research", "depends_on": [], "instruction": "Research market", "tools_available": [], "constraints": {}},
            {"task_id": "t_003", "agent": "web", "depends_on": ["t_001", "t_002"], "instruction": "Build landing page", "tools_available": [], "constraints": {}},
        ]
    })
    mocker.patch("backend.orchestrator.dag_builder.openai.OpenAI", return_value=_make_mock_client(payload))


@pytest.mark.asyncio
async def test_dag_builder_returns_tasks_list(mock_three_task_dag):
    from backend.orchestrator.dag_builder import build_task_dag
    dag = await build_task_dag(
        goal_id="g_abc",
        parsed_goal={"instruction": "launch my startup", "entities": {"company_name": "AcmeCo"}, "priority_agents": ["legal"]},
    )
    assert isinstance(dag, list)
    assert len(dag) == 3
    assert dag[0]["agent"] == "legal"


@pytest.mark.asyncio
async def test_dag_task_ids_are_goal_prefixed(mock_three_task_dag):
    from backend.orchestrator.dag_builder import build_task_dag
    dag = await build_task_dag("g_abc", {"instruction": "launch", "entities": {}, "priority_agents": []})
    for task in dag:
        assert task["task_id"].startswith("g_abc_"), f"Expected 'g_abc_' prefix, got: {task['task_id']}"


@pytest.mark.asyncio
async def test_dag_depends_on_remapped_to_goal_prefix(mock_three_task_dag):
    from backend.orchestrator.dag_builder import build_task_dag
    dag = await build_task_dag("g_abc", {"instruction": "launch", "entities": {}, "priority_agents": []})
    task_ids = {t["task_id"] for t in dag}
    for task in dag:
        for dep in task["depends_on"]:
            assert dep in task_ids, f"depends_on '{dep}' not in task_ids {task_ids}"


@pytest.mark.asyncio
async def test_dag_web_task_depends_on_two_tasks(mock_three_task_dag):
    from backend.orchestrator.dag_builder import build_task_dag
    dag = await build_task_dag("g_abc", {"instruction": "launch", "entities": {}, "priority_agents": []})
    web_task = next(t for t in dag if t["agent"] == "web")
    assert len(web_task["depends_on"]) == 2
    task_ids = {t["task_id"] for t in dag}
    assert all(dep in task_ids for dep in web_task["depends_on"])


@pytest.mark.asyncio
async def test_dag_builder_falls_back_on_invalid_json(mocker):
    mocker.patch(
        "backend.orchestrator.dag_builder.openai.OpenAI",
        return_value=_make_mock_client("not valid json at all")
    )
    from backend.orchestrator.dag_builder import build_task_dag
    dag = await build_task_dag("g_fallback", {"instruction": "do something", "entities": {}, "priority_agents": []})
    assert isinstance(dag, list)
    assert len(dag) >= 1
    assert dag[0]["task_id"].startswith("g_fallback_")


@pytest.mark.asyncio
async def test_dag_builder_no_pk_collision_across_goals(mock_three_task_dag):
    from backend.orchestrator.dag_builder import build_task_dag
    dag1 = await build_task_dag("g_001", {"instruction": "launch", "entities": {}, "priority_agents": []})
    dag2 = await build_task_dag("g_002", {"instruction": "launch", "entities": {}, "priority_agents": []})
    ids1 = {t["task_id"] for t in dag1}
    ids2 = {t["task_id"] for t in dag2}
    assert ids1.isdisjoint(ids2), f"ID collision across goals: {ids1 & ids2}"
```

- [ ] **Step 2: Run tests to verify the new tests fail**

```bash
python -m pytest tests/test_dag_builder.py -v
```
Expected: new tests about goal-prefixed IDs and remapped depends_on FAIL; the two old tests may pass (they were testing the wrong mock anyway)

- [ ] **Step 3: Fix dag_builder.py normalization block**

In `backend/orchestrator/dag_builder.py`, find the block inside the `try:` block starting at `seen_ids = set()` and replace through `return tasks` with:

```python
        # Always normalize task IDs to goal-prefixed format and remap depends_on
        old_to_new: dict[str, str] = {}
        for i, task in enumerate(tasks):
            old_id = task.get("task_id") or f"t_{i+1:03d}"
            new_id = f"{goal_id}_t_{i+1:03d}"
            old_to_new[old_id] = new_id
            task["task_id"] = new_id

        for task in tasks:
            task["depends_on"] = [old_to_new.get(dep, dep) for dep in task.get("depends_on", [])]
            task.setdefault("agent", "legal")
            task.setdefault("instruction", "")
            task.setdefault("tools_available", [])
            task.setdefault("constraints", {})

        return tasks
```

Also update the fallback block to use goal-prefixed IDs (it already does via `f"{goal_id}_t_001"` — verify this is correct, no change needed there).

- [ ] **Step 4: Run all dag builder tests to verify they pass**

```bash
python -m pytest tests/test_dag_builder.py -v
```
Expected: 6 tests PASS

- [ ] **Step 5: Run full test suite**

```bash
python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add backend/orchestrator/dag_builder.py tests/test_dag_builder.py
git commit -m "fix: normalize dag task IDs to goal-prefixed format, remap depends_on, update stale tests"
```

---

### Task 8: E2E Test — Full 6-Agent DAG

**Files:**
- Create: `tests/test_e2e_six_agents.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_e2e_six_agents.py
import json
import pytest
from unittest.mock import MagicMock, AsyncMock

FOUNDER_ID = "83ede714-c2ba-4842-ac33-19b6c7ff22a8"

_AGENT_OUTPUTS = {
    "legal": {"document_name": "AcmeCo Founder Agreement", "content": "AGREEMENT text..."},
    "research": {"report_title": "AcmeCo Market Analysis", "tam_usd": "4B", "competitors": ["CompA"]},
    "web": {"headline": "Your AI founding team.", "cta_text": "Get Started", "value_props": ["Fast", "Simple", "Founder-first"]},
    "marketing": {"gtm_summary": "Cold email + ProductHunt", "email_sequence": [{"subject": "Hi", "body": "..."}], "channels": ["cold_email"]},
    "technical": {"spec_title": "AcmeCo MVP Spec", "stack": {"backend": "FastAPI"}, "mvp_features": [{"name": "Auth", "priority": "must"}]},
    "ops": {"weekly_digest": "Week 1 complete.", "priorities": ["Sign agreement", "Launch page", "Send emails"], "blockers": [], "next_actions": [{"action": "Review agreement", "owner": "Founder", "due": "48 hours"}]},
}


def _agent_response(agent_id: str) -> str:
    return json.dumps({
        "status": "done",
        "output": _AGENT_OUTPUTS[agent_id],
        "confidence": 0.9,
        "reasoning": f"{agent_id} task complete",
    })


@pytest.fixture
def mock_infra(mocker):
    task_store: dict = {}
    goal_store: dict = {}

    async def fake_persist_goal(goal_id, founder_id, instruction, constraints):
        goal_store[goal_id] = {"id": goal_id, "status": "pending"}

    async def fake_persist_task_graph(goal_id, founder_id, tasks):
        for t in tasks:
            task_store[t["task_id"]] = {
                **t, "id": t["task_id"], "goal_id": goal_id, "status": "pending",
            }

    async def fake_get_ready_tasks(goal_id):
        done_ids = {
            tid for tid, t in task_store.items()
            if t.get("status") == "done" and t.get("goal_id") == goal_id
        }
        return [
            t for t in task_store.values()
            if t.get("goal_id") == goal_id
            and t.get("status") == "pending"
            and all(dep in done_ids for dep in t.get("depends_on", []))
        ]

    async def fake_has_in_progress(goal_id):
        return any(
            t.get("status") == "in_progress" and t.get("goal_id") == goal_id
            for t in task_store.values()
        )

    async def fake_update_task_status(task_id, status, output=None):
        if task_id in task_store:
            task_store[task_id]["status"] = status
            if output:
                task_store[task_id]["output"] = output

    async def fake_update_goal_status(goal_id, status, elapsed_seconds=None):
        if goal_id in goal_store:
            goal_store[goal_id]["status"] = status

    mocker.patch("backend.orchestrator.loop.persist_goal", side_effect=fake_persist_goal)
    mocker.patch("backend.orchestrator.loop.persist_task_graph", side_effect=fake_persist_task_graph)
    mocker.patch("backend.orchestrator.loop.get_ready_tasks", side_effect=fake_get_ready_tasks)
    mocker.patch("backend.orchestrator.loop.has_in_progress_tasks", side_effect=fake_has_in_progress)
    mocker.patch("backend.orchestrator.loop.update_task_status", side_effect=fake_update_task_status)
    mocker.patch("backend.orchestrator.loop.update_goal_status", side_effect=fake_update_goal_status)
    mocker.patch("backend.memory.vector_store.vector_store.write", new=AsyncMock())
    mocker.patch("backend.memory.vector_store.vector_store.retrieve", new=AsyncMock(return_value=[]))

    return {"goals": goal_store, "tasks": task_store}


@pytest.fixture
def mock_goal_parser(mocker):
    async def fake_parse(goal_id, founder_id, raw):
        return {
            "instruction": "launch AcmeCo — an AI tool for first-time founders",
            "entities": {"company_name": "AcmeCo", "problem": "founders waste time on admin"},
            "constraints": {},
            "priority_agents": ["legal", "research"],
        }
    mocker.patch("backend.orchestrator.loop.parse_goal", side_effect=fake_parse)


@pytest.fixture
def mock_dag_builder(mocker):
    async def fake_build(goal_id, parsed):
        raw_tasks = [
            {"task_id": "t_001", "agent": "legal", "depends_on": [], "instruction": "Draft founder agreement", "tools_available": ["doc_generator"], "constraints": {}},
            {"task_id": "t_002", "agent": "research", "depends_on": [], "instruction": "Research market", "tools_available": ["web_search"], "constraints": {}},
            {"task_id": "t_003", "agent": "web", "depends_on": ["t_001", "t_002"], "instruction": "Create landing page", "tools_available": ["landing_page_generator"], "constraints": {}},
            {"task_id": "t_004", "agent": "marketing", "depends_on": ["t_001", "t_002"], "instruction": "Create GTM plan", "tools_available": ["email_sequence_generator"], "constraints": {}},
            {"task_id": "t_005", "agent": "technical", "depends_on": ["t_003"], "instruction": "Create tech spec", "tools_available": ["spec_generator"], "constraints": {}},
            {"task_id": "t_006", "agent": "ops", "depends_on": ["t_001", "t_002", "t_003", "t_004", "t_005"], "instruction": "Synthesize all outputs", "tools_available": ["digest_generator"], "constraints": {}},
        ]
        old_to_new = {}
        for i, task in enumerate(raw_tasks):
            old_id = task["task_id"]
            new_id = f"{goal_id}_t_{i+1:03d}"
            old_to_new[old_id] = new_id
            task["task_id"] = new_id
        for task in raw_tasks:
            task["depends_on"] = [old_to_new.get(dep, dep) for dep in task["depends_on"]]
        return raw_tasks
    mocker.patch("backend.orchestrator.loop.build_task_dag", side_effect=fake_build)


@pytest.fixture
def mock_all_agents(mocker):
    from backend.orchestrator.loop import AGENTS
    for agent_id, agent in AGENTS.items():
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content=_agent_response(agent_id)))]
        )
        agent._client = mock_client
    yield
    for agent in AGENTS.values():
        agent._client = None


@pytest.mark.asyncio
async def test_six_agent_dag_all_complete(mock_infra, mock_goal_parser, mock_dag_builder, mock_all_agents):
    from backend.orchestrator.loop import OrchestratorLoop
    loop = OrchestratorLoop()
    result = await loop.run_goal(
        goal_id="g_six_test",
        founder_id=FOUNDER_ID,
        raw_instruction="launch my startup AcmeCo",
        constraints={},
    )
    assert result["status"] == "done"
    completed_agents = {r["agent"] for r in result["results"]}
    assert completed_agents == {"legal", "research", "web", "marketing", "technical", "ops"}


@pytest.mark.asyncio
async def test_ops_runs_last(mock_infra, mock_goal_parser, mock_dag_builder, mock_all_agents):
    from backend.orchestrator.loop import OrchestratorLoop
    loop = OrchestratorLoop()
    result = await loop.run_goal("g_order_test", FOUNDER_ID, "launch AcmeCo", {})

    ops_task = next(
        (t for t in mock_infra["tasks"].values() if t.get("agent") == "ops"),
        None,
    )
    assert ops_task is not None
    other_ids = {tid for tid, t in mock_infra["tasks"].items() if t.get("agent") != "ops"}
    assert all(dep in other_ids for dep in ops_task.get("depends_on", [])), (
        f"ops.depends_on should reference all other tasks; got {ops_task['depends_on']}"
    )


@pytest.mark.asyncio
async def test_no_pending_approvals_on_auto_goal(mock_infra, mock_goal_parser, mock_dag_builder, mock_all_agents):
    from backend.orchestrator.loop import OrchestratorLoop
    loop = OrchestratorLoop()
    result = await loop.run_goal("g_approval_test", FOUNDER_ID, "launch AcmeCo", {})
    assert result["pending_approvals"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_e2e_six_agents.py -v
```
Expected: `test_six_agent_dag_all_complete` FAIL — only `{"legal"}` in completed agents (before Task 6 lands)
After Task 6 is merged: re-run and all should pass.

- [ ] **Step 3: Run full test suite**

```bash
python -m pytest tests/ -v --tb=short 2>&1 | tail -40
```
Expected: all tests PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_six_agents.py
git commit -m "test: E2E gate test for full 6-agent DAG — all agents complete, ops runs last"
```

---

### Task 9: Live Smoke Test — All 6 Agents

- [ ] **Step 1: Verify MLX server running on port 8081**

```bash
curl -s http://localhost:8081/v1/models | python3 -c "import sys,json; d=json.load(sys.stdin); print([m['id'] for m in d['data']])"
```
Expected: list containing the model name from `.env AGENT_MODEL_NAME`

- [ ] **Step 2: Start FastAPI server**

```bash
pkill -f "uvicorn backend.main" 2>/dev/null; sleep 1
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 &
sleep 3 && curl -s http://localhost:8000/health
```
Expected: `{"status":"ok"}`

- [ ] **Step 3: Fire full smoke test**

```bash
python3 -c "
import urllib.request, json, time
data = json.dumps({
  'founder_id': '83ede714-c2ba-4842-ac33-19b6c7ff22a8',
  'instruction': 'launch my startup AcmeCo — an AI tool for first-time founders to handle legal, research, and launch',
  'constraints': {}
}).encode()
req = urllib.request.Request('http://localhost:8000/goal', data=data, method='POST',
  headers={'Content-Type': 'application/json'})
resp = urllib.request.urlopen(req, timeout=600)
result = json.loads(resp.read().decode())
print(f'Status:  {result[\"status\"]}')
print(f'Elapsed: {result[\"elapsed_seconds\"]:.1f}s')
print(f'Agents:  {sorted(r[\"agent\"] for r in result[\"results\"])}')
print(f'Approvals pending: {len(result[\"pending_approvals\"])}')
for r in result['results']:
    keys = list(r['output'].keys())
    print(f'  [{r[\"agent\"]}] output keys: {keys}')
"
```
Expected (order may vary based on DAG builder output; elapsed will be long due to sequential MLX inference):
```
Status:  done
Elapsed: ~300s
Agents:  ['legal', 'marketing', 'ops', 'research', 'technical', 'web']
Approvals pending: 0
  [legal] output keys: ['document_name', 'content']
  [research] output keys: ['report_title', 'tam_usd', 'competitors', ...]
  [web] output keys: ['headline', 'cta_text', 'value_props', ...]
  [marketing] output keys: ['gtm_summary', 'email_sequence', ...]
  [technical] output keys: ['spec_title', 'stack', 'mvp_features', ...]
  [ops] output keys: ['weekly_digest', 'priorities', 'next_actions', ...]
```

If DAG builder returns only 1 task (fallback), the model isn't generating valid JSON for the full 6-agent prompt. In that case, check server logs for the raw model response and iterate on the DAG builder prompt.

- [ ] **Step 4: Commit smoke test result**

```bash
git commit --allow-empty -m "test: stage 2 live smoke test — all 6 agents complete end-to-end"
```

---

## Gate Check

Stage 2 is complete when:
1. All 6 `tests/test_*_agent.py` files pass
2. `tests/test_agent_registry.py` passes (6 agents registered)
3. `tests/test_dag_builder.py` passes (goal-prefixed IDs, remapped depends_on)
4. `tests/test_e2e_six_agents.py` passes (DAG completes, ops runs last)
5. Live smoke test returns `status: done` with all 6 agents in results

Next milestone: Stage 2b — Next.js dashboard (goal submission form, agent results display, polling for live updates).
