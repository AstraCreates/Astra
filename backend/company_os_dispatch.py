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
from difflib import get_close_matches
from datetime import datetime, timezone
from typing import Any, Callable, Mapping


CAPABILITY_REGISTRY: dict[str, dict[str, Any]] = {
    "research": {"squad": "Insights", "capabilities": {"research", "compare", "evidence research", "market analysis", "competitive analysis", "synthesis"}, "capacity": 3},
    "marketing": {"squad": "Growth", "capabilities": {"positioning", "campaign development", "audience strategy", "content"}, "capacity": 3},
    "sales": {"squad": "Revenue", "capabilities": {"pipeline strategy", "account research", "sales materials", "outreach drafting"}, "capacity": 3},
    "product_technical": {"squad": "Product Delivery", "capabilities": {"product delivery", "software engineering", "website", "landing page", "website delivery", "local preview", "technical architecture"}, "capacity": 3},
    "design": {"squad": "Experience", "capabilities": {"visual design", "user experience", "interaction design", "prototype"}, "capacity": 3},
    "finance": {"squad": "Planning", "capabilities": {"financial analysis", "budgeting", "forecasting", "pricing analysis"}, "capacity": 2},
    "legal": {"squad": "Risk", "capabilities": {"legal analysis", "compliance review", "contract review", "privacy review"}, "capacity": 2},
    "operations": {"squad": "Company Operations", "capabilities": {"operating systems", "process design", "scheduling", "vendor operations"}, "capacity": 3},
}
DEPARTMENT_HEADS = tuple(CAPABILITY_REGISTRY)
_DEFAULT_DEPARTMENT = "operations"

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
_CONTINUATION_OVERLAP_THRESHOLD = 0.55


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


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.lower()))


def infer_work_request(intent: str) -> dict[str, Any]:
    """Create an auditable, capability-first request without phrase routing.

    The registry contains capabilities, not intent keywords. A future model
    extractor may populate richer requirements; this local extraction remains
    deterministic and safe during model outages.
    """
    words = _tokens(intent)
    model_request = _extract_work_request_with_model(intent)
    if model_request is not None:
        return model_request
    capability_tokens = {token for profile in CAPABILITY_REGISTRY.values() for capability in profile["capabilities"] for token in _tokens(capability)}
    # Misspellings should not turn an otherwise clear work request into a
    # blocked "clarify" task. This normalizes only toward declared
    # capabilities, never toward arbitrary intent phrases.
    words = {get_close_matches(word, capability_tokens, n=1, cutoff=0.82)[0] if get_close_matches(word, capability_tokens, n=1, cutoff=0.82) else word for word in words}
    matches: list[tuple[int, str, set[str]]] = []
    for department, profile in CAPABILITY_REGISTRY.items():
        # Composite labels need at least two matching words. This stops the
        # word "research" in "account research" from hijacking a general
        # research request while preserving intentionally single-word skills.
        matched = {capability for capability in profile["capabilities"]
                   if (len(_tokens(capability)) == 1 and _tokens(capability) & words)
                   or len(_tokens(capability) & words) >= 2}
        if matched:
            matches.append((len(matched), department, matched))
    matches.sort(key=lambda item: (-item[0], item[1]))
    required = sorted({capability for _, _, values in matches for capability in values})
    confidence = min(0.95, 0.35 + 0.2 * (matches[0][0] if matches else 0))
    return {"version": 1, "outcome": intent.strip(), "deliverables": [], "constraints": [], "entities": [],
            "risk": "internal", "required_capabilities": required, "confidence": confidence,
            "requires_triage": not matches}


def _extract_work_request_with_model(intent: str) -> dict[str, Any] | None:
    """Use the planner to describe work, then validate it against local capabilities."""
    try:
        from backend.tools._llm import generate, parse_json_response
        catalog = {head: sorted(profile["capabilities"]) for head, profile in CAPABILITY_REGISTRY.items()}
        raw = generate(
            f"""Extract a compact work request for an AI company operating system.
Founder message: {intent!r}
Available capabilities: {catalog}
Return JSON only: {{\"outcome\": string, \"deliverables\": [string], \"constraints\": [string], \"entities\": [string], \"required_capabilities\": [exact capabilities from the catalog], \"confidence\": number 0-1}}.
Requests to compare products require the compare and research capabilities. Website requests require website delivery or website. Do not invent capabilities.""",
            model="fast", json_mode=True, max_tokens=500, temperature=0.1,
        )
        payload = parse_json_response(raw)
        known = {capability for profile in CAPABILITY_REGISTRY.values() for capability in profile["capabilities"]}
        capabilities = {value for value in payload.get("required_capabilities", []) if isinstance(value, str) and value in known}
        # Preserve unambiguous declared capability words found in the request
        # so a planner cannot accidentally drop "website" while focusing on a
        # secondary comparison or research deliverable.
        message_words = _tokens(intent)
        capabilities.update(
            capability for capability in known
            if len(_tokens(capability)) == 1 and _tokens(capability) & message_words
        )
        confidence = float(payload.get("confidence", 0) or 0)
        if not capabilities or confidence < 0.45:
            return None
        return {"version": 1, "outcome": str(payload.get("outcome") or intent).strip(),
                "deliverables": [str(value) for value in payload.get("deliverables", []) if isinstance(value, str)],
                "constraints": [str(value) for value in payload.get("constraints", []) if isinstance(value, str)],
                "entities": [str(value) for value in payload.get("entities", []) if isinstance(value, str)],
                "risk": "internal", "required_capabilities": sorted(capabilities), "confidence": min(confidence, 1.0),
                "requires_triage": False}
    except Exception:
        return None


def _active_load(company: Mapping[str, Any], department: str) -> int:
    return sum(1 for squad in company.get("squads", []) if squad.get("department") == department and squad.get("state") in {"active", "working", "review"})


def route_work_request(company: Mapping[str, Any], request: Mapping[str, Any]) -> dict[str, Any]:
    required = set(request.get("required_capabilities") or [])
    scored = []
    for department, profile in CAPABILITY_REGISTRY.items():
        capability_score = len(required & set(profile["capabilities"]))
        load = _active_load(company, department)
        score = capability_score * 10 - load * 2
        scored.append((score, capability_score, department, load))
    scored.sort(reverse=True)
    score, matched, department, load = scored[0]
    profile = CAPABILITY_REGISTRY[department]
    triage = bool(request.get("requires_triage")) or matched == 0 or float(request.get("confidence", 0)) < 0.45
    if triage:
        department = _DEFAULT_DEPARTMENT
        profile = CAPABILITY_REGISTRY[department]
    handoffs = [entry[2] for entry in scored[1:] if entry[1] > 0 and entry[2] != department][:2]
    return {"department": department, "squad_name": profile["squad"], "score": score, "matched_capabilities": matched,
            "load": load, "requires_triage": triage, "director": department, "handoffs": handoffs}


def choose_department(intent: str) -> tuple[str, str]:
    """Compatibility wrapper for callers; routes through capabilities."""
    route = route_work_request({}, infer_work_request(intent))
    return route["department"], route["squad_name"]


def specialist_task_plan(department: str, intent: str, *, request: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """Build a small safe plan from work shape, not a department template."""
    request = request or infer_work_request(intent)
    capabilities = set(request.get("required_capabilities") or [])
    if request.get("requires_triage"):
        titles = ["Clarify the requested outcome and required capabilities"]
    elif {"website", "landing page", "website delivery", "local preview"} & capabilities:
        titles = ["Clarify audience, offer, and constraints", "Create a local website preview", "Review the preview and prepare a publish approval"]
    elif "evidence research" in capabilities or "competitive analysis" in capabilities:
        titles = ["Gather validated evidence", "Synthesize findings and uncertainties", "Produce a decision brief"]
    else:
        titles = ["Define acceptance criteria and constraints", "Create a reviewable local deliverable", "Review outcome and next actions"]
    return [{"title": title, "description": f"{title}. Outcome: {intent}", "department": department,
             "operation": "internal_analysis" if index == 0 else "draft", "required_capabilities": sorted(capabilities)}
            for index, title in enumerate(titles)]


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
    work_request = infer_work_request(intent)
    reuse = None
    if forced_initiative_id:
        reuse = next((item for item in company.get("initiatives", [])
                      if _entity_id(item, "initiative_id") == forced_initiative_id and item.get("state") != "archived"), None)
    if reuse is not None:
        route = route_work_request(company, work_request)
        department = reuse.get("director") or reuse.get("department") or route["department"]
        squad_name = route["squad_name"]
    else:
        route = route_work_request(company, work_request)
        department, squad_name = route["department"], route["squad_name"]
        reuse = _find_continuation(intent, [item for item in company.get("initiatives", []) if item.get("state") != "archived"])
    if reuse:
        initiative = reuse
        initiative_id = _entity_id(initiative, "initiative_id")
        candidates = [item for item in company.get("squads", []) if item.get("initiative_id") == initiative_id and item.get("department") == department and item.get("state") != "archived"]
        active = [item for item in candidates if item.get("state") in {"active", "working", "review"}]
        capacity = CAPABILITY_REGISTRY[department]["capacity"]
        squad = next((item for item in active if sum(1 for mission in company.get("missions", []) if mission.get("squad_id") == item.get("squad_id") and mission.get("state") in {"active", "working", "review"}) < capacity), None)
        if squad is None:
            # A completed team retains its scoped context and can be reopened
            # before forming another duplicate squad for the same initiative.
            squad = next((item for item in reversed(candidates) if item.get("state") == "done"), None)
            if squad:
                _call("update_squad", company_id=company_id, squad_id=_entity_id(squad, "squad_id"), state="active", lifecycle="formed")
                squad = {**squad, "state": "active", "lifecycle": "formed"}
        if squad is None:
            squad = _call("create_squad", company_id=company_id, initiative_id=initiative_id, name=squad_name, department=department,
                          capabilities=sorted(CAPABILITY_REGISTRY[department]["capabilities"]), lead=department, lifecycle="formed")
        squad_id = _entity_id(squad, "squad_id")
    else:
        initiative = _call("create_initiative", company_id=company_id, name=intent, department=department, director=route["director"],
                           objective=work_request["outcome"], state="planned", work_request=work_request)
        initiative_id = _entity_id(initiative, "initiative_id")
        squad = _call("create_squad", company_id=company_id, initiative_id=initiative_id, name=squad_name, department=department,
                      capabilities=sorted(CAPABILITY_REGISTRY[department]["capabilities"]), lead=department, lifecycle="formed")
        squad_id = _entity_id(squad, "squad_id")
    mission = _call("create_mission", company_id=company_id, initiative_id=initiative_id, squad_id=squad_id, name=intent,
                    department=department, state="active", initiative_director=route["director"], handoff_requests=route.get("handoffs", []))
    mission_id = _entity_id(mission, "mission_id")
    created_tasks = []
    for spec in specialist_task_plan(department, intent, request=work_request):
        policy = enforce_dispatch_policy(spec, company=company, proposed_spend=proposed_spend)
        task = _call("create_task", company_id=company_id, initiative_id=initiative_id, squad_id=squad_id, mission_id=mission_id,
                     name=spec["title"], description=spec["description"], department=department, operation=spec["operation"],
                     state="pending" if policy["decision"] == "auto" else "awaiting_approval", policy_decision=policy)
        _record_policy(company_id, task, policy)
        if policy["decision"] == "require_approval":
            _create_approval_card(company_id, task, policy)
        created_tasks.append(task)
    return {"department": department, "squad": squad, "initiative": initiative, "mission": mission, "tasks": created_tasks,
            "work_request": work_request, "routing": route}


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
