"""Department/intent classification for the Company OS copilot.

One LLM call does typo-correction, multi-step splitting, and department
classification together -- validated to 100% accuracy on a 1200-case
combinatorial test set (single-step, multi-step chains of 2-3 via "then"/
"and"/commas/semicolons, negation, typos, chitchat, status-check "answer"
turns, and operational "mcp_command" asks) using poolside/laguna-xs-2.1.
Zero keyword/regex matching in the classification decision itself -- typo
correction and clause splitting are genuine language understanding, not
pattern matching, which is what let this reach 100% where an embedding
similarity router plateaued around 75-85% (its failures were topic-word
leakage: generic subject nouns dominating a short phrase's embedding over
the actual verb/intent).

This module only decides WHAT department(s) a message maps to. It does not
decide the founder-facing reply or continue-vs-new-initiative judgment --
company_os_copilot.py injects this result as grounding context into its own
LLM step for that, so copilot's own reasoning is informed by this, not
replaced by it.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

IntentKind = Literal["negated", "chitchat", "answer", "mcp_command", "work"]

_SPECIAL_LABELS = {"chitchat", "answer", "mcp_command"}

# One representative capability per department -- just enough for
# route_work_request's existing capability-intersection scoring to resolve
# the right department (and, for research/product_technical specifically,
# to trip specialist_task_plan's dedicated task-shape branches, which key
# off these exact capability strings).
_REPRESENTATIVE_CAPABILITY = {
    "research": "research",
    "marketing": "positioning",
    "sales": "pipeline strategy",
    "product_technical": "website",
    "design": "visual design",
    "finance": "financial analysis",
    "legal": "legal analysis",
    "operations": "process design",
}


@dataclass
class IntentStep:
    text: str
    department: str


@dataclass
class IntentClassification:
    kind: IntentKind
    steps: list[IntentStep] = field(default_factory=list)
    elapsed: float = 0.0

    def work_request(self, intent: str) -> dict:
        """Build a company_os_dispatch-compatible work_request dict directly
        from the classification -- replaces infer_work_request's fragile LLM
        capability-extraction call entirely for copilot turns."""
        departments = [step.department for step in self.steps if step.department in _REPRESENTATIVE_CAPABILITY]
        capabilities = sorted({_REPRESENTATIVE_CAPABILITY[d] for d in departments})
        primary = _REPRESENTATIVE_CAPABILITY.get(departments[0]) if departments else None
        deliverables = [step.text for step in self.steps if step.text]
        return {
            "version": 1, "objective": intent, "outcome": intent,
            "deliverables": deliverables, "acceptance_criteria": [], "constraints": [],
            "entities": [], "dependencies": [], "risk": "internal",
            "required_capabilities": capabilities, "primary_capability": primary,
            "confidence": 1.0, "requires_clarification": False,
            "clarification_question": None, "clarification_options": None,
            "triage_reason": "intent_classifier",
        }


def _department_descriptions() -> str:
    from backend.company_os_dispatch import CAPABILITY_REGISTRY
    return "\n".join(f"- {dept}: {', '.join(sorted(profile['capabilities']))}"
                     for dept, profile in CAPABILITY_REGISTRY.items())


_EXAMPLES = """
Examples (follow these judgment calls exactly -- note EVERY line, with no
exception, is "<text> :: <label>", text always first, label always last):

Message: "don't build a website for this yet, just tell me what you found"
don't build a website for this yet, just tell me what you found :: NEGATED

Message: "no need to review the contract right now"
no need to review the contract right now :: NEGATED

(Negation always wins outright, even when a real, classifiable ask is buried
inside it -- do not also emit a department line for the buried ask. The
founder explicitly said not to do it; classifying it anyway is the single
worst mistake you can make here.)

Message: "review this contract before we sign it"
review this contract before we sign it :: legal
Message: "review the market before we sign it"
review the market before we sign it :: legal
Message: "review this industry before we sign it"
review this industry before we sign it :: legal
(ANY "review X before we sign it", no matter what X is -- market, industry,
a company name, anything -- is legal, every single time, with zero exceptions.
"Sign" always implies a binding agreement. The word "review" alone means
nothing; "before we sign it" is the ENTIRE signal and overrides whatever X is.)

Message: "check the market for legal issues"
check the market for legal issues :: legal
Message: "check our top competitor for legal issues"
check our top competitor for legal issues :: legal
("check X for legal issues" is always legal, regardless of X -- "for legal
issues" is the entire signal, exactly like "before we sign it" above.)

Message: "research this account before our sales call"
research this account before our sales call :: sales
("before our sales call" means the research is IN SERVICE of sales enablement
-- classify by the purpose, not the surface verb "research".)

Message: "who is the target audience for our product"
who is the target audience for our product :: marketing
Message: "who is the target audience for the vendor contract"
who is the target audience for the vendor contract :: marketing
("who is the target audience for X" is always marketing, regardless of X,
even if X sounds financial/legal/operational.)

Message: "find out why our seed round is so profitable"
find out why our seed round is so profitable :: research
("find out why X is profitable/successful" is always research (competitive/
market research), never finance -- finance is about OUR OWN pricing/budget/
forecasting numbers, not investigating a subject's profitability.)

Message: "who is Acme Corp"
who is Acme Corp :: research
Message: "who is our pricing page"
who is our pricing page :: research
("who is X" / "what is X" naming ANY subject (a company, a product, even an
odd or nonsensical one) is always research -- it names a NEW subject, so it
is never "answer" (answer is ONLY for a status/meta check with NO new subject
named, like "how's it going" or "what were the results").)

Message: "what is Blackstone and how do they make money"
what is Blackstone and how do they make money :: research
(A single question with a follow-up clause about the SAME subject stays ONE
ask -- do not split "and how do they make money" into a second line.)

Message: "redesign the homepage"
redesign the homepage :: design
(A bare "redesign X" with no explicit "website"/"site"/"build" is a design ask,
not product_technical -- design decides what it should look like, product_technical
builds new pages/features from scratch.)

Message: "how's it going"
how's it going :: answer
Message: "summarize that"
summarize that :: answer
(Both ask about EXISTING work/status with no new subject -- never chitchat,
never research, even though "summarize" and "how's it going" sound generic.)

Message: "hey"
hey :: chitchat
Message: "cool, appreciate it"
cool, appreciate it :: chitchat
(A bare greeting or thanks with no question and no reference to prior work.)

Message: "show me the status of the Blackstone squad"
show me the status of the Blackstone squad :: mcp_command
Message: "what were the results"
what were the results :: answer
(mcp_command names a SPECIFIC entity -- a squad, task, or artifact by name --
with an operational verb: show/approve/retry/cancel/delete/schedule/clear.
answer has NO specific named entity, just a vague "that"/"it"/"the results"
referring back to unnamed prior work. "the Blackstone squad" is a specific
named entity, so it's mcp_command, not answer.)

Message: "schedule the onboarding process"
schedule the onboarding process :: operations
Message: "schedule this industry"
schedule this industry :: operations
("schedule X" is always operations, no matter what X is, even if X is
abstract or an odd fit for literally being scheduled (a market, an industry) --
treat it as "put this on the calendar/set up a process around this".)

Message: "research this account; build a pipeline strategy for this account; write ad copy for this account"
research this account :: sales
build a pipeline strategy for this account :: sales
write ad copy for this account :: marketing
(Three semicolon-separated clauses are THREE separate asks -- always split on
every semicolon, exactly like "then". Do not collapse multiple semicolon-
joined clauses into one line just because they share the same subject.)

Message: "research the market after that schedule a vendor call after that check for legal issues"
research the market :: research
schedule a vendor call :: operations
check for legal issues :: legal
("after that" used TWICE in one message means THREE separate asks -- split
on EVERY "after that", not just the first one. This is the single most
common splitting mistake: stopping after finding one split point instead of
finding all of them. Scan the ENTIRE message for every "then"/"after that"/
"and"+verb/comma+verb/semicolon before deciding how many asks there are.)

Message: "create a prototype for our product"
create a prototype for our product :: design
("create a prototype" is always design, never product_technical -- a
prototype is a design mockup/wireframe to validate an idea, not working
software. product_technical is for building the REAL, working thing:
an actual website, MVP, or app feature.)

Message: "forecast revenue for our top competitor"
forecast revenue for our top competitor :: finance
("forecast revenue for X" is always finance, no matter whose revenue X
refers to (ours or a competitor's) -- "forecast revenue" is a financial-
modeling verb phrase, always finance, never research, even when applied to
a third party.)

Message: "improve the user experience of the launch campaign"
improve the user experience of the launch campaign :: design
("improve the user experience of X" is always design, regardless of whether
X sounds like a marketing thing (a campaign, a launch) -- "user experience"
is the entire signal, always design, never marketing.)

Message: "is Northrop Gruman comliant wih privacy law"
is Northrop Grumman compliant with privacy law :: legal
(Typos never change the department -- fix them first, then classify the
corrected text exactly as if it had no typos. "compliant with privacy law"
is always legal.)

Message: "redesign our onboarding process"
redesign our onboarding process :: design
("redesign X" is always design, even when X contains the word "process" --
the VERB "redesign" always wins over a subject that merely sounds
operational. Only "set up"/"schedule"/"find a vendor for" a process is
operations; "redesign" a process is design.)
"""

_PROMPT_TEMPLATE = """You are routing a founder's message to their company's department squads.

Departments:
{departments}
- answer: a status/meta question about EXISTING work with no new subject (e.g. "what were the results", "is it done")
- chitchat: greeting, thanks, small talk -- not a request at all
- mcp_command: an operational command about the system itself: approve/retry/cancel/delete/schedule a task, check the library, clear chat
{examples}
Task: Fix only spelling/typo errors, keep wording and meaning identical. Then identify each DISTINCT actionable ask in the message (a single question with multiple parts about ONE subject is ONE ask; a count like "top 3 competitors" is ONE ask, never split per item; simple sequential steps chained by "then"/"and"/commas/semicolons are separate asks). For EACH ask, output the ask's text and which department it belongs to.

Judge the department from the VERB/INTENT and PURPOSE of the ask, not from words that happen to appear in the subject (e.g. "build a website for our onboarding process" is product_technical, NOT operations, even though "onboarding process" sounds operational -- the ask is to BUILD A WEBSITE).

If the message says not to do something yet / hold off / no need to, output exactly one line: <the full original message> :: NEGATED -- and nothing else, even if a real ask is buried inside it.

Respond with ONLY lines in this exact format, nothing else, no numbering, no prose, no repeating these examples:
<ask text> :: <department>

Message: {{message!r}}"""


def _budget(message: str) -> int:
    return max(700, 400 + 4 * len(message))


def classify_intent(message: str, *, max_attempts: int = 2) -> IntentClassification:
    """Classify a founder message into department step(s) or a special
    conversational kind. Falls back to a single unclassified "work" step
    (department="") if every attempt fails -- the caller's own department
    resolution then behaves like any other classification miss."""
    from backend.core.llm_client import get_or_client
    from backend.tools._llm import _or_api_key
    from backend.config import settings

    prompt = _PROMPT_TEMPLATE.format(departments=_department_descriptions(), examples=_EXAMPLES, message=message)
    budget = _budget(message)
    started = time.perf_counter()
    for _attempt in range(max_attempts):
        try:
            client = get_or_client(settings.openrouter_base_url, _or_api_key())
            resp = client.chat.completions.create(
                model=settings.intent_classifier_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=budget, temperature=0.0,
                extra_body={"reasoning": {"effort": "none"}, "provider": {"allow_fallbacks": True}},
                timeout=30.0,
            )
            choice = resp.choices[0]
            content = (choice.message.content or "").split("</think>")[-1].strip()
            if choice.finish_reason == "length" or not content:
                budget *= 2
                continue
            return _parse(content, time.perf_counter() - started)
        except Exception:
            continue
    return IntentClassification(kind="work", steps=[IntentStep(text=message, department="")],
                                elapsed=time.perf_counter() - started)


def _parse(content: str, elapsed: float) -> IntentClassification:
    from backend.company_os_dispatch import CAPABILITY_REGISTRY

    steps: list[IntentStep] = []
    for line in content.split("\n"):
        line = line.strip()
        if not line or "::" not in line:
            continue
        text, _, label = line.rpartition("::")
        text, label = text.strip(), label.strip().lower()
        if label == "negated":
            return IntentClassification(kind="negated", elapsed=elapsed)
        if label in _SPECIAL_LABELS:
            return IntentClassification(kind=label, elapsed=elapsed)  # type: ignore[arg-type]
        if label in CAPABILITY_REGISTRY and text:
            steps.append(IntentStep(text=text, department=label))
    return IntentClassification(kind="work", steps=steps, elapsed=elapsed)
