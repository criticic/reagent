"""Tool registry — discover, register, and dispatch tools."""

from __future__ import annotations

import logging
from typing import Any

from reagent.llm.message import ToolCall
from reagent.tool.base import BaseTool

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Registry of available tools.

    Manages tool registration, lookup, and dispatch. Tools are registered
    by name and can be filtered per-agent.
    """

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance."""
        if tool.name in self._tools:
            logger.warning("Tool %s already registered, overwriting", tool.name)
        self._tools[tool.name] = tool

    def register_many(self, tools: list[BaseTool]) -> None:
        """Register multiple tools."""
        for tool in tools:
            self.register(tool)

    def get(self, name: str) -> BaseTool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def get_specs(self, names: list[str] | None = None) -> list[dict[str, Any]]:
        """Get OpenAI tool specs, optionally filtered by name.

        Args:
            names: If provided, only return specs for these tools.
                   If None, return all.
        """
        tools = self._tools.values()
        if names is not None:
            tools = [t for t in tools if t.name in names]
        return [t.to_openai_spec() for t in tools]

    def names(self) -> list[str]:
        """Get all registered tool names."""
        return list(self._tools.keys())

    def subset(self, names: list[str]) -> ToolRegistry:
        """Create a new registry with only the specified tools."""
        reg = ToolRegistry()
        for name in names:
            tool = self._tools.get(name)
            if tool:
                reg.register(tool)
            else:
                logger.warning("Tool %s not found in registry", name)
        return reg

    async def dispatch(self, tool_call: ToolCall) -> tuple[str, bool]:
        """Dispatch a tool call to the appropriate tool.

        Args:
            tool_call: The tool call from the LLM.

        Returns:
            (content, is_error) tuple.
        """
        tool = self._tools.get(tool_call.name)
        if tool is None:
            return (
                f"Unknown tool: {tool_call.name}. Available tools: {', '.join(self.names())}",
                True,
            )

        return await tool(tool_call.arguments)

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
