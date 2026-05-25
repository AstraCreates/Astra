from backend.core.factory import get_orchestrator


def test_all_six_agents_registered():
    orch = get_orchestrator()
    expected = {"legal", "research", "web", "marketing", "technical", "ops"}
    assert set(orch.specialists.keys()) == expected


def test_each_specialist_has_correct_name():
    orch = get_orchestrator()
    for key, agent in orch.specialists.items():
        assert agent.name == key
