from backend.tools.doc_generator import format_legal_document, DISCLAIMER


def test_format_adds_disclaimer(monkeypatch):
    monkeypatch.setattr("backend.tools._llm.generate", lambda *args, **kwargs: "A" * 220)
    doc = format_legal_document(
        doc_type="founder_agreement",
        company_name="AcmeCo",
        content="This is the agreement body.",
    )
    assert DISCLAIMER in doc["formatted_text"]


def test_format_includes_company_name(monkeypatch):
    monkeypatch.setattr("backend.tools._llm.generate", lambda *args, **kwargs: "A" * 220)
    doc = format_legal_document(
        doc_type="founder_agreement",
        company_name="AcmeCo",
        content="Agreement body here.",
    )
    assert "AcmeCo" in doc["formatted_text"]


def test_format_includes_content(monkeypatch):
    content = "Section 1: Equity split is 50/50."
    monkeypatch.setattr("backend.tools._llm.generate", lambda *args, **kwargs: content * 10)
    doc = format_legal_document(
        doc_type="nda",
        company_name="AcmeCo",
        content=content,
    )
    assert doc["generated"] is True
    assert "NON-DISCLOSURE AGREEMENT" in doc["formatted_text"]
