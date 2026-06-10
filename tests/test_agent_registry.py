from backend.core.factory import get_orchestrator


def test_core_agents_and_expanded_catalog_registered():
    orch = get_orchestrator()
    expected = {"legal", "research", "web", "marketing", "technical", "ops"}
    assert expected <= set(orch.specialists.keys())
    assert len(orch.specialists) >= 25


def test_each_specialist_has_correct_name():
    orch = get_orchestrator()
    for key, agent in orch.specialists.items():
        assert agent.name == key
