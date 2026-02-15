"""D-Mail tool — send knowledge back in time to a past checkpoint.

Inspired by Steins;Gate's D-Mail concept and kimi-cli's implementation.
When an agent realizes it wasted many steps going down a wrong path,
it can send a message to its past self at a checkpoint, causing the
context to revert and the agent to restart with the new knowledge.

This is powerful but expensive — the agent loses all work after the
checkpoint. Use sparingly: only when a fundamental assumption was wrong
and continuing forward would waste more tokens than reverting.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from reagent.agent.loop import BackToTheFuture
from reagent.tool.base import BaseTool, ToolOk, ToolResult


class SendDMailParams(BaseModel):
    checkpoint_id: int = Field(
        description=(
            "The checkpoint ID to send the message to. "
            "Use 0 for the earliest checkpoint, or a specific ID "
            "from context. Lower numbers = further back in time."
        ),
    )
    message: str = Field(
        description=(
            "Knowledge to send to your past self. Be specific and actionable: "
            "include what you tried, why it failed, and what to do instead. "
            "Example: 'The function at 0x401000 is NOT the key validator — "
            "it is a logging wrapper. The real validator is sub_402340, "
            "which uses HMAC-SHA256. Skip directly to analyzing sub_402340.'"
        ),
    )
    reason: str = Field(
        description=(
            "Why you need to send this D-Mail. Justify the cost: "
            "you lose all work after the checkpoint."
        ),
    )


class SendDMailTool(BaseTool[SendDMailParams]):
    """Send a D-Mail — transmit knowledge to your past self.

    This reverts the conversation to an earlier checkpoint and injects
    your message as a system note. All work after that checkpoint is lost.

    Use this when:
    - You discovered a fundamental assumption was wrong many steps ago
    - You went far down a dead-end path and want to redirect
    - You learned something critical that would have changed your approach

    Do NOT use this for minor corrections — just state them normally.
    """

    name: ClassVar[str] = "send_dmail"
    description: ClassVar[str] = (
        "Send a D-Mail to your past self at a checkpoint. "
        "This REVERTS the conversation and injects your knowledge. "
        "All work after the checkpoint is LOST. Use sparingly — only when "
        "a fundamental assumption was wrong and continuing is more expensive "
        "than reverting. The message should contain specific, actionable knowledge."
    )
    param_model: ClassVar[type[BaseModel]] = SendDMailParams

    async def execute(self, params: SendDMailParams) -> ToolResult:
        # Raising BackToTheFuture causes the agent_loop to catch it,
        # revert context to the checkpoint, and inject the message.
        raise BackToTheFuture(
            checkpoint_id=params.checkpoint_id,
            message=params.message,
        )
