"""Real production bug: find_leads/search_examples/github_create_repo have no
resilient-arg wrapper (unlike the research tools) and raised raw TypeError/
AttributeError on malformed model calls, which the model can only blindly
retry on since a Python exception carries no corrective signal — a rapid
failed-retry storm burning real CPU across many concurrent agents."""

from backend.tools.lead_finder import find_leads
from backend.tools.examples_library import search_examples
from backend.tools.github_scaffold import github_create_repo


def test_find_leads_returns_guidance_instead_of_crashing_on_missing_industry():
    result = find_leads()
    assert result == {"error": "find_leads requires 'industry' (e.g. find_leads(industry='restaurant', job_title='owner', max_results=10))"}


def test_search_examples_returns_guidance_when_nothing_usable_passed():
    result = search_examples()
    assert result["error"] == "search_examples requires 'query' (e.g. search_examples('nextauth google oauth'))"
    assert result["examples"] == []


def test_search_examples_falls_back_to_category_or_agent_role(monkeypatch):
    import backend.tools.examples_library as mod
    monkeypatch.setattr(mod, "_load_examples", lambda: [
        {"path": "auth/nextauth.md", "category": "auth", "title": "NextAuth", "tags": ["auth"], "applies_to": [], "content": "..."},
    ])
    result = search_examples(category="auth")
    assert "error" not in result


def test_github_create_repo_coerces_non_dict_stack_instead_of_crashing(monkeypatch):
    """Real bug: stack=[...] (a list, not a dict) reached _generate_scaffold's
    stack.get(...) calls unguarded — AttributeError: 'list' object has no
    attribute 'get'. Only isinstance(stack, str) was ever special-cased."""
    from backend.config import settings
    monkeypatch.setattr(settings, "github_token", None, raising=False)

    result = github_create_repo(repo_name="test-repo", stack=["Python", "FastAPI"])

    assert "error" not in result
    assert result["created"] is False
    assert "scaffold" in result
