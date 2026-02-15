"""Agent registry — discover and manage agents."""

from __future__ import annotations

import logging
from typing import Any

from reagent.agent.agent import Agent, AgentConfig, discover_agents

logger = logging.getLogger(__name__)


class AgentRegistry:
    """Registry of available agents.

    Agents can be registered programmatically or discovered from
    markdown files in agent directories.
    """

    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}

    def register(self, agent: Agent) -> None:
        """Register an agent."""
        self._agents[agent.name] = agent

    def get(self, name: str) -> Agent | None:
        """Get an agent by name."""
        return self._agents.get(name)

    def names(self) -> list[str]:
        """Get all registered agent names."""
        return list(self._agents.keys())

    def discover(self, search_dirs: list[str]) -> None:
        """Discover and register agents from markdown files."""
        for agent in discover_agents(search_dirs):
            self.register(agent)
            logger.info("Discovered agent: %s", agent.name)

    def get_primary_agents(self) -> list[Agent]:
        """Get all agents with mode='primary'."""
        return [a for a in self._agents.values() if a.config.mode == "primary"]

    def get_subagents(self) -> list[Agent]:
        """Get all agents with mode='subagent'."""
        return [a for a in self._agents.values() if a.config.mode == "subagent"]
