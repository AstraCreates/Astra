from backend.provisioning.account_provisioner import build_provision_plan


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
