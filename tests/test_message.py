"""Tests for reagent.llm.message."""

from __future__ import annotations

from reagent.llm.message import (
    Message,
    TextPart,
    ThinkingPart,
    TokenUsage,
    ToolCall,
    ToolCallPart,
    ToolResultPart,
)


# ---------------------------------------------------------------------------
# Part dataclasses
# ---------------------------------------------------------------------------


class TestTextPart:
    def test_defaults(self) -> None:
        p = TextPart()
        assert p.type == "text"
        assert p.text == ""

    def test_custom(self) -> None:
        p = TextPart(text="hello")
        assert p.text == "hello"


class TestToolCallPart:
    def test_defaults(self) -> None:
        p = ToolCallPart()
        assert p.type == "tool_call"
        assert p.id == ""
        assert p.name == ""
        assert p.arguments == ""

    def test_custom(self) -> None:
        p = ToolCallPart(id="tc1", name="shell", arguments='{"cmd": "ls"}')
        assert p.name == "shell"


class TestToolResultPart:
    def test_defaults(self) -> None:
        p = ToolResultPart()
        assert p.type == "tool_result"
        assert p.is_error is False
        assert p.content == ""

    def test_error(self) -> None:
        p = ToolResultPart(tool_call_id="tc1", content="fail", is_error=True)
        assert p.is_error is True


class TestThinkingPart:
    def test_defaults(self) -> None:
        p = ThinkingPart()
        assert p.type == "thinking"
        assert p.thinking == ""
        assert p.signature == ""

    def test_custom(self) -> None:
        p = ThinkingPart(thinking="reasoning", signature="sig")
        assert p.thinking == "reasoning"
        assert p.signature == "sig"


class TestToolCall:
    def test_fields(self) -> None:
        tc = ToolCall(id="tc1", name="shell", arguments={"command": "ls"})
        assert tc.id == "tc1"
        assert tc.arguments == {"command": "ls"}

    def test_arguments_is_dict(self) -> None:
        """ToolCall.arguments is a dict (already parsed), not a JSON string."""
        tc = ToolCall(id="tc1", name="test", arguments={"key": "value"})
        assert isinstance(tc.arguments, dict)


class TestTokenUsage:
    def test_defaults(self) -> None:
        u = TokenUsage()
        assert u.input_tokens == 0
        assert u.output_tokens == 0
        assert u.total_tokens == 0


# ---------------------------------------------------------------------------
# Message — constructors
# ---------------------------------------------------------------------------


class TestMessageConstructors:
    def test_system(self) -> None:
        m = Message.system("prompt")
        assert m.role == "system"
        assert m.text == "prompt"
        assert len(m.parts) == 1
        assert isinstance(m.parts[0], TextPart)

    def test_user(self) -> None:
        m = Message.user("hello")
        assert m.role == "user"
        assert m.text == "hello"

    def test_assistant_text_only(self) -> None:
        m = Message.assistant("response")
        assert m.role == "assistant"
        assert m.text == "response"

    def test_assistant_empty(self) -> None:
        m = Message.assistant()
        assert m.role == "assistant"
        # Empty text should either produce no parts or an empty text part
        assert m.text == ""

    def test_assistant_with_tool_calls(self) -> None:
        tc = ToolCallPart(id="tc1", name="shell", arguments='{"cmd": "ls"}')
        m = Message.assistant(text="calling", tool_calls=[tc])
        assert m.text == "calling"
        calls = [p for p in m.parts if isinstance(p, ToolCallPart)]
        assert len(calls) == 1
        assert calls[0].name == "shell"

    def test_assistant_tool_calls_no_text(self) -> None:
        tc = ToolCallPart(id="tc1", name="think", arguments="{}")
        m = Message.assistant(tool_calls=[tc])
        calls = [p for p in m.parts if isinstance(p, ToolCallPart)]
        assert len(calls) == 1

    def test_tool_result(self) -> None:
        m = Message.tool_result("tc1", "output", is_error=False)
        assert m.role == "tool"
        parts = [p for p in m.parts if isinstance(p, ToolResultPart)]
        assert len(parts) == 1
        assert parts[0].content == "output"
        assert parts[0].is_error is False

    def test_tool_result_error(self) -> None:
        m = Message.tool_result("tc1", "error msg", is_error=True)
        parts = [p for p in m.parts if isinstance(p, ToolResultPart)]
        assert parts[0].is_error is True


# ---------------------------------------------------------------------------
# Message — properties
# ---------------------------------------------------------------------------


class TestMessageProperties:
    def test_text_concatenation(self) -> None:
        m = Message(
            role="assistant",
            parts=[TextPart(text="hello "), TextPart(text="world")],
        )
        assert m.text == "hello world"

    def test_text_skips_non_text_parts(self) -> None:
        m = Message(
            role="assistant",
            parts=[
                TextPart(text="intro"),
                ToolCallPart(id="tc1", name="shell", arguments="{}"),
            ],
        )
        assert m.text == "intro"

    def test_thinking(self) -> None:
        m = Message(
            role="assistant",
            parts=[
                ThinkingPart(thinking="step 1"),
                ThinkingPart(thinking="step 2"),
                TextPart(text="answer"),
            ],
        )
        assert m.thinking == "step 1step 2"

    def test_thinking_blocks(self) -> None:
        m = Message(
            role="assistant",
            parts=[
                ThinkingPart(thinking="reasoning", signature="sig1"),
                TextPart(text="answer"),
            ],
        )
        blocks = m.thinking_blocks
        assert len(blocks) == 1
        assert blocks[0]["thinking"] == "reasoning"
        assert blocks[0]["signature"] == "sig1"

    def test_thinking_blocks_empty(self) -> None:
        m = Message.assistant("no thinking here")
        assert m.thinking_blocks == []

    def test_tool_calls(self) -> None:
        m = Message(
            role="assistant",
            parts=[
                ToolCallPart(id="tc1", name="shell", arguments='{"command": "ls"}'),
                ToolCallPart(id="tc2", name="read_file", arguments='{"path": "/tmp"}'),
            ],
        )
        calls = m.tool_calls
        assert len(calls) == 2
        assert calls[0].name == "shell"
        assert calls[0].arguments == {"command": "ls"}
        assert calls[1].name == "read_file"

    def test_tool_calls_invalid_json(self) -> None:
        """Invalid JSON in arguments should default to {}."""
        m = Message(
            role="assistant",
            parts=[ToolCallPart(id="tc1", name="test", arguments="not json")],
        )
        calls = m.tool_calls
        assert len(calls) == 1
        assert calls[0].arguments == {}

    def test_tool_calls_empty(self) -> None:
        m = Message.user("no tools")
        assert m.tool_calls == []


# ---------------------------------------------------------------------------
# Message — to_openai_dict
# ---------------------------------------------------------------------------


class TestMessageToOpenAI:
    def test_user(self) -> None:
        m = Message.user("hello")
        d = m.to_openai_dict()
        assert d["role"] == "user"
        assert d["content"] == "hello"

    def test_system(self) -> None:
        m = Message.system("prompt")
        d = m.to_openai_dict()
        assert d["role"] == "system"
        assert d["content"] == "prompt"

    def test_assistant_text(self) -> None:
        m = Message.assistant("response")
        d = m.to_openai_dict()
        assert d["role"] == "assistant"
        assert d["content"] == "response"

    def test_assistant_with_tool_calls(self) -> None:
        tc = ToolCallPart(id="tc1", name="shell", arguments='{"cmd": "ls"}')
        m = Message.assistant(text="calling", tool_calls=[tc])
        d = m.to_openai_dict()
        assert d["role"] == "assistant"
        assert len(d["tool_calls"]) == 1
        assert d["tool_calls"][0]["id"] == "tc1"
        assert d["tool_calls"][0]["type"] == "function"
        assert d["tool_calls"][0]["function"]["name"] == "shell"
        assert d["tool_calls"][0]["function"]["arguments"] == '{"cmd": "ls"}'

    def test_assistant_no_text_with_tool_calls(self) -> None:
        tc = ToolCallPart(id="tc1", name="think", arguments="{}")
        m = Message.assistant(tool_calls=[tc])
        d = m.to_openai_dict()
        # content should be None when there's no text (OpenAI format)
        assert d.get("content") is None or d.get("content") == ""

    def test_tool_result(self) -> None:
        m = Message.tool_result("tc1", "output")
        d = m.to_openai_dict()
        assert d["role"] == "tool"
        assert d["tool_call_id"] == "tc1"
        assert d["content"] == "output"

    def test_assistant_with_thinking(self) -> None:
        m = Message(
            role="assistant",
            parts=[
                ThinkingPart(thinking="reasoning", signature="sig1"),
                TextPart(text="answer"),
            ],
        )
        d = m.to_openai_dict()
        assert d["role"] == "assistant"
        assert d["content"] == "answer"
        # Should include thinking blocks for providers that support them
        if "thinking_blocks" in d:
            assert len(d["thinking_blocks"]) == 1
