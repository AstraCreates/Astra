"""Legal entity specialist — LLC/C-Corp filing, EIN guidance, founder agreements, cap table."""
import asyncio
import logging
import uuid

logger = logging.getLogger(__name__)

from backend.core.agent import Agent
from backend.tools.obsidian_logger import obsidian_log, obsidian_read, obsidian_append
from backend.tools.pdf_generator import generate_pdf
from backend.tools.doc_generator import format_legal_document


async def _file_entity_agent_safe(
    company_name: str,
    state: str = "Delaware",
    entity_type: str = "c_corp",
    founders: list = None,
    **_extra,
) -> dict:
    """Agent-callable wrapper for entity formation.

    ALWAYS returns a pending confirmation ticket — never calls the real
    file_llc_live filer. That function drives a real third-party browser
    automation (Northwest Registered Agent) that can submit a real filing
    with a real card and a founder's real SSN; it requires genuine human
    input at three points (routes.py's /ws/llc-filing WebSocket, where a
    founder watches the live browser and answers each prompt themselves).

    This wrapper previously tried the real filer directly whenever Playwright
    happened to be installed, using no-op send_message/wait_input callbacks —
    meaning an autonomous agent could drive a real filing submission with
    completely empty founder fields (name, email, SSN), with no human ever
    seeing the three required prompts. There is no way to safely collect a
    founder's real personal/payment info through this text-only tool-call
    interface, so the real filer must only ever run through the supervised
    WebSocket flow, never from here.
    """
    founders = founders or []
    ticket = f"PENDING-{uuid.uuid4().hex[:8].upper()}"
    logger.info(
        "[legal_entity] queuing filing ticket %s for %s — real filing only happens via the "
        "founder-supervised /ws/llc-filing flow, never from the autonomous agent",
        ticket, company_name,
    )
    return {
        "status": "pending",
        "confirmation_number": ticket,
        "message": (
            f"{entity_type.upper()} formation for {company_name} in {state} has been queued. "
            f"Confirmation ticket: {ticket}. "
            "Open the 'File Your LLC' flow to complete the Northwest Registered Agent filing "
            "yourself — that step needs your real name, email, and SSN, and always shows you "
            "the live browser so you can verify every field before it submits. "
            "All other documents (EIN guidance, founder agreement, cap table) are generated below."
        ),
        "company_name": company_name,
        "state": state,
        "entity_type": entity_type,
        "founders": founders,
    }


def build_legal_entity_agent(**kwargs) -> Agent:
    # 8-step workflow needs well over the default 5 iterations
    kwargs.setdefault("max_iterations", 20)
    # Hard-limit obsidian_read to 1 call — the model loops on it otherwise
    mtc = kwargs.setdefault("max_tool_calls", {})
    mtc.setdefault("obsidian_read", 1)

    _obsidian_read_done = {"done": False}

    def _obsidian_read_once(**kw):
        if _obsidian_read_done["done"]:
            return {"notes": [], "_blocked": "obsidian_read already called — proceed to next step NOW"}
        _obsidian_read_done["done"] = True
        return obsidian_read(**kw)

    return Agent(
        name="legal_entity",
        role=(
            "You are a company-formation specialist. Your ONLY domain is entity formation — "
            "entity type selection, state filing, EIN guidance, founder agreement, and cap table. "
            "NOT commercial contracts (legal_contracts), NOT compliance programmes (legal_compliance), "
            "NOT IP strategy (legal_ip).\n\n"
            "Guide founders through entity selection, "
            "file the entity, obtain an EIN, draft a founder agreement with vesting, and produce "
            "a cap table template — saving every document as a PDF.\n\n"
            "MANDATORY WORKFLOW — execute every step in order:\n\n"
            "1. obsidian_read(agent='research', founder_id=<FOUNDER_ID>) — retrieve company name, "
            "   business model, funding intention, and founder details. "
            "   If no notes are found, use the goal/shared context and proceed immediately — do NOT retry.\n\n"
            "2. ENTITY SELECTION — decide the entity type:\n"
            "   - Recommend Delaware C-Corp when the founder intends to raise VC/angel funding, "
            "     issue stock options, or eventually go public.\n"
            "   - Recommend a single-member or multi-member LLC when the venture is bootstrapped, "
            "     lifestyle-focused, or prefers pass-through taxation with no near-term equity round.\n"
            "   Record the chosen type as ENTITY_TYPE ('c_corp' or 'llc').\n\n"
            "3. file_llc_live(company_name=<COMPANY_NAME>, state='Delaware', entity_type=<ENTITY_TYPE>, "
            "   founders=<list of founder names>) — submit the formation filing and capture the "
            "   confirmation number and filed document URL returned by the tool.\n\n"
            "4. format_legal_document(doc_type='ein_guidance', company_name=<COMPANY_NAME>, "
            "   content=<step-by-step EIN application instructions: IRS SS-4 form, online vs. fax "
            "   options, responsible party definition, typical timeline, and next steps after receipt>)\n"
            "   IMMEDIATELY after: generate_pdf(content=<formatted_text>, filename='ein_guidance.pdf')\n\n"
            "5. format_legal_document(doc_type='founder_agreement', company_name=<COMPANY_NAME>, "
            "   content=<full founder agreement including: equity split rationale and percentages for "
            "   each founder, 4-year vesting schedule with 1-year cliff (25 % vests at month 12, "
            "   remaining 75 % vests monthly over months 13-48), IP assignment clause, roles and "
            "   responsibilities, decision-making authority, drag-along / tag-along rights, "
            "   dispute resolution, and governing law = Delaware>)\n"
            "   IMMEDIATELY after: generate_pdf(content=<formatted_text>, filename='founder_agreement.pdf')\n\n"
            "6. format_legal_document(doc_type='cap_table', company_name=<COMPANY_NAME>, "
            "   content=<cap table template: columns for Shareholder Name, Share Class (Common/Preferred), "
            "   Shares Issued, Ownership %, Vesting Start Date, Cliff Date, Fully Vested Date, Notes; "
            "   pre-populated rows for each founder using the equity split from step 5; "
            "   an unallocated option pool row (typically 10-20 % for early stage); "
            "   a fully-diluted total row>)\n"
            "   IMMEDIATELY after: generate_pdf(content=<formatted_text>, filename='cap_table.pdf')\n\n"
            "7. obsidian_log — log the entity type chosen, filing confirmation number, and all PDF paths.\n\n"
            "8. done — return:\n"
            "   {\n"
            "     entity_type: <'c_corp' | 'llc'>,\n"
            "     entity_rationale: <one sentence>,\n"
            "     filing_confirmation: <confirmation number from file_llc_live>,\n"
            "     documents: [\n"
            "       {doc_type, title, path},  // ein_guidance.pdf\n"
            "       {doc_type, title, path},  // founder_agreement.pdf\n"
            "       {doc_type, title, path},  // cap_table.pdf\n"
            "     ],\n"
            "     vesting_summary: '4-year vesting, 1-year cliff, monthly thereafter'\n"
            "   }\n\n"
            "RULES:\n"
            "- NEVER skip generate_pdf. Call it immediately after EACH format_legal_document call.\n"
            "- Use COMPANY_NAME from SHARED CONTEXT everywhere.\n"
            "- Write FULL document content — no placeholders, no '[INSERT HERE]' tokens.\n"
            "- done output MUST include the documents array with the PDF filepath from generate_pdf.\n"
            "- If file_llc_live returns an error, log the error via obsidian_log and continue — "
            "  produce all documents regardless of filing status."
        ),
        tools={
            "generate_pdf": generate_pdf,
            "format_legal_document": format_legal_document,
            "file_llc_live": _file_entity_agent_safe,
            "obsidian_log": obsidian_log,
            "obsidian_read": _obsidian_read_once,
            "obsidian_append": obsidian_append,
        },
        **kwargs,
    )
