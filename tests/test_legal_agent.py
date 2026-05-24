from backend.agents.legal import LEGAL_AGENT


def test_legal_agent_id():
    assert LEGAL_AGENT.agent_id == "legal"


def test_legal_agent_namespaces():
    assert "legal" in LEGAL_AGENT.memory_namespaces
    assert "shared" in LEGAL_AGENT.memory_namespaces


def test_legal_agent_system_prompt_has_disclaimer():
    assert "not legal advice" in LEGAL_AGENT.system_prompt


def test_legal_agent_has_pdf_tool():
    assert "generate_pdf" in LEGAL_AGENT.tools
