import logging
import os
import uuid

logger = logging.getLogger(__name__)


def generate_pdf(title: str, sections: list[dict], output_dir: str = "/tmp/astra_docs") -> dict:
    """
    Generate a PDF document from sections.
    sections: [{"heading": str, "body": str}]
    Returns local path. In production, upload to Supabase Storage.
    """
    os.makedirs(output_dir, exist_ok=True)
    filename = f"{title.lower().replace(' ', '_')}_{uuid.uuid4().hex[:8]}.pdf"
    filepath = os.path.join(output_dir, filename)

    try:
        from fpdf import FPDF

        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=20)
        pdf.add_page()
        pdf.set_margins(20, 20, 20)

        # Title
        pdf.set_font("Helvetica", "B", 18)
        pdf.cell(0, 12, title, new_x="LMARGIN", new_y="NEXT", align="C")
        pdf.ln(6)

        # Disclaimer
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(120, 120, 120)
        pdf.multi_cell(0, 5, "AI-generated document — not legal advice. Review with a licensed professional before signing.")
        pdf.set_text_color(0, 0, 0)
        pdf.ln(8)

        for section in sections:
            heading = section.get("heading", "")
            body = section.get("body", "")

            if heading:
                pdf.set_font("Helvetica", "B", 12)
                pdf.cell(0, 8, heading, new_x="LMARGIN", new_y="NEXT")
                pdf.ln(2)

            if body:
                pdf.set_font("Helvetica", "", 10)
                pdf.multi_cell(0, 6, body)
                pdf.ln(4)

        pdf.output(filepath)
        return {"generated": True, "path": filepath, "filename": filename}

    except ImportError:
        # Fallback: write plain text file
        txt_path = filepath.replace(".pdf", ".txt")
        with open(txt_path, "w") as f:
            f.write(f"{title}\n{'=' * len(title)}\n\n")
            f.write("AI-generated document — not legal advice.\n\n")
            for section in sections:
                if section.get("heading"):
                    f.write(f"\n{section['heading']}\n{'-' * len(section['heading'])}\n")
                if section.get("body"):
                    f.write(f"{section['body']}\n")
        return {"generated": True, "path": txt_path, "filename": os.path.basename(txt_path), "format": "txt"}

    except Exception as e:
        logger.error("generate_pdf failed: %s", e)
        return {"generated": False, "error": str(e)}
