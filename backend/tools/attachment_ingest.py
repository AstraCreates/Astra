"""Turn uploaded files into agent-readable text.

- text/code/csv  → decoded as UTF-8
- PDF            → extracted text (pypdf)
- images         → transcribed + described by a vision model (OpenRouter)

Keeps the rest of the system text-only: every agent just reads the resulting
text, no multimodal plumbing required downstream.
"""
from __future__ import annotations

import io
import logging

logger = logging.getLogger(__name__)

MAX_CHARS = 20000
_VISION_MODEL = "google/gemini-2.5-flash"


def _truncate(text: str) -> tuple[str, bool]:
    if len(text) > MAX_CHARS:
        return text[:MAX_CHARS] + "\n…[truncated]", True
    return text, False


def extract_pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    parts = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n".join(p for p in parts if p.strip())


def describe_image(data: bytes, mime: str) -> str:
    """Transcribe and describe an image via an OpenRouter vision model."""
    import base64
    import openai
    from backend.config import settings
    from backend.core.key_rotator import get_openrouter_key

    b64 = base64.b64encode(data).decode("ascii")
    client = openai.OpenAI(
        base_url=settings.openrouter_base_url,
        api_key=get_openrouter_key() or settings.openrouter_api_key,
        default_headers={"HTTP-Referer": "https://astracreates.com", "X-Title": "Astra"},
    )
    resp = client.chat.completions.create(
        model=_VISION_MODEL,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": (
                    "Transcribe ALL visible text in this image verbatim, then briefly describe "
                    "its visual content (layout, charts, UI, diagrams) so an AI agent can use it. "
                    "Return plain text only."
                )},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ],
        }],
        temperature=0.1,
        timeout=120.0,
    )
    return (resp.choices[0].message.content or "").strip()


def ingest_attachment(filename: str, mime: str, data: bytes) -> dict:
    """Return {content, kind, truncated, error?} for an uploaded file."""
    name = (filename or "file").lower()
    mime = (mime or "").lower()
    try:
        if mime == "application/pdf" or name.endswith(".pdf"):
            text = extract_pdf_text(data)
            if not text.strip():
                return {"content": "", "kind": "pdf", "truncated": False,
                        "error": "No extractable text in this PDF (it may be scanned images)."}
            text, trunc = _truncate(text)
            return {"content": text, "kind": "pdf", "truncated": trunc}

        if mime.startswith("image/") or name.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
            desc = describe_image(data, mime or "image/png")
            if not desc:
                return {"content": "", "kind": "image", "truncated": False,
                        "error": "Could not read this image."}
            desc, trunc = _truncate(desc)
            return {"content": desc, "kind": "image", "truncated": trunc}

        # Default: treat as text.
        text = data.decode("utf-8", errors="replace")
        text, trunc = _truncate(text)
        return {"content": text, "kind": "text", "truncated": trunc}
    except Exception as e:
        logger.warning("ingest_attachment failed for %s: %s", filename, e)
        return {"content": "", "kind": "error", "truncated": False, "error": str(e)}
