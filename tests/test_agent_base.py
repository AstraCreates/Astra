import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from backend.agents.base import AstraAgent, AgentTask, AgentResult


@pytest.fixture
def agent(mocker):
    mocker.patch("backend.agents.base.vector_store")
    mocker.patch("backend.agents.base.openai")
    return AstraAgent(
        agent_id="legal",
        system_prompt="You are the Legal Agent.",
        model="gemma4",
        tools=["doc_generator"],
        memory_namespaces=["legal", "shared"],
    )


def test_agent_builds_prompt_includes_instruction(agent):
    task = AgentTask(
        task_id="t1", goal_id="g1", founder_id="f1",
        agent="legal", instruction="Draft an NDA",
        context_bundle={"company_name": "AcmeCo"},
        constraints={}, tools_available=["doc_generator"],
    )
    prompt = agent._build_prompt(task, memory_docs=[])
    assert "Draft an NDA" in prompt
    assert "AcmeCo" in prompt


@pytest.mark.asyncio
async def test_agent_run_done_returns_agent_result(mocker):
    mocker.patch("backend.agents.base.vector_store.retrieve", new=AsyncMock(return_value=[]))

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices[0].message.content = json.dumps({
        "status": "done",
        "output": {"document": "Agreement text here"},
        "confidence": 0.95,
        "reasoning": "Generated founder agreement",
    })
    mock_client.chat.completions.create.return_value = mock_response
    mocker.patch("backend.agents.base.openai.OpenAI", return_value=mock_client)

    agent = AstraAgent(
        agent_id="legal",
        system_prompt="You are the Legal Agent.",
        model="gemma4",
        tools=["doc_generator"],
        memory_namespaces=["legal", "shared"],
    )

    task = AgentTask(
        task_id="t1", goal_id="g1", founder_id="f1",
        agent="legal", instruction="Draft NDA",
        context_bundle={}, constraints={}, tools_available=[],
    )
    result = await agent.run(task)
    assert isinstance(result, AgentResult)
    assert result.status == "done"
    assert "document" in result.output


@pytest.mark.asyncio
async def test_agent_run_approval_required_returns_approval_result(mocker):
    mocker.patch("backend.agents.base.vector_store.retrieve", new=AsyncMock(return_value=[]))

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices[0].message.content = json.dumps({
        "status": "approval_required",
        "output": {},
        "confidence": 0.99,
        "reasoning": "About to charge $500",
        "approval_action": "File Delaware LLC — $500 charge",
        "approval_consequence": "Irreversible. Company legally formed.",
    })
    mock_client.chat.completions.create.return_value = mock_response
    mocker.patch("backend.agents.base.openai.OpenAI", return_value=mock_client)

    agent = AstraAgent(
        agent_id="legal", system_prompt="Legal.", model="gemma4",
        tools=[], memory_namespaces=["legal"],
    )
    task = AgentTask(
        task_id="t2", goal_id="g1", founder_id="f1",
        agent="legal", instruction="File LLC",
        context_bundle={}, constraints={}, tools_available=[],
    )
    result = await agent.run(task)
    assert result.status == "approval_required"
    assert result.approval_action is not None
