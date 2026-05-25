"""
P2P message bus. Agents register and route messages to each other.
"""
import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.core.agent import Agent, Message

logger = logging.getLogger(__name__)


class AgentBus:
    def __init__(self):
        self._agents: dict[str, "Agent"] = {}

    def register(self, agent: "Agent") -> None:
        self._agents[agent.name] = agent

    async def route(self, msg: "Message") -> None:
        target = self._agents.get(msg.recipient)
        if target is None:
            logger.warning("Bus: no agent named %s", msg.recipient)
            return
        await target.receive(msg)

    def agents(self) -> list[str]:
        return list(self._agents.keys())
