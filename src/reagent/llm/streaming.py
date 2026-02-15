"""Streaming generation and step primitives."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from reagent.llm.message import (
    ContentPart,
    Message,
    TextPart,
    ThinkingPart,
    ToolCall,
    ToolCallPart,
    ToolResultPart,
    TokenUsage,
)
from reagent.llm.provider import ChatProvider

logger = logging.getLogger(__name__)

# Type alias for tool specs in OpenAI format
ToolSpec = dict[str, Any]

# Callback types
OnPart = Callable[[ContentPart], None] | None
OnToolResult = (
    Callable[[str, str, str, bool], None] | None
)  # (tool_call_id, tool_name, content, is_error)
OnToolCall = (
    Callable[[str, str, str], None] | None
)  # (tool_call_id, tool_name, arguments)
OnThinking = Callable[[str], None] | None  # (thinking_text_chunk)


@dataclass
class GenerateResult:
    """Result of a single LLM generation."""

    message: Message
    usage: TokenUsage = field(default_factory=TokenUsage)
    finish_reason: str | None = None

    @property
    def tool_calls(self) -> list[ToolCall]:
        return self.message.tool_calls

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


@dataclass
class StepResult:
    """Result of a generate + tool dispatch step."""

    message: Message
    tool_results: list[Message] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage)
    finish_reason: str | None = None

    @property
    def stop_reason(self) -> str:
        """Why did this step end?"""
        if self.message.tool_calls:
            return "tool_calls"
        return "end_turn"


async def generate(
    provider: ChatProvider,
    system: str,
    messages: list[Message],
    tools: list[ToolSpec] | None = None,
    on_part: OnPart = None,
    on_tool_call: OnToolCall = None,
    on_thinking: OnThinking = None,
) -> GenerateResult:
    """Stream one LLM response, yielding content parts in real-time.

    This is the fundamental primitive: one API call, one assistant message.
    """
    # Convert messages to OpenAI format
    api_messages = [m.to_openai_dict() for m in messages]

    # Accumulate the assistant message
    text_buffer = ""
    thinking_buffer = ""
    thinking_signature = ""  # last signature seen (Anthropic-only)
    tool_call_buffers: dict[int, dict[str, Any]] = {}  # index -> {id, name, arguments}
    usage = TokenUsage()
    finish_reason = None

    async for chunk in provider.stream(system, api_messages, tools):
        fr = chunk.get("finish_reason")
        if fr:
            finish_reason = fr

        delta = chunk.get("delta", {})

        # Thinking / reasoning content (arrives before text content)
        reasoning = delta.get("reasoning_content")
        if reasoning:
            thinking_buffer += reasoning
            if on_thinking:
                on_thinking(reasoning)
                await asyncio.sleep(0)

        # Thinking blocks (Anthropic format — extract signature)
        tb = delta.get("thinking_blocks")
        if tb:
            for block in tb:
                if isinstance(block, dict):
                    sig = block.get("signature", "")
                    if sig:
                        thinking_signature = sig
                    thinking_text = block.get("thinking", "")
                    if thinking_text and thinking_text not in thinking_buffer:
                        thinking_buffer += thinking_text
                        if on_thinking:
                            on_thinking(thinking_text)
                            await asyncio.sleep(0)

        # Text content
        content = delta.get("content")
        if content:
            text_buffer += content
            if on_part:
                on_part(TextPart(text=content))
                # Yield control so TUI/listeners can process the event.
                # Without this, the tight async-for loop starves other
                # coroutines on the event loop and text only appears at
                # the end.
                await asyncio.sleep(0)

        # Tool calls (streamed incrementally)
        tc_deltas = delta.get("tool_calls", [])
        for tc_delta in tc_deltas:
            idx = tc_delta.get("index", 0)
            if idx not in tool_call_buffers:
                tool_call_buffers[idx] = {
                    "id": "",
                    "name": "",
                    "arguments": "",
                }

            buf = tool_call_buffers[idx]
            if tc_delta.get("id"):
                buf["id"] = tc_delta["id"]
            func = tc_delta.get("function", {})
            if func:
                if func.get("name"):
                    buf["name"] = func["name"]
                if func.get("arguments"):
                    buf["arguments"] += func["arguments"]

        # Usage stats
        if "usage" in chunk:
            u = chunk["usage"]
            usage = TokenUsage(
                input_tokens=u.get("prompt_tokens", 0),
                output_tokens=u.get("completion_tokens", 0),
                total_tokens=u.get("total_tokens", 0),
            )

    # Build the final message
    parts: list[ContentPart] = []

    # Thinking parts come first (matches Anthropic message ordering)
    if thinking_buffer:
        parts.append(
            ThinkingPart(
                thinking=thinking_buffer,
                signature=thinking_signature,
            )
        )

    if text_buffer:
        parts.append(TextPart(text=text_buffer))

    for _idx in sorted(tool_call_buffers.keys()):
        buf = tool_call_buffers[_idx]
        tc_part = ToolCallPart(
            id=buf["id"],
            name=buf["name"],
            arguments=buf["arguments"],
        )
        parts.append(tc_part)
        if on_part:
            on_part(tc_part)
        # Emit real-time tool call notification
        if on_tool_call:
            on_tool_call(buf["id"], buf["name"], buf["arguments"])

    message = Message(role="assistant", parts=parts)
    return GenerateResult(message=message, usage=usage, finish_reason=finish_reason)


async def step(
    provider: ChatProvider,
    system: str,
    messages: list[Message],
    tools: list[ToolSpec] | None = None,
    tool_dispatch: Callable[[ToolCall], Any] | None = None,
    on_part: OnPart = None,
    on_tool_call: OnToolCall = None,
    on_tool_result: OnToolResult = None,
    on_thinking: OnThinking = None,
) -> StepResult:
    """Generate one LLM response and dispatch tool calls.

    This is the main building block for the agent loop:
    1. Call generate() to get the model's response
    2. If the response contains tool calls, dispatch them concurrently
    3. Return the message + tool results

    Args:
        provider: LLM provider to use.
        system: System prompt.
        messages: Conversation history.
        tools: Tool definitions in OpenAI format.
        tool_dispatch: Async callable that takes a ToolCall and returns (content, is_error).
        on_part: Callback for streaming content parts.
        on_tool_call: Callback when a tool call is received (id, name, arguments).
        on_tool_result: Callback for tool results (tool_call_id, tool_name, content, is_error).
        on_thinking: Callback for streaming thinking/reasoning text chunks.
    """
    result = await generate(
        provider, system, messages, tools, on_part, on_tool_call, on_thinking
    )

    tool_results: list[Message] = []

    if result.has_tool_calls and tool_dispatch:
        # Dispatch tool calls concurrently
        async def _run_tool(tc: ToolCall) -> Message:
            try:
                content, is_error = await tool_dispatch(tc)
                content = str(content)
            except Exception as e:
                logger.error("Tool %s failed: %s", tc.name, e)
                content = f"Error: {e}"
                is_error = True

            if on_tool_result:
                on_tool_result(tc.id, tc.name, content, is_error)

            return Message.tool_result(tc.id, content, is_error)

        tasks = [_run_tool(tc) for tc in result.tool_calls]
        tool_results = await asyncio.gather(*tasks)

    return StepResult(
        message=result.message,
        tool_results=tool_results,
        usage=result.usage,
        finish_reason=result.finish_reason,
    )
