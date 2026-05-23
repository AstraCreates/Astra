import pytest
from unittest.mock import MagicMock, patch
from backend.orchestrator.goal_parser import parse_goal


@pytest.mark.asyncio
async def test_parse_goal_returns_structured_output(mocker):
    mock_model = MagicMock()
    mock_response = MagicMock()
    mock_response.text = '{"instruction": "launch a SaaS for restaurants", "entities": {"company_name": "RestaurantIQ", "icp": "restaurant owners"}, "priority_agents": ["legal", "research"]}'
    mock_model.generate_content.return_value = mock_response
    mocker.patch("backend.orchestrator.goal_parser.genai.GenerativeModel", return_value=mock_model)

    result = await parse_goal(
        goal_id="g1",
        founder_id="f1",
        raw_instruction="I want to build a restaurant inventory SaaS called RestaurantIQ",
    )
    assert result["instruction"] == "launch a SaaS for restaurants"
    assert "entities" in result
    assert "priority_agents" in result


@pytest.mark.asyncio
async def test_parse_goal_falls_back_on_invalid_json(mocker):
    mock_model = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "not valid json at all"
    mock_model.generate_content.return_value = mock_response
    mocker.patch("backend.orchestrator.goal_parser.genai.GenerativeModel", return_value=mock_model)

    result = await parse_goal(goal_id="g1", founder_id="f1", raw_instruction="Build something")
    assert result["instruction"] == "Build something"
    assert result["entities"] == {}
