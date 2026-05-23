from backend.config import settings

def test_settings_has_required_fields():
    assert hasattr(settings, "supabase_url")
    assert hasattr(settings, "redis_url")
    assert hasattr(settings, "gemini_api_key")
    assert hasattr(settings, "agent_model_base_url")
    assert hasattr(settings, "vertex_project")
