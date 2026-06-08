import logging
from datetime import date

logger = logging.getLogger(__name__)

DISCLAIMER = (
    "AI-generated document preparation — not legal advice. "
    "Review with a licensed attorney before signing."
)

DOC_TYPE_LABELS = {
    "founder_agreement": "Founder Agreement",
    "nda": "Non-Disclosure Agreement",
    "ip_assignment": "IP Assignment Agreement",
    "vesting_schedule": "Vesting Schedule",
    "privacy_policy": "Privacy Policy",
    "terms_of_service": "Terms of Service",
}

_DOC_PROMPTS = {
    "privacy_policy": """\
Draft a comprehensive Privacy Policy for {company_name}.
Context: {context}

Include these sections with full legal language:
1. Information We Collect (personal data, usage data, cookies)
2. How We Use Your Information
3. Data Sharing and Third Parties
4. Data Retention
5. Your Rights (GDPR / CCPA compliance)
6. Cookies and Tracking
7. Data Security
8. Children's Privacy (COPPA)
9. Changes to This Policy
10. Contact Information

Write complete, professional legal text for each section. Be specific and thorough.
Return only the document text, no meta-commentary.""",

    "terms_of_service": """\
Draft comprehensive Terms of Service for {company_name}.
Context: {context}

Include these sections with full legal language:
1. Acceptance of Terms
2. Description of Service
3. User Accounts and Registration
4. Acceptable Use Policy
5. Intellectual Property Rights
6. Payment and Billing (if applicable)
7. Disclaimers and Limitation of Liability
8. Indemnification
9. Termination
10. Governing Law and Dispute Resolution
11. Changes to Terms
12. Contact Information

Write complete, professional legal text for each section.
Return only the document text, no meta-commentary.""",

    "nda": """\
Draft a Mutual Non-Disclosure Agreement for {company_name}.
Context: {context}

Include: definitions of Confidential Information, obligations of receiving party,
exclusions from confidentiality, term and termination, remedies, governing law,
signature blocks.

Write complete, professional legal text. Return only the document text.""",

    "founder_agreement": """\
Draft a Founder Agreement for {company_name}.
Context: {context}

Include: roles and responsibilities, equity split and vesting schedule (4-year / 1-year cliff),
IP assignment, non-compete / non-solicitation, decision making authority,
departure provisions, dispute resolution.

Write complete, professional legal text. Return only the document text.""",

    "ip_assignment": """\
Draft an Intellectual Property Assignment Agreement for {company_name}.
Context: {context}

Include: assignment of all IP developed in connection with the company,
moral rights waiver, representations and warranties, consideration,
governing law, signature blocks.

Write complete, professional legal text. Return only the document text.""",
}


def format_legal_document(doc_type: str, company_name: str, content: str) -> dict:
    """Format a legal document. Args: doc_type (str, e.g. 'nda', 'privacy_policy', 'terms_of_service', 'founder_agreement', 'ip_assignment'), company_name (str), content (str, describe the business/context for the document). Returns {formatted_text, doc_type, company_name}."""
    label = DOC_TYPE_LABELS.get(doc_type, doc_type.replace("_", " ").title())
    today = date.today().isoformat()

    # Try LLM-generated full document body
    doc_body = _generate_doc_body(doc_type, company_name, content)

    formatted = (
        f"{'=' * 80}\n"
        f"{label.upper()}\n"
        f"Company: {company_name}\n"
        f"Date: {today}\n"
        f"{'=' * 80}\n\n"
        f"{doc_body}\n\n"
        f"{'=' * 80}\n"
        f"DISCLAIMER: {DISCLAIMER}\n"
        f"{'=' * 80}\n"
    )
    return {"formatted_text": formatted, "doc_type": doc_type, "company_name": company_name, "generated": True}


def _generate_doc_body(doc_type: str, company_name: str, context: str) -> str:
    """Call LLM to draft the document body. Falls back to the raw content string."""
    prompt_template = _DOC_PROMPTS.get(doc_type)
    if not prompt_template:
        # Unknown doc type — use whatever content the agent provided
        return context

    prompt = prompt_template.format(company_name=company_name, context=context or "a technology company")
    try:
        from backend.tools._llm import generate
        # Cap output — an unbounded legal doc took ~2 min each on the heavy model, so
        # legal (3+ docs) blew past timeouts. ~3k tokens is a complete policy/agreement.
        body = generate(prompt, max_tokens=3000)
        if body and len(body) > 200:
            return body
        logger.warning("LLM legal doc output too short (%d chars) — using raw content", len(body))
    except Exception as e:
        logger.warning("LLM legal doc generation failed (%s) — using raw content", e)

    return context
