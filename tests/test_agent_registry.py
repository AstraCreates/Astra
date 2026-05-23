from backend.orchestrator.loop import AGENTS


def test_all_six_agents_registered():
    expected = {"legal", "research", "web", "marketing", "technical", "ops"}
    assert set(AGENTS.keys()) == expected, f"Missing agents: {expected - set(AGENTS.keys())}"


def test_each_agent_has_correct_agent_id():
    for key, agent in AGENTS.items():
        assert agent.agent_id == key, f"AGENTS['{key}'].agent_id == '{agent.agent_id}'"
