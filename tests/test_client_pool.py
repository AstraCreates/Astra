import sys
import types
import unittest
from unittest.mock import MagicMock

sys.modules.setdefault("openai", types.SimpleNamespace(OpenAI=object))

from backend.core.agent import Agent


class AgentClientPoolTest(unittest.TestCase):
    def test_agent_get_llm_uses_pooled_openrouter_client_with_rotated_keys(self):
        from unittest.mock import patch

        agent = Agent(
            name="research",
            role="research",
            tools={},
            model_base_url="https://openrouter.ai/api/v1",
            model_api_key="fallback-key",
        )

        pooled_client_one = MagicMock(name="pooled_client_one")
        pooled_client_two = MagicMock(name="pooled_client_two")
        pooled_getter = MagicMock(side_effect=[pooled_client_one, pooled_client_two, pooled_client_one])
        rotated_keys = iter(["rotated-key-1", "rotated-key-2", "rotated-key-1"])

        with patch("backend.core.llm_client.get_or_client", pooled_getter), patch(
            "backend.core.key_rotator.get_openrouter_key", side_effect=lambda: next(rotated_keys)
        ):
            self.assertIs(agent._get_llm(), pooled_client_one)
            self.assertIs(agent._get_llm(), pooled_client_two)
            agent._llm = None
            self.assertIs(agent._get_llm(), pooled_client_one)

        self.assertEqual(
            pooled_getter.call_args_list,
            [
                unittest.mock.call(
                    base_url=agent._model_base_url,
                    api_key="rotated-key-1",
                    timeout=None,
                ),
                unittest.mock.call(
                    base_url=agent._model_base_url,
                    api_key="rotated-key-2",
                    timeout=None,
                ),
                unittest.mock.call(
                    base_url=agent._model_base_url,
                    api_key="rotated-key-1",
                    timeout=None,
                ),
            ],
        )
