"""Base tool classes with Pydantic parameter validation."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Generic, TypeVar, get_type_hints

from pydantic import BaseModel

from reagent.tool.truncation import truncate_output

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


@dataclass
class ToolResult:
    """Base result from a tool execution."""

    output: str = ""
    brief: str = ""  # Short description for UI display
    is_error: bool = False


@dataclass
class ToolOk(ToolResult):
    """Successful tool result."""

    is_error: bool = False


@dataclass
class ToolError(ToolResult):
    """Failed tool result."""

    is_error: bool = True


@dataclass
class ToolRejected(ToolResult):
    """User rejected the tool call."""

    output: str = "Tool call was rejected by the user."
    is_error: bool = True
    rejected: bool = True


class BaseTool(ABC, Generic[T]):
    """Base class for all tools.

    Tools are pure functions: structured input -> structured output.
    Each tool declares its parameters as a Pydantic model (the type parameter T).

    Usage:
        class MyParams(BaseModel):
            path: str
            offset: int = 0

        class MyTool(BaseTool[MyParams]):
            name = "my_tool"
            description = "Does something useful"
            param_model = MyParams

            async def execute(self, params: MyParams) -> ToolResult:
                return ToolOk(output="done")
    """

    name: ClassVar[str]
    description: ClassVar[str]
    param_model: ClassVar[type[BaseModel]]

    async def __call__(self, arguments: dict[str, Any]) -> tuple[str, bool]:
        """Validate arguments, execute, truncate output.

        Returns:
            (content, is_error) tuple suitable for tool result messages.
        """
        try:
            params = self.param_model.model_validate(arguments)
        except Exception as e:
            return f"Invalid parameters: {e}", True

        try:
            result = await self.execute(params)  # type: ignore[arg-type]
        except Exception as e:
            logger.error("Tool %s execution error: %s", self.name, e, exc_info=True)
            return f"Error executing {self.name}: {e}", True

        # Truncate output
        output = truncate_output(result.output)
        return output, result.is_error

    @abstractmethod
    async def execute(self, params: T) -> ToolResult:
        """Execute the tool with validated parameters."""
        ...

    def to_openai_spec(self) -> dict[str, Any]:
        """Convert to OpenAI function tool specification."""
        schema = self.param_model.model_json_schema()
        # Strip the title and $defs that Pydantic adds — LLMs don't need them
        schema.pop("title", None)
        schema.pop("$defs", None)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": schema,
            },
        }
