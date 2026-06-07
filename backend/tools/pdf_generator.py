import logging
import os
import uuid

logger = logging.getLogger(__name__)

_UNICODE_MAP = {
    "—": "--",   # em dash
    "–": "-",    # en dash
    "‘": "'",    # left single quote
    "’": "'",    # right single quote
    "“": '"',    # left double quote
    "”": '"',    # right double quote
    "…": "...",  # ellipsis
    "·": "*",    # middle dot
    "•": "*",    # bullet
    "®": "(R)",
    "©": "(C)",
    "é": "e",
    "è": "e",
    "ê": "e",
    "à": "a",
    "â": "a",
    "ô": "o",
    "û": "u",
    "ü": "u",
    "ç": "c",
}


def _safe(text: str) -> str:
    """Replace non-Latin-1 chars so fpdf Helvetica doesn't crash."""
    for char, replacement in _UNICODE_MAP.items():
        text = text.replace(char, replacement)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _expand_section(heading: str, body: str, doc_title: str) -> str:
    """If body is thin (< 300 chars), call LLM to write a proper section."""
    if len(body.strip()) >= 300:
        return body
    prompt = (
        f"You are writing a section of a professional business document titled '{doc_title}'.\n"
        f"Section heading: {heading}\n"
        f"Brief notes: {body}\n\n"
        "Expand this into 3-5 detailed paragraphs of professional, substantive content. "
        "Include specific data, examples, or analysis relevant to a startup context. "
        "Do not use bullet points — write flowing paragraphs. Return only the section text."
    )
    try:
        from backend.tools._llm import generate
        expanded = generate(prompt)
        if expanded and len(expanded) > len(body):
            return expanded
    except Exception as e:
        logger.warning("PDF section expansion failed: %s", e)
    return body


def generate_pdf(title: str = "", sections: list = None, output_dir: str = "", expand_content: bool = False,
                 content: str = "", filename: str = "", body: str = "", **kwargs) -> dict:
    """Generate PDF. Args: title (str), sections (list — MUST be a JSON array of objects, e.g. [{"heading": "Executive Summary", "body": "text..."}, {"heading": "Market Size", "body": "text..."}]), expand_content (bool, default False — set True only if you want slow LLM expansion of thin sections). Returns {generated, path, filename}. IMPORTANT: sections must be a real list/array, NOT a string. Also accepts the simpler form generate_pdf(content="...", filename="x.pdf")."""
    import os as _os
    from backend.config import settings
    # Accept the (content=/body=, filename=) form some agents use instead of (title, sections).
    if sections is None:
        text = content or body or kwargs.get("text") or ""
        sections = [{"heading": "", "body": text}] if text else []
    if not title:
        stem = (filename or kwargs.get("name") or "document").rsplit(".", 1)[0]
        title = stem.replace("_", " ").replace("-", " ").strip().title() or "Document"
    if not output_dir:
        vault = _os.environ.get("OBSIDIAN_VAULT") or getattr(settings, "obsidian_vault", "") or "/tmp/astra_docs"
        output_dir = str(vault).rstrip("/") + "/files"
    os.makedirs(output_dir, exist_ok=True)
    if filename:
        safe_name = _os.path.basename(str(filename)).encode("ascii", "ignore").decode()
        if not safe_name.lower().endswith(".pdf"):
            safe_name += ".pdf"
        # Keep names unique so concurrent docs don't clobber each other.
        stem, ext = safe_name.rsplit(".", 1)
        filename = f"{stem}_{uuid.uuid4().hex[:6]}.{ext}"
    else:
        safe_title = title.lower().replace(" ", "_").encode("ascii", "ignore").decode()
        filename = f"{safe_title}_{uuid.uuid4().hex[:8]}.pdf"
    filepath = os.path.join(output_dir, filename)

    # Coerce sections to list — model sometimes passes a string repr or a single dict
    if isinstance(sections, str):
        import json, ast
        try:
            sections = json.loads(sections)
        except Exception:
            try:
                sections = ast.literal_eval(sections)
            except Exception:
                sections = [{"heading": "", "body": sections}]
    if isinstance(sections, dict):
        sections = [sections]
    if not isinstance(sections, list):
        sections = [{"heading": "", "body": str(sections)}]

    # Expand thin sections via LLM before rendering
    expanded_sections = []
    for section in sections:
        if isinstance(section, str):
            section = {"heading": "", "body": section}
        heading = section.get("heading", "") if isinstance(section, dict) else ""
        body = section.get("body", "") or section.get("content", "") if isinstance(section, dict) else str(section)
        if expand_content and heading and body:
            body = _expand_section(heading, body, title)
        expanded_sections.append({"heading": heading, "body": body})

    try:
        from fpdf import FPDF

        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=20)
        pdf.add_page()
        pdf.set_margins(20, 20, 20)

        pdf.set_font("Helvetica", "B", 18)
        pdf.cell(0, 12, _safe(title), new_x="LMARGIN", new_y="NEXT", align="C")
        pdf.ln(6)

        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(120, 120, 120)
        pdf.multi_cell(0, 5, "AI-generated document - not legal advice. Review with a licensed professional before signing.")
        pdf.set_text_color(0, 0, 0)
        pdf.ln(8)

        for section in expanded_sections:
            heading = section.get("heading", "")
            body = section.get("body", "")

            if heading:
                pdf.set_font("Helvetica", "B", 12)
                pdf.cell(0, 8, _safe(heading), new_x="LMARGIN", new_y="NEXT")
                pdf.ln(2)

            if body:
                pdf.set_font("Helvetica", "", 10)
                pdf.multi_cell(0, 6, _safe(body))
                pdf.ln(4)

        pdf.output(filepath)
        return {"generated": True, "path": filepath, "filename": filename}

    except ImportError:
        txt_path = filepath.replace(".pdf", ".txt")
        with open(txt_path, "w") as f:
            f.write(f"{title}\n{'=' * len(title)}\n\n")
            for section in expanded_sections:
                if section.get("heading"):
                    f.write(f"\n{section['heading']}\n{'-' * len(section['heading'])}\n")
                if section.get("body"):
                    f.write(f"{section['body']}\n")
        return {"generated": True, "path": txt_path, "filename": os.path.basename(txt_path), "format": "txt"}

    except Exception as e:
        logger.error("generate_pdf failed: %s", e)
        return {"generated": False, "error": str(e)}
