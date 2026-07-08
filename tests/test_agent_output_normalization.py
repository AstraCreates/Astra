from pathlib import Path

from backend.core.agent import Agent
from backend.tools import vercel_deploy


def test_marketing_normalizes_ad_images():
    agent = Agent(name="marketing", role="m", tools={})
    output = {}
    normalized = agent._normalize_done_output(output, [
        ("generate_ad_image", {"image_url": "https://img.example/a.png", "prompt": "ad visual"}),
        ("generate_ad_image", {"base64": "a" * 120, "prompt": "ad visual 2"}),
    ])
    assert "ad_images" in normalized
    assert len(normalized["ad_images"]) == 2


def test_sales_normalizes_leads_sequences_and_contacts():
    agent = Agent(name="sales", role="s", tools={})
    normalized = agent._normalize_done_output({}, [
        ("find_leads", {"leads": [{"company": "Acme"}]}),
        ("build_outreach_sequence", {"lead": {"company": "Acme"}, "sequence": [{"send_day": 1, "subject": "Hi"}]}),
        ("build_crm_contact", {"company": "Acme", "email": "a@acme.com"}),
    ])
    assert normalized["leads"][0]["company"] == "Acme"
    assert normalized["sequence"][0]["subject"] == "Hi"
    assert normalized["crm_contacts"][0]["email"] == "a@acme.com"


def test_design_normalizes_design_spec_wireframes_logo():
    agent = Agent(name="design", role="d", tools={})
    normalized = agent._normalize_done_output({}, [
        ("generate_design_spec", {"product": "Astra"}),
        ("generate_wireframe", {"page_type": "landing"}),
        ("generate_logo_brief", {"direction": "minimal"}),
    ])
    assert normalized["design_spec"]["product"] == "Astra"
    assert normalized["wireframes"][0]["page_type"] == "landing"
    assert normalized["logo_brief"]["direction"] == "minimal"


def test_legal_normalizes_documents_from_tool_sequence():
    agent = Agent(name="legal", role="l", tools={})
    normalized = agent._normalize_done_output({}, [
        ("format_legal_document", {"doc_type": "privacy_policy", "formatted_text": "Policy text"}),
        ("generate_pdf", {"path": "/tmp/privacy_policy.pdf"}),
    ])
    assert normalized["documents"][0]["doc_type"] == "privacy_policy"
    assert normalized["documents"][0]["path"] == "/tmp/privacy_policy.pdf"


def test_marketing_content_normalizes_content_packages():
    agent = Agent(name="marketing_content", role="mc", tools={})
    normalized = agent._normalize_done_output({}, [
        ("generate_reel_package", {"script": "reel-1"}),
        ("generate_reel_package", {"script": "reel-2"}),
        ("generate_reel_package", {"script": "reel-3"}),
        ("generate_tiktok_package", {"script": "tt-1"}),
        ("generate_tiktok_package", {"script": "tt-2"}),
        ("generate_meta_ad", {"headline": "aware"}),
        ("generate_meta_ad", {"headline": "consider"}),
        ("generate_meta_ad", {"headline": "convert"}),
        ("generate_pdf", {"path": "/tmp/content_calendar.pdf"}),
    ])
    assert len(normalized["reel_scripts"]) == 3
    assert len(normalized["tiktok_packages"]) == 2
    assert normalized["meta_ads"]["awareness"]["headline"] == "aware"
    assert normalized["meta_ads"]["conversion"]["headline"] == "convert"
    assert normalized["content_calendar_pdf"] == "/tmp/content_calendar.pdf"


def test_web_normalizes_repo_and_deploy_from_tool_results():
    agent = Agent(name="web", role="w", tools={})
    normalized = agent._normalize_done_output({}, [
        ("github_create_repo", {"repo_url": "https://github.com/acme/site"}),
        ("run_mvp_loop", {
            "repo_url": "https://github.com/acme/site",
            "deploy_url": "https://acme.vercel.app",
            "success": True,
            "build_passes": True,
            "files_in_repo": 18,
            "files_preview": ["app/page.tsx"],
        }),
    ])
    assert normalized["repo_url"] == "https://github.com/acme/site"
    assert normalized["deploy_url"] == "https://acme.vercel.app"
    assert normalized["success"] is True
    assert normalized["build_passes"] is True
    assert normalized["files_in_repo"] == 18


def test_web_requires_successful_mvp_build_output():
    agent = Agent(name="web", role="w", tools={})
    missing = agent._missing_required_output({
        "repo_url": "https://github.com/acme/site",
        "deploy_url": "https://acme.vercel.app",
        "success": False,
        "build_passes": False,
    })
    assert "success=True" in missing
    assert "build_passes=True" in missing


def test_technical_requires_successful_mvp_build_output():
    agent = Agent(name="technical", role="t", tools={})
    missing = agent._missing_required_output({
        "repo_url": "https://github.com/acme/app",
        "deploy_url": "https://acme.vercel.app",
        "files_in_repo": 3,
        "success": False,
        "build_passes": False,
    })
    assert "success=True" in missing
    assert "build_passes=True" in missing


def test_ops_normalizes_action_outputs():
    agent = Agent(name="ops", role="o", tools={})
    normalized = agent._normalize_done_output({}, [
        ("generate_pdf", {"path": "/tmp/ops.pdf"}),
        ("create_product_with_payment_link", {"payment_link_url": "https://buy.stripe.com/x"}),
        ("composio_linear_create_issue", {"ok": True, "title": "Launch checklist"}),
        ("composio_notion_create_page", {"ok": True, "title": "Ops SOP"}),
    ])
    assert normalized["pdf_path"] == "/tmp/ops.pdf"
    assert normalized["payment_setup"]["payment_link_url"] == "https://buy.stripe.com/x"
    assert normalized["linear_issue"]["title"] == "Launch checklist"
    assert normalized["notion_page"]["title"] == "Ops SOP"


def test_marketing_paid_requires_real_outputs():
    agent = Agent(name="marketing_paid", role="mp", tools={})
    missing = agent._missing_required_output({"pdf_path": "/tmp/paid.pdf", "meta_ads": [], "channel_split": None})
    assert "meta_ads[2+]" in missing
    assert "total_budget_usd" in missing
    assert "channel_split" in missing


def test_generate_landing_page_html_accepts_html_without_doctype(monkeypatch):
    def fake_run_claude(tmpdir, *_args, **_kwargs):
        Path(tmpdir, "index.html").write_text(
            "<html><head><title>X</title></head><body><h1>Custom</h1></body></html>",
            encoding="utf-8",
        )
        return ""

    monkeypatch.setattr("backend.tools.git_tools._run_claude", fake_run_claude)
    html = vercel_deploy.generate_landing_page_html(
        page_title="Acme",
        headline="Build faster",
        subheadline="A better way to ship.",
        value_props=["Fast", "Simple", "Reliable"],
        cta_text="Get started",
        cta_url="https://example.com",
        company_name="Acme",
        business_context="Use #112233 and #f5f5f5",
    )
    assert html.lower().startswith("<!doctype html>")
    assert "astra-fallback-template" not in html


def test_generate_landing_page_html_accepts_written_doctype_html(monkeypatch):
    def fake_run_claude(tmpdir, *_args, **_kwargs):
        Path(tmpdir, "index.html").write_text(
            "<!DOCTYPE html><html><body><h1>Custom page</h1></body></html>",
            encoding="utf-8",
        )
        return ""

    monkeypatch.setattr("backend.tools.git_tools._run_claude", fake_run_claude)
    html = vercel_deploy.generate_landing_page_html(
        page_title="Acme",
        headline="Build faster",
        subheadline="A better way to ship.",
        value_props=["Fast", "Simple", "Reliable"],
        cta_text="Get started",
        cta_url="https://example.com",
        company_name="Acme",
        business_context="Use #112233 and #f5f5f5",
    )
    assert "custom page" in html.lower()


def test_legal_entity_surfaces_confirmation_from_real_filer_url():
    """The real filer (llc_filing.file_llc_live) returns confirmation_url, not
    confirmation_number — only the safe-stub fallback returns the latter. A
    genuinely successful real filing must still surface a confirmation."""
    agent = Agent(name="legal_entity", role="le", tools={})
    normalized = agent._normalize_done_output({}, [
        ("file_llc_live", {"status": "submitted", "confirmation_url": "https://nwra.example/order/12345", "entity_type": "LLC"}),
    ])
    assert normalized["filing_confirmation"] == "https://nwra.example/order/12345"
    assert normalized["entity_type"] == "LLC"


def test_legal_entity_prefers_confirmation_number_when_present():
    agent = Agent(name="legal_entity", role="le", tools={})
    normalized = agent._normalize_done_output({}, [
        ("file_llc_live", {"status": "pending", "confirmation_number": "PENDING-ABC123"}),
    ])
    assert normalized["filing_confirmation"] == "PENDING-ABC123"
