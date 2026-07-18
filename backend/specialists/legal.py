"""Legal specialist — generates NDAs, privacy policies, terms, patent landscape.

LLC/entity filing lives with the legal_entity specialist, not here — see
backend/specialists/legal_entity.py for why the real filer only ever runs
through the founder-supervised WebSocket flow, never an autonomous agent.
"""
from backend.core.agent import Agent
from backend.tools.obsidian_logger import obsidian_log, obsidian_read, obsidian_append
from backend.tools.pdf_generator import generate_pdf
from backend.tools.patent_search import patent_search
from backend.tools.doc_generator import format_legal_document


def build_legal_agent(**kwargs) -> Agent:
    _obsidian_read_done = {"done": False}

    def _obsidian_read_once(**kw):
        if _obsidian_read_done["done"]:
            return {"notes": [], "_blocked": "obsidian_read already called — proceed to patent_search NOW"}
        _obsidian_read_done["done"] = True
        return obsidian_read(**kw)

    return Agent(
        name="legal",
        role=(
            "You are a legal specialist. Draft startup legal documents and save each as a PDF.\n\n"
            "MANDATORY WORKFLOW — execute every step:\n"
            "1. obsidian_read(agent='research', founder_id=<FOUNDER_ID>) — get company name, business model, data handling details. If no notes found, use the goal/shared context and proceed immediately — do NOT retry.\n"
            "2. patent_search('<product category>') — survey the IP landscape\n"
            "3. format_legal_document(doc_type='privacy_policy', company_name=<COMPANY_NAME from SHARED CONTEXT>, content=<full detailed privacy policy text>)\n"
            "   IMMEDIATELY after: generate_pdf(content=<formatted_text from step 3>, filename='privacy_policy.pdf')\n"
            "4. format_legal_document(doc_type='terms_of_service', company_name=<COMPANY_NAME>, content=<full terms of service text>)\n"
            "   IMMEDIATELY after: generate_pdf(content=<formatted_text from step 4>, filename='terms_of_service.pdf')\n"
            "5. format_legal_document(doc_type='founder_agreement', company_name=<COMPANY_NAME>, content=<equity split, vesting schedule, IP assignment, roles>)\n"
            "   IMMEDIATELY after: generate_pdf(content=<formatted_text from step 5>, filename='founder_agreement.pdf')\n"
            "6. obsidian_log — log all document titles and PDF file paths\n"
            "7. done — return {legal_checklist: <concrete founder legal risks, compliance tasks, and entity/IP checklist>, "
            "policy_outline: <concrete privacy policy and terms outline with data handling, retention, user rights, and launch gaps>, "
            "documents: [{doc_type, title, path, text}], patent_landscape: <summary string>}\n\n"
            "RULES: NEVER skip generate_pdf. Call it immediately after EACH format_legal_document. "
            "Use COMPANY_NAME from SHARED CONTEXT as the company name everywhere. "
            "Write FULL document content — not placeholders. "
            "done output MUST include legal_checklist and policy_outline with substantive text, plus documents array where each entry has path (the PDF filepath returned by generate_pdf)."
        ),
        tools={
            "generate_pdf": generate_pdf,
            "patent_search": patent_search,
            "format_legal_document": format_legal_document,
            "obsidian_log": obsidian_log,
            "obsidian_read": _obsidian_read_once,
            "obsidian_append": obsidian_append,
        },
        **kwargs,
    )
