"""Tests for reagent.llm.streaming (StepResult, GenerateResult)."""

from __future__ import annotations

from reagent.llm.message import Message, TextPart, ToolCallPart
from reagent.llm.streaming import GenerateResult, StepResult


# ---------------------------------------------------------------------------
# GenerateResult
# ---------------------------------------------------------------------------


class TestGenerateResult:
    def test_tool_calls_empty(self) -> None:
        msg = Message.assistant("just text")
        result = GenerateResult(message=msg)
        assert result.tool_calls == []
        assert result.has_tool_calls is False

    def test_tool_calls_present(self) -> None:
        tc = ToolCallPart(id="tc1", name="shell", arguments='{"cmd":"ls"}')
        msg = Message(role="assistant", parts=[TextPart(text="ok"), tc])
        result = GenerateResult(message=msg)
        assert result.has_tool_calls is True
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "shell"

    def test_finish_reason_default(self) -> None:
        result = GenerateResult(message=Message.assistant("hi"))
        assert result.finish_reason is None


# ---------------------------------------------------------------------------
# StepResult.stop_reason
# ---------------------------------------------------------------------------


class TestStepResultStopReason:
    def test_end_turn(self) -> None:
        """No tool calls and non-length finish_reason => end_turn."""
        msg = Message.assistant("final answer")
        result = StepResult(message=msg, finish_reason="stop")
        assert result.stop_reason == "end_turn"

    def test_end_turn_none_finish(self) -> None:
        """No tool calls and finish_reason=None => end_turn."""
        msg = Message.assistant("answer")
        result = StepResult(message=msg, finish_reason=None)
        assert result.stop_reason == "end_turn"

    def test_tool_calls(self) -> None:
        """Has tool calls => tool_calls, regardless of finish_reason."""
        tc = ToolCallPart(id="tc1", name="read_file", arguments='{"path":"x"}')
        msg = Message(role="assistant", parts=[tc])
        result = StepResult(message=msg, finish_reason="tool_calls")
        assert result.stop_reason == "tool_calls"

    def test_tool_calls_overrides_length(self) -> None:
        """tool_calls check happens before length check."""
        tc = ToolCallPart(id="tc1", name="shell", arguments="{}")
        msg = Message(role="assistant", parts=[tc])
        result = StepResult(message=msg, finish_reason="length")
        assert result.stop_reason == "tool_calls"

    def test_context_overflow(self) -> None:
        """finish_reason='length' with no tool calls => context_overflow."""
        msg = Message.assistant("truncated response")
        result = StepResult(message=msg, finish_reason="length")
        assert result.stop_reason == "context_overflow"

    def test_context_overflow_empty_message(self) -> None:
        """Even an empty message with finish_reason='length' is context_overflow."""
        msg = Message(role="assistant", parts=[])
        result = StepResult(message=msg, finish_reason="length")
        assert result.stop_reason == "context_overflow"
