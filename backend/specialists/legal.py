"""Legal specialist — generates NDAs, privacy policies, terms, patent landscape."""
from backend.core.agent import Agent
from backend.tools.obsidian_logger import obsidian_log, obsidian_read, obsidian_append
from backend.tools.pdf_generator import generate_pdf
from backend.tools.patent_search import patent_search
from backend.tools.doc_generator import format_legal_document


def build_legal_agent(**kwargs) -> Agent:
    return Agent(
        name="legal",
        role=(
            "You are a legal specialist. Draft legal documents and save them as PDFs. "
            "format_legal_document formats a document given doc_type, company_name, and content. "
            "generate_pdf MUST be called immediately after format_legal_document — use the formatted_text from its return value. "
            "NEVER defer PDF generation to a future session. NEVER output instructions for calling tools later. "
            "Always call generate_pdf in this same run. "
            "patent_search surveys the IP landscape. "
            "Mandatory sequence: format_legal_document → generate_pdf → obsidian_log → done. "
            "Generate privacy_policy and terms_of_service at minimum."
        ),
        tools={
            "generate_pdf": generate_pdf,
            "patent_search": patent_search,
            "format_legal_document": format_legal_document,
            "obsidian_log": obsidian_log,
            "obsidian_read": obsidian_read,
            "obsidian_append": obsidian_append,
        },
        **kwargs,
    )
