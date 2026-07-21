"""Department dispatch and safe execution for the Company OS.

This module deliberately owns orchestration, not persistence.  The Company OS
store is the source of truth and is accessed only through its small frozen
contract: ``get_company_os``, the five create functions, and ``append_event``.
"""
from __future__ import annotations

import hashlib
import importlib
import inspect
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

logger = logging.getLogger(__name__)


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
    """Create a validated semantic work request from the founder's outcome."""
    model_request = _extract_work_request_with_model(intent)
    if model_request is not None:
        return model_request
    # Last-resort deterministic recovery is limited to explicit outcome words;
    # it prevents a planner/provider hiccup from turning a self-contained
    # research request into an unnecessary founder clarification.
    lowered = intent.lower()
    if any(term in lowered for term in ("research", "compare", "viability", "competitive analysis", "evidence")):
        capabilities = {"research", "evidence research"}
        if "compare" in lowered or " versus " in lowered or " vs " in lowered:
            capabilities.add("compare")
        return {"version": 1, "objective": intent.strip(), "outcome": intent.strip(),
                "deliverables": ["validated research brief"], "acceptance_criteria": ["cited evidence"],
                "constraints": [], "entities": [], "dependencies": [], "risk": "internal",
                "required_capabilities": sorted(capabilities), "primary_capability": "research",
                "confidence": 0.72, "requires_clarification": False, "clarification_question": None,
                "clarification_options": None, "triage_reason": "explicit_research_recovery"}
    return {"version": 1, "objective": intent.strip(), "outcome": intent.strip(), "deliverables": [],
            "acceptance_criteria": [], "constraints": [], "entities": [], "dependencies": [],
            "risk": "internal", "required_capabilities": [], "primary_capability": None, "confidence": 0.0,
            "requires_clarification": True, "clarification_question": "What concrete outcome should this work produce?",
            "clarification_options": None,
            "triage_reason": "semantic_extraction_unavailable"}


def _extract_work_request_with_model(intent: str) -> dict[str, Any] | None:
    """Use the planner to describe work, then validate it against local capabilities."""
    from backend.tools._llm import generate, parse_json_response
    catalog = {head: sorted(profile["capabilities"]) for head, profile in CAPABILITY_REGISTRY.items()}
    prompt = f"""A founder sent this message to their company's AI operating system: {intent!r}
Extract a compact, structured description of the work this message is asking for.
Available capabilities: {catalog}
Return JSON only: {{"objective": string, "deliverables": [string], "acceptance_criteria": [string], "constraints": [string], "entities": [string], "dependencies": [string], "primary_capability": exact capability that owns the first deliverable, "required_capabilities": [exact capabilities from the catalog], "risk": "internal|external|approval", "clarification_question": string|null, "clarification_options": [string]|null, "confidence": number 0-1}}.
Reason over the meaning of the whole request, including misspellings and multiple outcomes. A product comparison needs compare and research. A website needs website or website delivery. Do not invent capabilities, and do not invent a comparison, audience, or platform the founder never mentioned.
A request to explain, describe, or research a specific named subject (a company, product, market, or person) is self-sufficient on its own -- proceed with the standard dimensions a competent analyst would cover (overview, business model, market position, competitors) rather than asking what to cover. Most requests are NOT ambiguous: default to reasonable assumptions and proceed. Only set clarification_question when the request is so vague the work genuinely cannot start at all (e.g. "build me an app" with no description of what it does) -- not to narrow scope, pick an emphasis, or confirm something you could reasonably infer. When you do ask, and the missing piece is naturally a short list of choices genuinely implied by the founder's own message, set clarification_options to 2-5 short answer strings drawn from that message; otherwise leave clarification_options null for an open-ended answer."""
    known = {capability for profile in CAPABILITY_REGISTRY.values() for capability in profile["capabilities"]}
    failures: list[str] = []
    # The strict instruction model is materially more reliable for a small
    # schema than the chat/fast model. Retry once rather than silently sending
    # a clear request into Operations because a provider emitted malformed JSON.
    for model in ("instruct", "large"):
        try:
            raw = generate(prompt, model=model, json_mode=True, max_tokens=650, temperature=0.0)
            payload = parse_json_response(raw)
            capabilities = {value for value in payload.get("required_capabilities", []) if isinstance(value, str) and value in known}
            confidence = float(payload.get("confidence", 0) or 0)
            if not capabilities or confidence < 0.45:
                failures.append(f"{model}: insufficient validated capabilities")
                continue
            clarification_question = payload.get("clarification_question") if isinstance(payload.get("clarification_question"), str) and payload.get("clarification_question").strip() else None
            raw_options = payload.get("clarification_options")
            clarification_options = [str(value) for value in raw_options if isinstance(value, str) and value.strip()] if isinstance(raw_options, list) else None
            return {"version": 1, "objective": str(payload.get("objective") or intent).strip(), "outcome": str(payload.get("objective") or intent).strip(),
                    "deliverables": [str(value) for value in payload.get("deliverables", []) if isinstance(value, str)],
                    "acceptance_criteria": [str(value) for value in payload.get("acceptance_criteria", []) if isinstance(value, str)],
                    "constraints": [str(value) for value in payload.get("constraints", []) if isinstance(value, str)],
                    "entities": [str(value) for value in payload.get("entities", []) if isinstance(value, str)],
                    "dependencies": [str(value) for value in payload.get("dependencies", []) if isinstance(value, str)],
                    "risk": str(payload.get("risk") or "internal"), "required_capabilities": sorted(capabilities), "confidence": min(confidence, 1.0),
                    "requires_clarification": clarification_question is not None,
                    "clarification_question": clarification_question,
                    "clarification_options": clarification_options or None,
                    "router_model": model,
                    "primary_capability": payload.get("primary_capability") if payload.get("primary_capability") in known else None}
        except Exception as exc:
            failures.append(f"{model}: {type(exc).__name__}")
    logger.warning("Semantic work-request extraction failed: %s", "; ".join(failures))
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
    primary_capability = request.get("primary_capability")
    if isinstance(primary_capability, str):
        primary_candidates = [entry for entry in scored if primary_capability in CAPABILITY_REGISTRY[entry[2]]["capabilities"]]
        if primary_candidates:
            score, matched, department, load = primary_candidates[0]
    # Research is a first-class department capability. If the planner emits a
    # research/evidence capability, never let a tie or missing primary field
    # fall through to the Company Operations default.
    if required & {"research", "evidence research", "competitive analysis", "compare"}:
        department = "research"
        profile = CAPABILITY_REGISTRY[department]
        matched = len(required & set(profile["capabilities"]))
        load = _active_load(company, department)
        score = matched * 10 - load * 2
    profile = CAPABILITY_REGISTRY[department]
    triage = bool(request.get("requires_clarification")) or matched == 0 or float(request.get("confidence", 0)) < 0.45
    handoffs = [entry[2] for entry in scored if entry[1] > 0 and entry[2] != department][:2]
    return {"department": department, "squad_name": profile["squad"], "score": score, "matched_capabilities": matched,
            "load": load, "requires_clarification": triage, "director": department, "handoffs": handoffs, "primary_capability": primary_capability}


def choose_department(intent: str) -> tuple[str, str]:
    """Compatibility wrapper for callers; routes through capabilities."""
    route = route_work_request({}, infer_work_request(intent))
    return route["department"], route["squad_name"]


def specialist_task_plan(department: str, intent: str, *, request: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """Build a small safe plan from work shape, not a department template."""
    request = request or infer_work_request(intent)
    capabilities = set(request.get("required_capabilities") or [])
    research_capabilities = {"research", "compare", "evidence research", "competitive analysis"}
    website_capabilities = {"website", "landing page", "website delivery", "local preview"}
    # A mixed request can contain both website and research capabilities. The
    # department head owns the mission shape: a Research handoff must never be
    # handed website tasks just because the overall initiative also builds a
    # site. This keeps the visible squad activity honest and gives the runner
    # the correct MCP task contract.
    if department == "research" and research_capabilities & capabilities:
        steps = [
            ("Gather validated evidence", "internal_analysis", "astra_company_research"),
            ("Synthesize findings and uncertainties", "draft", None),
            ("Produce a decision brief", "draft", None),
        ]
    elif website_capabilities & capabilities:
        # These are local, reversible deliverables. A later explicit
        # publish/deploy task is the only action that may require approval.
        steps = [
            ("Define the local website brief", "internal_analysis", None),
            ("Create a local website preview", "local_preview", None),
            ("Prepare the publication decision", "internal_review", None),
            ("Publish the website to Vercel", "external_deploy", "vercel_deploy"),
        ]
    elif research_capabilities & capabilities:
        steps = [
            ("Gather validated evidence", "internal_analysis", "astra_company_research"),
            ("Synthesize findings and uncertainties", "draft", None),
            ("Produce a decision brief", "draft", None),
        ]
    else:
        steps = [
            ("Define acceptance criteria and constraints", "internal_analysis", None),
            ("Create a reviewable local deliverable", "draft", None),
            ("Review outcome and next actions", "internal_review", None),
        ]
    subject = _subject_for(request, intent)
    titles: list[str] = []
    descriptions: list[str] = []
    for index, (fallback_title, operation, mcp_tool) in enumerate(steps):
        # Pull the most specific title source for this lane. Per-subject
        # titles turn three copy-paste "Gather / Synthesize / Produce a
        # decision brief" rows with the goal pasted after each into rows
        # that each name what is actually happening to the user's input.
        if department == "research" and research_capabilities & capabilities:
            specific = _specific_research_title(operation, index, subject)
        elif website_capabilities & capabilities:
            specific = _specific_website_title(operation, subject)
        else:
            specific = _specific_generic_title(operation, subject)
        titles.append(specific or fallback_title)
        descriptions.append(_description_for(operation, index, capabilities))
    return [{"title": title, "description": description, "department": department,
             "operation": operation, "mcp_tool": mcp_tool,
             "execution_scope": "external" if operation == "external_deploy" else "local",
             "required_capabilities": sorted(capabilities)}
            for title, description, (_, operation, mcp_tool) in zip(
                titles, descriptions, steps)]


def _subject_for(request: Mapping[str, Any], intent: str) -> str:
    """Pick a short, specific subject token for the user's intent.

    Sources (first with usable signal wins): named entities from the
    planner, the first deliverable, or the explicit objective. Bare
    `intent` is NOT used -- when the planner didn't extract anything, the
    request was too vague to anchor titles, so callers fall back to a
    stable generic shape rather than smearing a long natural-language
    phrase into every title.
    """
    entities = [str(value).strip() for value in (request.get("entities") or []) if str(value).strip()]
    if entities:
        subject = ", ".join(entities[:3])
    else:
        first_deliverable = next(
            (str(value).strip() for value in (request.get("deliverables") or []) if str(value).strip()),
            None,
        )
        objective = str(request.get("objective") or "").strip()
        subject = first_deliverable or objective
    if not subject:
        return ""
    subject = " ".join(subject.split())
    if len(subject) > 60:
        subject = subject[:57].rstrip() + "\u2026"
    return subject


def _specific_research_title(operation: str, step_index: int, subject: str) -> str | None:
    if not subject or operation not in {"internal_analysis", "draft"}:
        return None
    if step_index == 0:
        return f"Gather validated evidence on {subject}"
    if step_index == 1:
        return f"Synthesize {subject} findings and uncertainties"
    return f"Produce decision brief on {subject}"


def _specific_website_title(operation: str, subject: str) -> str | None:
    if not subject:
        return None
    if operation == "internal_analysis":
        return f"Define the local website brief for {subject}"
    if operation == "local_preview":
        return f"Create a local preview of the {subject} site"
    if operation == "internal_review":
        return f"Prepare the publication decision for {subject}"
    if operation == "external_deploy":
        return f"Publish the {subject} website to Vercel"
    return None


def _specific_generic_title(operation: str, subject: str) -> str | None:
    if not subject:
        return None
    if operation == "internal_analysis":
        return f"Define acceptance criteria for {subject}"
    if operation == "draft":
        return f"Create a reviewable {subject} deliverable"
    if operation == "internal_review":
        return f"Review outcome and next actions for {subject}"
    return None


def _description_for(operation: str, step_index: int, capability_set: set[str]) -> str:
    """Describe what the operator actually does on this step.

    The original `"<title>. Outcome: <intent>"` template echoed the
    founder's goal into every row, which was both visually noisy
    (three rows that all end with the same sentence) and unhelpful
    (the squad panel never told the founder what each step *does*).
    """
    research_caps = {"research", "compare", "evidence research", "competitive analysis"}
    website_caps = {"website", "landing page", "website delivery", "local preview"}
    if research_caps & capability_set:
        if operation == "internal_analysis":
            return "Source cited evidence with named companies, dates, and URLs."
        if operation == "draft" and step_index == 1:
            return "Cross-reference findings, note open questions, and stress-test claims."
        if operation == "draft":
            return "Write the final decision brief per company OS standards."
    if website_caps & capability_set:
        if operation == "internal_analysis":
            return "Capture scope, audience, and success criteria for the local preview."
        if operation == "local_preview":
            return "Build and serve the website locally so the founder can review a working preview."
        if operation == "internal_review":
            return "Verify the preview is ready before requesting approval to publish."
        if operation == "external_deploy":
            return "Publish the approved website to Vercel under the founder's account."
    if operation == "internal_analysis":
        return "Define what \"done\" looks like and any constraints the plan must respect."
    if operation == "draft":
        return "Create a reviewable deliverable the founder can inspect before sign-off."
    if operation == "internal_review":
        return "Review the deliverable against its acceptance criteria and surface next actions."
    return "Complete this step before the mission advances."


def enforce_dispatch_policy(
    task: Mapping[str, Any], *, company: Mapping[str, Any] | None = None,
    proposed_spend: float = 0.0,
) -> dict[str, Any]:
    """The sole policy choke point for every executor in this module.

    A task is never rejected here: risky work becomes an approval card.  Explicit
    risk categories override benign wording so callers cannot label a deployment
    as a draft to bypass the gate.
    """
    operation = str(task.get("operation") or task.get("action") or "").lower()
    local_operations = {"internal_analysis", "draft", "local_preview", "internal_review", "prepare_approval"}
    # A local task label may describe a future action (for example,
    # "prepare the publication decision") without performing it. For typed
    # local operations the operation is authoritative; explicit side-effect
    # flags below still override this classification.
    text_fields = ("operation", "action") if operation in local_operations else ("title", "description", "operation", "action")
    text = " ".join(str(task.get(key, "")) for key in text_fields).lower()
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


def dispatch_intent(company_id: str, intent: str, *, proposed_spend: float = 0.0, forced_initiative_id: str | None = None,
                    work_request: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Create initiative, squad, mission, and specialist tasks for an intent.

    forced_initiative_id lets a caller that already knows this is a
    continuation (e.g. the copilot's LLM turn router, which understands
    typos and paraphrases the lexical matcher below can't) skip straight to
    reusing that initiative instead of guessing from wording alone.
    """
    company = _call("get_company_os", company_id=company_id) or {}
    work_request = dict(work_request or infer_work_request(intent))
    if work_request.get("requires_clarification"):
        return {"needs_clarification": True, "work_request": work_request}
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
                     mcp_tool=spec.get("mcp_tool"),
                     state="pending" if policy["decision"] == "auto" else "awaiting_approval", policy_decision=policy)
        _record_policy(company_id, task, policy)
        if policy["decision"] == "require_approval":
            _create_approval_card(company_id, task, policy)
        created_tasks.append(task)
    handoff_missions = []
    # A handoff is real work, not a label on the primary mission. Form a
    # bounded sibling squad under the same initiative so its lead owns the
    # work and Copilot can report one integrated initiative outcome.
    for handoff_department in route.get("handoffs", []):
        profile = CAPABILITY_REGISTRY[handoff_department]
        handoff_squad = _call("create_squad", company_id=company_id, initiative_id=initiative_id, name=profile["squad"],
                              department=handoff_department, capabilities=sorted(profile["capabilities"]), lead=handoff_department, lifecycle="formed")
        handoff_mission = _call("create_mission", company_id=company_id, initiative_id=initiative_id,
                                squad_id=_entity_id(handoff_squad, "squad_id"), name=f"{profile['squad']} support: {intent}",
                                department=handoff_department, state="active", initiative_director=route["director"], handoff_for=mission_id)
        for spec in specialist_task_plan(handoff_department, intent, request=work_request):
            policy = enforce_dispatch_policy(spec, company=company, proposed_spend=proposed_spend)
            task = _call("create_task", company_id=company_id, initiative_id=initiative_id, squad_id=_entity_id(handoff_squad, "squad_id"),
                         mission_id=_entity_id(handoff_mission, "mission_id"), name=spec["title"], description=spec["description"],
                         department=handoff_department, operation=spec["operation"], mcp_tool=spec.get("mcp_tool"),
                         state="pending" if policy["decision"] == "auto" else "awaiting_approval", policy_decision=policy)
            _record_policy(company_id, task, policy)
            if policy["decision"] == "require_approval":
                _create_approval_card(company_id, task, policy)
        handoff_missions.append(handoff_mission)
    # A website that incorporates comparison findings must not race ahead of
    # research, whether Product Delivery or Research happened to lead the
    # initiative. Attach the dependency to the website mission in either
    # topology rather than assuming it is always the primary mission.
    if {"website", "landing page", "website delivery", "local preview"} & set(work_request.get("required_capabilities") or []):
        all_missions = [mission, *handoff_missions]
        research_dependencies = [
            _entity_id(item, "mission_id") for item in all_missions
            if item.get("department") == "research" and _entity_id(item, "mission_id")
        ]
        for candidate in all_missions:
            if candidate.get("department") != "product_technical":
                continue
            candidate_id = _entity_id(candidate, "mission_id")
            dependencies = [item for item in research_dependencies if item != candidate_id]
            if not dependencies:
                continue
            _call("update_mission", company_id=company_id, mission_id=candidate_id,
                  depends_on_mission_ids=dependencies)
            updated = {**candidate, "depends_on_mission_ids": dependencies}
            if candidate_id == mission_id:
                mission = updated
            else:
                handoff_missions = [updated if _entity_id(item, "mission_id") == candidate_id else item for item in handoff_missions]
    return {"department": department, "squad": squad, "initiative": initiative, "mission": mission, "tasks": created_tasks,
            "work_request": work_request, "routing": route, "handoff_missions": handoff_missions}


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
    is_research = str(task.get("mcp_tool") or "") == "astra_company_research"
    for attempt_number in range(2):
        started = time.perf_counter()
        attempt = _call("create_task_attempt", company_id=company_id, task_id=task_id,
                        idempotency_key=key if attempt_number == 0 else f"{key}:retry", state="running",
                        profile="company_os_deep_research" if is_research else "company_os_default")
        attempt_id = _entity_id(attempt, "attempt_id")
        try:
            result = executor(task)
        except Exception as exc:
            last_exc = exc
            transient = _is_transient_error(exc)
            _call("update_task_attempt", company_id=company_id, attempt_id=attempt_id, state="failed", error=str(exc),
                  transient=transient, finished_at=_utcnow(), latency_ms=round((time.perf_counter() - started) * 1000))
            if transient and attempt_number == 0:
                from backend.config import settings
                time.sleep(float(settings.deep_research_backoff_seconds))
            continue
        # _store_artifact() (company_os_runner.py) returns research_metadata/
        # evidence_validation as its own top-level keys, not nested under a
        # "result" wrapper -- the erroneous .get("result") unwrap here always
        # resolved to None, so every research attempt's metadata/model/
        # provider/evidence_validation was silently persisted as empty.
        metadata = result if isinstance(result, Mapping) else {}
        research_meta = metadata.get("research_metadata") if isinstance(metadata.get("research_metadata"), Mapping) else {}
        _call("update_task_attempt", company_id=company_id, attempt_id=attempt_id, state="completed",
              finished_at=_utcnow(), latency_ms=round((time.perf_counter() - started) * 1000),
              model=research_meta.get("model"), provider=research_meta.get("provider"),
              research_metadata=dict(research_meta), evidence_validation=metadata.get("evidence_validation"))
        last_exc = None
        break
    if last_exc is not None:
        _call("update_task", company_id=company_id, task_id=task_id, state="blocked", blocked_reason=str(last_exc))
        if is_research:
            _call("create_approval", company_id=company_id,
                  title=f"Retry research: {task.get('name') or task.get('title', 'research task')}",
                  task_id=task_id, detail=str(last_exc), kind="research_retry", action="retry_task",
                  retry_available=True, attempt_count=2)
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


def _is_transient_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(token in text for token in ("429", "408", "500", "502", "503", "504", "timeout", "temporarily", "rate limit"))


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
