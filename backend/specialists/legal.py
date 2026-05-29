"""Legal specialist — generates NDAs, privacy policies, terms, patent landscape, LLC filing."""
from backend.core.agent import Agent
from backend.tools.obsidian_logger import obsidian_log, obsidian_read, obsidian_append
from backend.tools.pdf_generator import generate_pdf
from backend.tools.patent_search import patent_search
from backend.tools.doc_generator import format_legal_document
from backend.tools.llc_filing import file_llc_live


def build_legal_agent(**kwargs) -> Agent:
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
            "7. done — return {documents: [{doc_type, title, path, text}], patent_landscape: <summary string>}\n\n"
            "RULES: NEVER skip generate_pdf. Call it immediately after EACH format_legal_document. "
            "Use COMPANY_NAME from SHARED CONTEXT as the company name everywhere. "
            "Write FULL document content — not placeholders. "
            "done output MUST include documents array where each entry has path (the PDF filepath returned by generate_pdf)."
        ),
        tools={
            "generate_pdf": generate_pdf,
            "patent_search": patent_search,
            "format_legal_document": format_legal_document,
            "file_llc_live": file_llc_live,
            "obsidian_log": obsidian_log,
            "obsidian_read": obsidian_read,
            "obsidian_append": obsidian_append,
        },
        **kwargs,
    )
