"""Department dispatch and safe execution for the Company OS.

This module deliberately owns orchestration, not persistence.  The Company OS
store is the source of truth and is accessed only through its small frozen
contract: ``get_company_os``, the five create functions, and ``append_event``.
"""
from __future__ import annotations

import hashlib
import importlib
import inspect
import re
from datetime import datetime, timezone
from typing import Any, Callable, Mapping


DEPARTMENT_HEADS = (
    "research", "marketing", "sales", "product_technical", "design",
    "finance", "legal", "operations",
)

_INTENT_KEYWORDS = {
    "research": ("research", "market", "competitor", "customer interview", "learn", "investigate",
                 "viable", "viability", "feasible", "feasibility", "find out", "figure out",
                 "profitable", "profitability", "worth it", "is it possible", "possible"),
    "marketing": ("marketing", "campaign", "brand", "seo", "content", "audience"),
    "sales": ("sales", "lead", "prospect", "pipeline", "outreach", "close"),
    "product_technical": ("product", "feature", "bug", "api", "code", "technical", "engineering", "website", "web site", "landing page", "web app", "frontend"),
    "design": ("design", "ux", "ui", "wireframe", "prototype", "visual"),
    "finance": ("finance", "budget", "forecast", "revenue", "invoice", "pricing"),
    "legal": ("legal", "contract", "privacy", "terms", "compliance", "trademark"),
    "operations": ("operation", "process", "schedule", "vendor", "workflow", "hire"),
}

# When nothing scores above zero, max()'s tie-break silently picked whichever
# department happened to be first in DEPARTMENT_HEADS -- an accident of tuple
# order, not a decision. Research is still the right default for a vague
# "is X viable/worth doing" ask, but it's now an explicit choice instead of
# incidental ordering, so changing the default later means changing one name.
_DEFAULT_DEPARTMENT = "research"

_SQUADS = {
    "research": "insights", "marketing": "growth", "sales": "revenue",
    "product_technical": "product_delivery", "design": "experience",
    "finance": "planning", "legal": "risk", "operations": "company_operations",
}

_PLANS = {
    "research": ("Gather reliable sources and internal evidence", "Synthesize findings and uncertainties", "Produce a decision brief"),
    "marketing": ("Analyze audience and positioning", "Draft campaign assets", "Prepare a review-ready launch plan"),
    "sales": ("Research target accounts and qualification criteria", "Draft outreach and follow-up materials", "Prepare pipeline recommendations"),
    "product_technical": ("Clarify requirements and technical constraints", "Draft an implementation plan or local artifact", "Review risks and acceptance criteria"),
    "design": ("Research user needs and visual references", "Create draft flows or design artifacts", "Document review criteria"),
    "finance": ("Analyze assumptions and financial data", "Create forecast and variance analysis", "Prepare budget recommendations"),
    "legal": ("Research applicable requirements", "Draft internal issue list or document redlines", "Escalate decisions needing counsel or approval"),
    "operations": ("Assess process, cadence, and capacity", "Draft operating procedures or schedules", "Prepare reversible internal updates"),
}

_WEBSITE_TERMS = ("website", "web site", "landing page", "web app", "frontend")

_APPROVAL_TERMS = (
    "send", "email", "message", "contact", "outreach", "publish", "post", "deploy",
    "production", "credential", "secret", "api key", "provision", "purchase", "pay",
    "spend", "charge", "transfer", "refund", "delete", "remove", "destroy",
)
_AUTO_TERMS = ("read", "research", "analyze", "draft", "internal", "local", "artifact", "reversible")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _store() -> Any:
    """Load lazily so this dispatcher remains importable during store migrations."""
    return importlib.import_module("backend.company_os")


def _call(function_name: str, **values: Any) -> Any:
    """Call a contract function while tolerating optional store parameters."""
    fn = getattr(_store(), function_name)
    try:
        parameters = inspect.signature(fn).parameters
        if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
            return fn(**values)
        return fn(**{key: value for key, value in values.items() if key in parameters})
    except (TypeError, ValueError):
        return fn(**values)


_STOPWORDS = frozenset({
    "a", "an", "the", "is", "it", "to", "of", "for", "and", "or", "in", "on", "if", "that",
    "this", "was", "were", "are", "be", "do", "does", "did", "how", "what", "why", "when",
    "where", "who", "we", "i", "you", "our", "your", "find", "out", "see", "teh", "with",
    "can", "could", "should", "would", "will", "research", "reserach", "resreach",
})
_CONTINUATION_OVERLAP_THRESHOLD = 0.4


def _content_words(text: str) -> frozenset[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return frozenset(w for w in words if w not in _STOPWORDS and len(w) > 2)


def _find_continuation(intent: str, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Find an active initiative whose name is close enough to `intent` that
    this is really the same ask again (verbatim repeat or light rephrasing),
    not a new topic that happens to share a department. Purely lexical
    (overlap coefficient on stopword-filtered words) -- no LLM call, so it
    catches repeats and near-repeats but not a genuinely different question
    about the same broad subject; that's a deliberate, cheaper middle ground."""
    words = _content_words(intent)
    if len(words) < 2:
        return None
    best: tuple[float, dict[str, Any]] | None = None
    for candidate in candidates:
        candidate_words = _content_words(str(candidate.get("name", "")))
        if len(candidate_words) < 2:
            continue
        overlap = len(words & candidate_words) / min(len(words), len(candidate_words))
        if overlap >= _CONTINUATION_OVERLAP_THRESHOLD and (best is None or overlap > best[0]):
            best = (overlap, candidate)
    return best[1] if best else None


def choose_department(intent: str) -> tuple[str, str]:
    """Choose a department head and its default specialist squad from intent."""
    words = (intent or "").lower()
    if any(term in words for term in _WEBSITE_TERMS):
        return "product_technical", "website_build"
    scores = {head: sum(term in words for term in _INTENT_KEYWORDS[head]) for head in DEPARTMENT_HEADS}
    winner = max(DEPARTMENT_HEADS, key=lambda head: scores[head])
    if scores[winner] == 0:
        winner = _DEFAULT_DEPARTMENT
    return winner, _SQUADS[winner]


def specialist_task_plan(department: str, intent: str) -> list[dict[str, Any]]:
    """Return a safe, reviewable specialist plan before any external action."""
    if department not in DEPARTMENT_HEADS:
        raise ValueError(f"Unknown department head: {department}")
    plan = ("Clarify audience, offer, and constraints", "Create a local website preview", "Review the preview and prepare a publish approval") if department == "product_technical" and any(term in intent.lower() for term in _WEBSITE_TERMS) else _PLANS[department]
    return [
        {"title": title, "description": f"{title}. Intent: {intent}", "department": department,
         "operation": "internal_analysis" if index == 0 else "draft"}
        for index, title in enumerate(plan)
    ]


def enforce_dispatch_policy(
    task: Mapping[str, Any], *, company: Mapping[str, Any] | None = None,
    proposed_spend: float = 0.0,
) -> dict[str, Any]:
    """The sole policy choke point for every executor in this module.

    A task is never rejected here: risky work becomes an approval card.  Explicit
    risk categories override benign wording so callers cannot label a deployment
    as a draft to bypass the gate.
    """
    text = " ".join(str(task.get(key, "")) for key in ("title", "description", "operation", "action")).lower()
    budget = (company or {}).get("budget") or {}
    remaining = budget.get("remaining_usd", budget.get("available_usd", budget.get("max_usd")))
    if remaining is None:
        remaining = (company or {}).get("budget_remaining_usd")
    reasons: list[str] = []
    categories = {
        "external communication": ("send", "email", "message", "contact", "outreach"),
        "publish/deploy": ("publish", "post", "deploy", "production"),
        "credentials/provisioning": ("credential", "secret", "api key", "provision"),
        "money": ("purchase", "pay", "charge", "transfer", "refund"),
        "deletion": ("delete", "remove", "destroy"),
    }
    for label, terms in categories.items():
        if any(term in text for term in terms):
            reasons.append(label)
    explicit_risk = str(task.get("risk_category") or task.get("action_category") or "").lower()
    if explicit_risk in {"external", "publish", "deploy", "credentials", "provisioning", "money", "deletion"}:
        reasons.append(explicit_risk)
    if task.get("external") or task.get("requires_credentials") or task.get("irreversible"):
        reasons.append("explicit task risk")
    if proposed_spend > 0:
        reasons.append("spend")
    if remaining is not None and proposed_spend > float(remaining):
        reasons.append("spend above budget")
    # Auto is intentionally an allowlist. A new operation type cannot become
    # executable merely because it was omitted from the risk keyword lists.
    if not reasons and not any(term in text for term in _AUTO_TERMS):
        reasons.append("unclassified operation")
    decision = "require_approval" if reasons else "auto"
    return {"decision": decision, "reasons": reasons, "proposed_spend": proposed_spend,
            "policy_version": "company-os-dispatch-v1", "decided_at": _utcnow()}


def dispatch_intent(company_id: str, intent: str, *, proposed_spend: float = 0.0, forced_initiative_id: str | None = None) -> dict[str, Any]:
    """Create initiative, squad, mission, and specialist tasks for an intent.

    forced_initiative_id lets a caller that already knows this is a
    continuation (e.g. the copilot's LLM turn router, which understands
    typos and paraphrases the lexical matcher below can't) skip straight to
    reusing that initiative instead of guessing from wording alone.
    """
    company = _call("get_company_os", company_id=company_id) or {}
    reuse = None
    if forced_initiative_id:
        reuse = next((item for item in company.get("initiatives", [])
                      if _entity_id(item, "initiative_id") == forced_initiative_id and item.get("state") != "archived"), None)
    if reuse is not None:
        department = reuse.get("department") or choose_department(intent)[0]
        squad_name = _SQUADS.get(department, _SQUADS[_DEFAULT_DEPARTMENT])
    else:
        department, squad_name = choose_department(intent)
        # Squads used to be reused across ANY active initiative in the same
        # department, keyed only on department -- with no topic check. That silently
        # merged unrelated asks (e.g. a fresh "cookie clicker monetization" question
        # landing inside an existing "Big Pharma consulting" research initiative)
        # into one initiative, corrupting the acknowledgement text and evidence
        # trail. Now a new dispatch reuses an existing initiative + squad only when
        # its wording is actually close to one already active in the same
        # department (re-asking the same thing, or a light rephrasing of it);
        # a genuinely different ask in the same department still gets its own.
        same_department_active = [item for item in company.get("initiatives", []) if item.get("state") != "archived" and item.get("department") == department]
        reuse = _find_continuation(intent, same_department_active)
    if reuse:
        initiative = reuse
        initiative_id = _entity_id(initiative, "initiative_id")
        squad = next((item for item in company.get("squads", []) if item.get("initiative_id") == initiative_id and item.get("state") != "archived"), None)
        if squad is None:
            squad = _call("create_squad", company_id=company_id, initiative_id=initiative_id, name=squad_name, department=department)
        squad_id = _entity_id(squad, "squad_id")
    else:
        initiative = _call("create_initiative", company_id=company_id, name=intent, department=department, state="active")
        initiative_id = _entity_id(initiative, "initiative_id")
        squad = _call("create_squad", company_id=company_id, initiative_id=initiative_id, name=squad_name, department=department)
        squad_id = _entity_id(squad, "squad_id")
    mission = _call("create_mission", company_id=company_id, initiative_id=initiative_id, squad_id=squad_id, name=intent, department=department, state="active")
    mission_id = _entity_id(mission, "mission_id")
    created_tasks = []
    for spec in specialist_task_plan(department, intent):
        policy = enforce_dispatch_policy(spec, company=company, proposed_spend=proposed_spend)
        task = _call("create_task", company_id=company_id, initiative_id=initiative_id, squad_id=squad_id, mission_id=mission_id,
                     name=spec["title"], description=spec["description"], department=department, operation=spec["operation"],
                     state="pending" if policy["decision"] == "auto" else "awaiting_approval", policy_decision=policy)
        _record_policy(company_id, task, policy)
        if policy["decision"] == "require_approval":
            _create_approval_card(company_id, task, policy)
        created_tasks.append(task)
    return {"department": department, "squad": squad, "initiative": initiative, "mission": mission, "tasks": created_tasks}


def execute_task(company_id: str, task: Mapping[str, Any], executor: Callable[[Mapping[str, Any]], Any], *,
                 proposed_spend: float = 0.0, idempotency_key: str | None = None) -> dict[str, Any]:
    """Execute a task only after policy and durable duplicate checks.

    Every in-module executor, including the scheduler, must call this function.
    """
    company = _call("get_company_os", company_id=company_id) or {}
    policy = enforce_dispatch_policy(task, company=company, proposed_spend=proposed_spend)
    _record_policy(company_id, task, policy)
    if policy["decision"] != "auto":
        approval = _create_approval_card(company_id, task, policy)
        return {"status": "awaiting_approval", "policy": policy, "approval_task": approval}
    key = idempotency_key or _attempt_key(company_id, task)
    existing = _existing_attempt(company, key)
    if existing:
        return {"status": "duplicate", "attempt": existing, "idempotency_key": key}
    task_id = _entity_id(task, "task_id")
    _call("update_task", company_id=company_id, task_id=task_id, state="working")
    # One inline retry before giving up. A research task fails whenever a
    # single web search comes back thin (rate limit, one weak query) -- that's
    # a flaky call, not a broken task, and terminally blocking the whole
    # mission on the first attempt was flooding squads into "blocked" for
    # transient reasons. A second consecutive failure still blocks for real.
    attempt: Any = None
    last_exc: Exception | None = None
    for attempt_number in range(2):
        attempt = _call("create_task_attempt", company_id=company_id, task_id=task_id,
                        idempotency_key=key if attempt_number == 0 else f"{key}:retry", state="running")
        attempt_id = _entity_id(attempt, "attempt_id")
        try:
            result = executor(task)
        except Exception as exc:
            last_exc = exc
            _call("update_task_attempt", company_id=company_id, attempt_id=attempt_id, state="failed", error=str(exc))
            continue
        _call("update_task_attempt", company_id=company_id, attempt_id=attempt_id, state="completed")
        last_exc = None
        break
    if last_exc is not None:
        _call("update_task", company_id=company_id, task_id=task_id, state="blocked", blocked_reason=str(last_exc))
        raise last_exc
    completed_at = _utcnow()
    if task.get("recurring") or task.get("cadence_seconds"):
        # A cadence task must re-arm for its next slot, not finish like a
        # one-shot task -- otherwise scheduler_tick's state filter permanently
        # excludes it after its first run and "recurring" never recurs again.
        _call("update_task", company_id=company_id, task_id=task_id, state="scheduled", last_run_at=completed_at, completed_at=completed_at)
    else:
        _call("update_task", company_id=company_id, task_id=task_id, state="done", completed_at=completed_at)
    return {"status": "completed", "attempt": attempt, "result": result, "policy": policy, "idempotency_key": key}


def scheduler_tick(company_id: str, executor: Callable[[Mapping[str, Any]], Any], *, now: datetime | None = None) -> list[dict[str, Any]]:
    """Run due Company Operations tasks while honoring pause, cadence, and budget."""
    company = _call("get_company_os", company_id=company_id) or {}
    if company.get("global_pause") or (company.get("operations") or {}).get("global_pause"):
        return []
    now = now or datetime.now(timezone.utc)
    results = []
    for task in company.get("tasks") or []:
        if not _due(task, now) or task.get("state", task.get("status")) not in ("pending", "scheduled"):
            continue
        cadence = task.get("cadence_seconds")
        key = _attempt_key(company_id, task, now=now, cadence=cadence) if cadence else None
        results.append(execute_task(company_id, task, executor, proposed_spend=float(task.get("proposed_spend", 0) or 0), idempotency_key=key))
    return results


def _due(task: Mapping[str, Any], now: datetime) -> bool:
    cadence = task.get("cadence_seconds")
    if not cadence:
        return True
    last = task.get("last_run_at")
    if not last:
        return True
    try:
        return (now - datetime.fromisoformat(str(last).replace("Z", "+00:00"))).total_seconds() >= float(cadence)
    except ValueError:
        return True


def _id(record: Any) -> str | None:
    if not isinstance(record, Mapping):
        return None
    return record.get("id") or record.get("task_id")


def _entity_id(record: Any, key: str) -> str:
    if isinstance(record, Mapping) and record.get(key):
        return str(record[key])
    if isinstance(record, Mapping) and record.get("id"):
        return str(record["id"])
    raise ValueError(f"Company OS record is missing {key}")


def _attempt_key(company_id: str, task: Mapping[str, Any], *, now: datetime | None = None, cadence: float | None = None) -> str:
    # Without a time-bucketed slot, a recurring task's idempotency key never
    # changes, so _existing_attempt would report every later run as a
    # duplicate of the first one forever.
    slot: Any = task.get("cadence_slot", "")
    if cadence and now:
        slot = int(now.timestamp() // float(cadence))
    material = f"{company_id}:{_id(task) or task.get('title', '')}:{slot}"
    return hashlib.sha256(material.encode()).hexdigest()


def _existing_attempt(company: Mapping[str, Any], key: str) -> Mapping[str, Any] | None:
    for attempt in company.get("task_attempts") or []:
        if attempt.get("idempotency_key") == key:
            return attempt
    return None


def _record_policy(company_id: str, task: Mapping[str, Any], policy: Mapping[str, Any]) -> None:
    _call("append_event", company_id=company_id, event_type="policy.decided", payload={"task_id": _id(task), **dict(policy)})


def _create_approval_card(company_id: str, task: Mapping[str, Any], policy: Mapping[str, Any]) -> Any:
    return _call("create_approval", company_id=company_id, title=f"Approval required: {task.get('name') or task.get('title', 'task')}",
                 task_id=_id(task), detail="Review the policy-gated action before execution.",
                 department=task.get("department"), policy_decision=dict(policy))
