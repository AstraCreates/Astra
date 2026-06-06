import asyncio
import imaplib

from backend.provisioning.account_provisioner import build_provision_plan, get_founder_setup_status, get_zero_touch_readiness, _interaction_required_map, _summarize


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


def test_summarize_reports_human_step_required():
    lines = _summarize({
        "github": {"created": True},
        "vercel": {"created": True},
        "sendgrid": {"created": True},
        "supabase": {"created": True},
        "composio": {"created": True},
        "composio_oauth_apps": {
            "linear": {
                "connected": False,
                "requires_human": True,
                "next_step": "Complete the verification challenge in-browser, then resume the integration flow.",
            },
        },
    })

    assert any("linear" in line and "human step required" in line for line in lines)


def test_interaction_required_map_returns_only_human_gated_apps():
    interaction = _interaction_required_map({
        "composio_oauth_apps": {
            "linear": {
                "connected": False,
                "requires_human": True,
                "category": "anti_bot",
            },
            "notion": {
                "connected": False,
                "error": "Timed out",
            },
            "github": {
                "connected": True,
            },
        }
    })

    assert interaction == {
        "linear": {
            "connected": False,
            "requires_human": True,
            "category": "anti_bot",
        }
    }


def test_google_sheets_uses_google_drive_oauth_app():
    plan = build_provision_plan("sales", required_only=False, include_foundation=False)
    assert "google_drive" in plan["composio_apps"]


def test_get_founder_setup_status_surfaces_saved_and_live_composio_apps(monkeypatch):
    monkeypatch.setattr(
        "backend.provisioning.account_provisioner.load_all_credentials",
        lambda founder_id: {
            "composio": {"api_key": "cmp_live"},
            "notion": {"connected": True, "connected_via": "composio_oauth", "composio_app": "notion"},
        },
    )
    monkeypatch.setattr(
        "backend.tools.integration_connect.get_composio_app_status",
        lambda founder_id: {"linear": True, "googlecalendar": True, "google_drive": True},
    )

    status = asyncio.run(get_founder_setup_status("founder-1"))

    assert status["composio"] is True
    assert status["apps"]["notion"] is True
    assert status["apps"]["linear"] is True
    assert status["apps"]["product_tracker"] is True
    assert status["apps"]["google_calendar"] is True
    assert status["apps"]["google_drive"] is True
    assert status["apps"]["google_sheets"] is True


def test_zero_touch_readiness_reports_missing_antibot_and_bad_imap(monkeypatch):
    monkeypatch.setattr("backend.config.settings.composio_api_key", "cmp_live", raising=False)
    monkeypatch.setattr("backend.config.settings.test_email_base", "astra.testingmail@gmail.com", raising=False)
    monkeypatch.setattr("backend.config.settings.test_email_imap_password", "bad password", raising=False)
    monkeypatch.setattr("backend.config.settings.test_email_web_password", "", raising=False)
    monkeypatch.setattr("backend.config.settings.browser_proxy_server", "", raising=False)
    monkeypatch.setattr("backend.config.settings.capsolver_extension_path", "", raising=False)

    class FailingImap:
        def __init__(self, *args, **kwargs):
            pass
        def login(self, email_address, password):
            raise imaplib.IMAP4.error("bad creds")
        def logout(self):
            return None

    monkeypatch.setattr("backend.provisioning.account_provisioner.imaplib.IMAP4_SSL", FailingImap)

    readiness = get_zero_touch_readiness()

    assert readiness["ready"] is False
    assert readiness["shared_inbox"]["imap_auth_ok"] is False
    assert readiness["shared_inbox"]["web_password_configured"] is False
    assert readiness["browser_runtime"]["anti_bot_ready"] is False
    assert any("IMAP authentication failed" in blocker for blocker in readiness["blockers"])
    assert any("TEST_EMAIL_WEB_PASSWORD" in blocker for blocker in readiness["blockers"])
    assert any("anti-bot bypass" in blocker for blocker in readiness["blockers"])
