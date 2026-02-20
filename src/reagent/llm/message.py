"""Message types for the LLM abstraction."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger(__name__)


@dataclass
class TextPart:
    """A text content part."""

    type: Literal["text"] = "text"
    text: str = ""


@dataclass
class ToolCallPart:
    """A tool call content part."""

    type: Literal["tool_call"] = "tool_call"
    id: str = ""
    name: str = ""
    arguments: str = ""  # JSON string


@dataclass
class ToolResultPart:
    """A tool result content part."""

    type: Literal["tool_result"] = "tool_result"
    tool_call_id: str = ""
    content: str = ""
    is_error: bool = False


@dataclass
class ThinkingPart:
    """A thinking/reasoning content part (extended thinking from the model).

    This represents the model's internal reasoning (e.g. Anthropic extended
    thinking, DeepSeek reasoning, etc.).  The ``signature`` field is only
    populated for Anthropic models and is required when sending thinking
    blocks back in multi-turn conversations.
    """

    type: Literal["thinking"] = "thinking"
    thinking: str = ""
    signature: str = ""


ContentPart = TextPart | ToolCallPart | ToolResultPart | ThinkingPart


@dataclass
class ToolCall:
    """A complete tool call extracted from a model response."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class TokenUsage:
    """Token usage stats from an LLM call."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass
class Message:
    """A conversation message with typed content parts."""

    role: Literal["system", "user", "assistant", "tool"]
    parts: list[ContentPart] = field(default_factory=list)

    @property
    def text(self) -> str:
        """Get concatenated text content."""
        return "".join(p.text for p in self.parts if isinstance(p, TextPart))

    @property
    def thinking(self) -> str:
        """Get concatenated thinking/reasoning content."""
        return "".join(p.thinking for p in self.parts if isinstance(p, ThinkingPart))

    @property
    def thinking_blocks(self) -> list[dict[str, str]]:
        """Get thinking blocks in Anthropic's format (for round-tripping)."""
        return [
            {"type": "thinking", "thinking": p.thinking, "signature": p.signature}
            for p in self.parts
            if isinstance(p, ThinkingPart) and p.thinking
        ]

    @property
    def tool_calls(self) -> list[ToolCall]:
        """Get all tool calls in this message."""
        import json

        calls = []
        for p in self.parts:
            if isinstance(p, ToolCallPart):
                try:
                    args = json.loads(p.arguments) if p.arguments else {}
                except json.JSONDecodeError:
                    logger.warning(
                        "Failed to parse tool call arguments for %s: %s",
                        p.name,
                        p.arguments[:200],
                    )
                    args = {}
                calls.append(ToolCall(id=p.id, name=p.name, arguments=args))
        return calls

    # --- Convenience constructors ---

    @classmethod
    def system(cls, text: str) -> Message:
        return cls(role="system", parts=[TextPart(text=text)])

    @classmethod
    def user(cls, text: str) -> Message:
        return cls(role="user", parts=[TextPart(text=text)])

    @classmethod
    def assistant(
        cls, text: str = "", tool_calls: list[ToolCallPart] | None = None
    ) -> Message:
        parts: list[ContentPart] = []
        if text:
            parts.append(TextPart(text=text))
        if tool_calls:
            parts.extend(tool_calls)
        return cls(role="assistant", parts=parts)

    @classmethod
    def tool_result(
        cls, tool_call_id: str, content: str, is_error: bool = False
    ) -> Message:
        return cls(
            role="tool",
            parts=[
                ToolResultPart(
                    tool_call_id=tool_call_id, content=content, is_error=is_error
                )
            ],
        )

    def to_openai_dict(self) -> dict[str, Any]:
        """Convert to OpenAI API format.

        For assistant messages with thinking blocks, we include
        ``thinking_blocks`` and ``reasoning_content`` so that litellm can
        round-trip them to Anthropic (required for multi-turn tool calling
        with extended thinking enabled).
        """
        if self.role == "tool":
            # Tool results
            for p in self.parts:
                if isinstance(p, ToolResultPart):
                    return {
                        "role": "tool",
                        "tool_call_id": p.tool_call_id,
                        "content": p.content,
                    }
            return {"role": "tool", "content": ""}

        if self.role == "assistant":
            result: dict[str, Any] = {"role": "assistant"}
            text_parts = [p for p in self.parts if isinstance(p, TextPart)]
            tc_parts = [p for p in self.parts if isinstance(p, ToolCallPart)]
            thinking_parts = [p for p in self.parts if isinstance(p, ThinkingPart)]

            if text_parts:
                result["content"] = "".join(p.text for p in text_parts)
            else:
                result["content"] = None

            if tc_parts:
                result["tool_calls"] = []
                for p in tc_parts:
                    tc_dict: dict[str, Any] = {
                        "id": p.id,
                        "type": "function",
                        "function": {"name": p.name, "arguments": p.arguments},
                    }
                    result["tool_calls"].append(tc_dict)

            # Include thinking blocks for Anthropic round-tripping
            if thinking_parts:
                blocks = [
                    {
                        "type": "thinking",
                        "thinking": p.thinking,
                        "signature": p.signature,
                    }
                    for p in thinking_parts
                    if p.thinking
                ]
                if blocks:
                    result["thinking_blocks"] = blocks
                    result["reasoning_content"] = "".join(
                        p.thinking for p in thinking_parts
                    )

            return result

        # system or user
        return {"role": self.role, "content": self.text}
