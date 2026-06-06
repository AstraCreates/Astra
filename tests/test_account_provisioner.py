from backend.provisioning.account_provisioner import build_provision_plan, _summarize


def test_build_provision_plan_for_idea_to_revenue_required_connectors():
    plan = build_provision_plan("idea_to_revenue", required_only=True, include_foundation=False)

    assert {item["key"] for item in plan["connectors"]} == {"github", "vercel"}
    assert plan["services"] == ["github", "vercel"]
    assert plan["manual_connectors"] == []


def test_build_provision_plan_includes_foundation_services_and_composio_apps():
    plan = build_provision_plan("sales", required_only=True, include_foundation=True)

    assert "github" in plan["services"]
    assert "vercel" in plan["services"]
    assert "sendgrid" in plan["services"]
    assert "supabase" in plan["services"]
    assert "composio" in plan["services"]
    assert "gmail" in plan["composio_apps"]
    assert "crm" in plan["manual_connectors"]


def test_build_provision_plan_tracks_notion_and_calendar_oauth_apps():
    plan = build_provision_plan("founder_ops", required_only=False, include_foundation=False)

    assert "notion" in plan["composio_apps"]
    assert "googlecalendar" in plan["composio_apps"]


def test_summarize_reports_oauth_app_results():
    lines = _summarize({
        "github": {"created": True},
        "vercel": {"created": False, "error": "skip"},
        "sendgrid": {"created": False, "error": "skip"},
        "supabase": {"created": False, "error": "skip"},
        "composio": {"created": True},
        "composio_oauth_apps": {
            "notion": {"connected": True},
            "linear": {"connected": False, "error": "Timed out completing OAuth for linear"},
        },
    })

    assert any("notion" in line and "connected via browser OAuth" in line for line in lines)
    assert any("linear" in line and "Timed out completing OAuth" in line for line in lines)


def test_google_sheets_uses_google_drive_oauth_app():
    plan = build_provision_plan("sales", required_only=False, include_foundation=False)
    assert "google_drive" in plan["composio_apps"]
