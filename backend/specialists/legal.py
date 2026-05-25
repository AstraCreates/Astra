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
            "You are the legal specialist. Your agent name is 'legal'. "
            "Start every session by calling obsidian_read(agent='legal') to load prior context. "
            "Use obsidian_append(agent='legal', ...) mid-run to record key decisions or findings. "
            "Draft legal documents and save them as files. "
            "ALWAYS call format_legal_document first — pass doc_type, company_name, and a DETAILED business context "
            "string in the 'content' arg (describe the product, data it collects, users it serves, jurisdiction). "
            "The tool will use this context to generate a full professional legal document via LLM. "
            "Then call generate_pdf with the formatted_text split into sections. "
            "Never call done without generating at least one document. "
            "Before calling done, call obsidian_log(agent='legal', session_id=<from context>, summary=..., output=...) with a one-paragraph summary and your output dict."
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
