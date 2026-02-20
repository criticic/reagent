"""Tests for reagent.context (Context, serialization helpers)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reagent.context import Context, _dict_to_message, _message_to_dict
from reagent.llm.message import (
    Message,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolResultPart,
)


# ---------------------------------------------------------------------------
# _message_to_dict / _dict_to_message round-trip
# ---------------------------------------------------------------------------


class TestMessageSerialization:
    def test_text_message_round_trip(self) -> None:
        msg = Message.user("hello world")
        d = _message_to_dict(msg)
        assert d["role"] == "user"
        assert d["content"] == "hello world"
        msg2 = _dict_to_message(d)
        assert msg2.role == "user"
        assert msg2.text == "hello world"

    def test_system_message_round_trip(self) -> None:
        msg = Message.system("you are a bot")
        d = _message_to_dict(msg)
        msg2 = _dict_to_message(d)
        assert msg2.role == "system"
        assert msg2.text == "you are a bot"

    def test_assistant_with_tool_calls(self) -> None:
        tc = ToolCallPart(id="tc1", name="shell", arguments='{"command": "ls"}')
        msg = Message.assistant(text="Let me check", tool_calls=[tc])
        d = _message_to_dict(msg)
        assert d["role"] == "assistant"
        assert d["content"] == "Let me check"
        assert len(d["tool_calls"]) == 1
        assert d["tool_calls"][0]["name"] == "shell"

        msg2 = _dict_to_message(d)
        assert msg2.role == "assistant"
        assert msg2.text == "Let me check"
        calls = [p for p in msg2.parts if isinstance(p, ToolCallPart)]
        assert len(calls) == 1
        assert calls[0].name == "shell"

    def test_tool_result_round_trip(self) -> None:
        msg = Message.tool_result("tc1", "file.txt\ndata.bin", is_error=False)
        d = _message_to_dict(msg)
        assert d["role"] == "tool"
        assert d["tool_call_id"] == "tc1"
        assert d["content"] == "file.txt\ndata.bin"
        assert d["is_error"] is False

        msg2 = _dict_to_message(d)
        assert msg2.role == "tool"
        parts = [p for p in msg2.parts if isinstance(p, ToolResultPart)]
        assert len(parts) == 1
        assert parts[0].tool_call_id == "tc1"
        assert parts[0].is_error is False

    def test_tool_result_error(self) -> None:
        msg = Message.tool_result("tc2", "command failed", is_error=True)
        d = _message_to_dict(msg)
        assert d["is_error"] is True
        msg2 = _dict_to_message(d)
        parts = [p for p in msg2.parts if isinstance(p, ToolResultPart)]
        assert parts[0].is_error is True

    def test_thinking_round_trip(self) -> None:
        msg = Message(
            role="assistant",
            parts=[
                ThinkingPart(thinking="Let me reason about this", signature="sig123"),
                TextPart(text="Here's my answer"),
            ],
        )
        d = _message_to_dict(msg)
        assert d["thinking"] == "Let me reason about this"
        assert d["thinking_signature"] == "sig123"
        assert d["content"] == "Here's my answer"

        msg2 = _dict_to_message(d)
        assert msg2.thinking == "Let me reason about this"
        assert msg2.text == "Here's my answer"
        thinking_parts = [p for p in msg2.parts if isinstance(p, ThinkingPart)]
        assert thinking_parts[0].signature == "sig123"


# ---------------------------------------------------------------------------
# Context — basic operations
# ---------------------------------------------------------------------------


class TestContext:
    async def test_init_creates_parent_dir(self, tmp_path: Path) -> None:
        ctx_path = tmp_path / "sub" / "deep" / "context.jsonl"
        ctx = Context(path=ctx_path)
        assert ctx_path.parent.exists()
        assert ctx.messages == []

    async def test_append(self, tmp_path: Path) -> None:
        ctx = Context(path=tmp_path / "test.jsonl")
        await ctx.append(Message.user("hello"))
        assert len(ctx.messages) == 1
        assert ctx.messages[0].text == "hello"

    async def test_append_system(self, tmp_path: Path) -> None:
        ctx = Context(path=tmp_path / "test.jsonl")
        await ctx.append_system("system msg")
        assert len(ctx.messages) == 1
        assert ctx.messages[0].role == "system"
        assert ctx.messages[0].text == "system msg"

    async def test_get_messages_returns_copy(self, tmp_path: Path) -> None:
        ctx = Context(path=tmp_path / "test.jsonl")
        await ctx.append(Message.user("hi"))
        msgs = ctx.get_messages()
        msgs.append(Message.user("extra"))
        assert len(ctx.messages) == 1  # Original unaffected

    async def test_grow(self, tmp_path: Path) -> None:
        ctx = Context(path=tmp_path / "test.jsonl")
        assistant = Message.assistant("response")
        tool_results = [Message.tool_result("tc1", "result")]
        await ctx.grow(assistant, tool_results)
        assert len(ctx.messages) == 2
        assert ctx.messages[0].role == "assistant"
        assert ctx.messages[1].role == "tool"

    async def test_estimate_tokens(self, tmp_path: Path) -> None:
        ctx = Context(path=tmp_path / "test.jsonl")
        await ctx.append(Message.user("hello world"))
        tokens = ctx.estimate_tokens()
        assert tokens > 0


# ---------------------------------------------------------------------------
# Context — checkpoint / revert
# ---------------------------------------------------------------------------


class TestContextCheckpoint:
    async def test_checkpoint(self, tmp_path: Path) -> None:
        ctx = Context(path=tmp_path / "test.jsonl")
        await ctx.append(Message.user("msg1"))
        cp_id = await ctx.checkpoint()
        assert cp_id == 0
        assert cp_id in ctx.checkpoints

    async def test_revert_to(self, tmp_path: Path) -> None:
        ctx = Context(path=tmp_path / "test.jsonl")
        await ctx.append(Message.user("msg1"))
        cp_id = await ctx.checkpoint()
        await ctx.append(Message.user("msg2"))
        await ctx.append(Message.user("msg3"))
        assert len(ctx.messages) == 3

        await ctx.revert_to(cp_id)
        assert len(ctx.messages) == 1
        assert ctx.messages[0].text == "msg1"

    async def test_revert_to_invalid(self, tmp_path: Path) -> None:
        ctx = Context(path=tmp_path / "test.jsonl")
        with pytest.raises(ValueError, match="Unknown checkpoint"):
            await ctx.revert_to(999)

    async def test_multiple_checkpoints(self, tmp_path: Path) -> None:
        ctx = Context(path=tmp_path / "test.jsonl")
        await ctx.append(Message.user("msg1"))
        cp1 = await ctx.checkpoint()
        await ctx.append(Message.user("msg2"))
        cp2 = await ctx.checkpoint()
        await ctx.append(Message.user("msg3"))

        await ctx.revert_to(cp2)
        assert len(ctx.messages) == 2

        await ctx.revert_to(cp1)
        assert len(ctx.messages) == 1


# ---------------------------------------------------------------------------
# Context — persistence (JSONL restore)
# ---------------------------------------------------------------------------


class TestContextPersistence:
    async def test_persist_and_restore(self, tmp_path: Path) -> None:
        ctx_path = tmp_path / "test.jsonl"
        ctx = Context(path=ctx_path)
        await ctx.append(Message.user("hello"))
        await ctx.append(Message.system("system note"))
        await ctx.append(
            Message.assistant(
                text="answer",
                tool_calls=[
                    ToolCallPart(id="tc1", name="shell", arguments='{"command":"ls"}')
                ],
            )
        )
        await ctx.append(Message.tool_result("tc1", "file.txt"))

        # Restore from same file
        ctx2 = await Context.restore(ctx_path)
        assert len(ctx2.messages) == 4
        assert ctx2.messages[0].text == "hello"
        assert ctx2.messages[1].role == "system"
        assert ctx2.messages[2].text == "answer"
        assert ctx2.messages[3].role == "tool"

    async def test_restore_with_checkpoints(self, tmp_path: Path) -> None:
        ctx_path = tmp_path / "test.jsonl"
        ctx = Context(path=ctx_path)
        await ctx.append(Message.user("msg1"))
        await ctx.checkpoint()
        await ctx.append(Message.user("msg2"))

        ctx2 = await Context.restore(ctx_path)
        assert len(ctx2.messages) == 2
        assert len(ctx2.checkpoints) == 1

    async def test_restore_malformed_line(self, tmp_path: Path) -> None:
        """Malformed JSONL lines should be skipped with a warning."""
        ctx_path = tmp_path / "test.jsonl"
        # Write a mix of valid and invalid lines
        with open(ctx_path, "w") as f:
            f.write(json.dumps({"role": "user", "content": "valid"}) + "\n")
            f.write("this is not json\n")
            f.write(json.dumps({"role": "system", "content": "also valid"}) + "\n")

        ctx = await Context.restore(ctx_path)
        assert len(ctx.messages) == 2

    async def test_restore_nonexistent_file(self, tmp_path: Path) -> None:
        ctx_path = tmp_path / "nonexistent.jsonl"
        ctx = await Context.restore(ctx_path)
        assert len(ctx.messages) == 0


# ---------------------------------------------------------------------------
# Context — rewrite() public method
# ---------------------------------------------------------------------------


class TestContextRewrite:
    async def test_rewrite_persists_current_state(self, tmp_path: Path) -> None:
        ctx_path = tmp_path / "test.jsonl"
        ctx = Context(path=ctx_path)
        await ctx.append(Message.user("msg1"))
        await ctx.append(Message.user("msg2"))
        await ctx.append(Message.user("msg3"))

        # Mutate in-memory state (simulating compaction)
        ctx.messages = [Message.user("compacted summary")]
        await ctx.rewrite()

        # Restore from file and verify only the compacted message is present
        ctx2 = await Context.restore(ctx_path)
        assert len(ctx2.messages) == 1
        assert ctx2.messages[0].text == "compacted summary"

    async def test_rewrite_preserves_checkpoints(self, tmp_path: Path) -> None:
        ctx_path = tmp_path / "test.jsonl"
        ctx = Context(path=ctx_path)
        await ctx.append(Message.user("msg1"))
        cp_id = await ctx.checkpoint()
        await ctx.append(Message.user("msg2"))

        await ctx.rewrite()

        ctx2 = await Context.restore(ctx_path)
        assert len(ctx2.messages) == 2
        assert cp_id in ctx2.checkpoints

    async def test_rewrite_empty_context(self, tmp_path: Path) -> None:
        ctx_path = tmp_path / "test.jsonl"
        ctx = Context(path=ctx_path)
        await ctx.rewrite()

        ctx2 = await Context.restore(ctx_path)
        assert len(ctx2.messages) == 0
