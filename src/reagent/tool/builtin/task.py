"""Task tool — dispatch work to sub-agents."""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from reagent.tool.base import BaseTool, ToolOk, ToolError, ToolResult


class TaskParams(BaseModel):
    description: str = Field(description="Short description of the task (3-5 words).")
    prompt: str = Field(description="Detailed task instructions for the sub-agent.")
    agent: str = Field(
        default="static",
        description="Which specialist agent to dispatch to (triage, static, dynamic, etc.).",
    )


class TaskTool(BaseTool[TaskParams]):
    """Dispatch a task to a specialist sub-agent.

    The orchestrator uses this to delegate work to specialists.
    Each sub-agent runs in its own context and returns results.
    """

    name: ClassVar[str] = "task"
    description: ClassVar[str] = (
        "Dispatch a task to a specialist sub-agent. Use this to delegate "
        "analysis work to the appropriate specialist (triage, static, dynamic). "
        "The sub-agent runs autonomously and returns its findings."
    )
    param_model: ClassVar[type[BaseModel]] = TaskParams

    def __init__(self, dispatch_fn: Any = None) -> None:
        self._dispatch_fn = dispatch_fn

    async def execute(self, params: TaskParams) -> ToolResult:
        if self._dispatch_fn is None:
            return ToolError(output="Sub-agent dispatch not configured.")

        try:
            result = await self._dispatch_fn(
                agent=params.agent,
                prompt=params.prompt,
                description=params.description,
            )
            return ToolOk(output=str(result), brief=f"Task: {params.description}")
        except Exception as e:
            return ToolError(output=f"Sub-agent failed: {e}")
