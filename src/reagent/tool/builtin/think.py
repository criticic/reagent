"""Think tool — scratchpad for reasoning without acting."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from reagent.tool.base import BaseTool, ToolOk, ToolResult


class ThinkParams(BaseModel):
    thought: str = Field(
        description=(
            "Your internal reasoning. Use this to plan, analyze, form hypotheses, "
            "or work through complex problems before taking action."
        )
    )


class ThinkTool(BaseTool[ThinkParams]):
    """Scratchpad for internal reasoning.

    Use this tool to think through problems, plan next steps,
    form hypotheses about binary behavior, or reason about
    complex analysis before taking action. The content is
    recorded in context but no side effects occur.
    """

    name: ClassVar[str] = "think"
    description: ClassVar[str] = (
        "Use this tool to think through problems and plan your approach. "
        "No side effects — just records your reasoning in context. "
        "Use before complex analysis to plan, or to form/evaluate hypotheses."
    )
    param_model: ClassVar[type[BaseModel]] = ThinkParams

    async def execute(self, params: ThinkParams) -> ToolResult:
        return ToolOk(output="Thought recorded.", brief="Thinking...")
