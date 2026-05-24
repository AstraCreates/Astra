import pytest
import backend.orchestrator.goal_parser as _gp_module
from unittest.mock import MagicMock, patch


@pytest.fixture(autouse=True)
def reset_client():
    _gp_module._client = None
    yield
    _gp_module._client = None


def _make_openai_mock(content: str):
    mock_client = MagicMock()
    mock_msg = MagicMock()
    mock_msg.content = content
    mock_choice = MagicMock()
    mock_choice.message = mock_msg
    mock_client.chat.completions.create.return_value = MagicMock(choices=[mock_choice])
    return mock_client


@pytest.mark.asyncio
async def test_parse_goal_returns_structured_output():
    from backend.orchestrator.goal_parser import parse_goal

    mock_client = _make_openai_mock(
        '{"instruction": "launch a SaaS for restaurants", '
        '"entities": {"company_name": "RestaurantIQ", "icp": "restaurant owners"}, '
        '"constraints": {}, "priority_agents": ["legal", "research"]}'
    )
    with patch("backend.orchestrator.goal_parser.openai.OpenAI", return_value=mock_client):
        result = await parse_goal(
            goal_id="g1",
            founder_id="f1",
            raw_instruction="I want to build a restaurant inventory SaaS called RestaurantIQ",
        )
    assert result["instruction"] == "launch a SaaS for restaurants"
    assert "entities" in result
    assert "priority_agents" in result


@pytest.mark.asyncio
async def test_parse_goal_falls_back_on_invalid_json():
    from backend.orchestrator.goal_parser import parse_goal

    mock_client = _make_openai_mock("not valid json at all")
    with patch("backend.orchestrator.goal_parser.openai.OpenAI", return_value=mock_client):
        result = await parse_goal(goal_id="g1", founder_id="f1", raw_instruction="Build something")
    assert result["instruction"] == "Build something"
    assert result["entities"] == {}


@pytest.mark.asyncio
async def test_parse_goal_handles_braces_in_instruction():
    from backend.orchestrator.goal_parser import parse_goal

    mock_client = _make_openai_mock(
        '{"instruction": "test", "entities": {}, "constraints": {}, "priority_agents": []}'
    )
    with patch("backend.orchestrator.goal_parser.openai.OpenAI", return_value=mock_client):
        result = await parse_goal(
            goal_id="g1",
            founder_id="f1",
            raw_instruction="Build {something} with {{double}}",
        )
    assert result["instruction"] == "test"
