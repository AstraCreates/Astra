from backend.control_plane.budget import get_default_budget_service


def test_default_budget_service_uses_fake_repo_when_supabase_not_configured(monkeypatch):
    import backend.control_plane.budget as budget

    monkeypatch.setattr(budget, "_default_service", None)
    monkeypatch.setattr("backend.config.settings.supabase_url", "")
    monkeypatch.setattr("backend.config.settings.supabase_key", "")

    service = get_default_budget_service()
    assert service._repo.__class__.__name__ == "FakeBudgetReservationRepository"


def test_default_budget_service_uses_supabase_repo_when_configured(monkeypatch):
    import backend.control_plane.budget as budget

    monkeypatch.setattr(budget, "_default_service", None)
    monkeypatch.setattr("backend.config.settings.supabase_url", "https://example.supabase.co")
    monkeypatch.setattr("backend.config.settings.supabase_key", "service-key")

    class StubRepo:
        pass

    monkeypatch.setattr(
        "backend.control_plane.supabase_repositories.SupabaseBudgetReservationRepository",
        StubRepo,
    )
    service = get_default_budget_service()
    assert isinstance(service._repo, StubRepo)
