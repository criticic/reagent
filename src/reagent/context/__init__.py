"""Context — JSONL-backed conversation history with checkpoints."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import aiofiles

from reagent.llm.message import (
    Message,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolResultPart,
)


logger = logging.getLogger(__name__)


@dataclass
class Context:
    """Conversation context with checkpoint support for D-Mail.

    Messages are stored in a JSONL file. Checkpoints mark restore points
    that the D-Mail system can revert to.
    """

    path: Path
    messages: list[Message] = field(default_factory=list)
    checkpoints: dict[int, int] = field(
        default_factory=dict
    )  # checkpoint_id -> message_index
    token_count: int = 0

    _checkpoint_counter: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    async def append(self, message: Message) -> None:
        """Append a message to context and persist."""
        self.messages.append(message)
        await self._append_jsonl(_message_to_dict(message))

    async def append_system(self, text: str) -> None:
        """Append a system message."""
        await self.append(Message.system(text))

    async def checkpoint(self) -> int:
        """Create a checkpoint (restore point for D-Mail)."""
        cid = self._checkpoint_counter
        self._checkpoint_counter += 1
        self.checkpoints[cid] = len(self.messages)
        await self._append_jsonl({"_type": "checkpoint", "id": cid})
        return cid

    async def revert_to(self, checkpoint_id: int) -> None:
        """Revert context to a previous checkpoint.

        The JSONL file is rotated and replayed up to the checkpoint.
        """
        if checkpoint_id not in self.checkpoints:
            raise ValueError(f"Unknown checkpoint: {checkpoint_id}")

        idx = self.checkpoints[checkpoint_id]
        self.messages = self.messages[:idx]

        # Remove checkpoints after this one
        self.checkpoints = {
            k: v for k, v in self.checkpoints.items() if k <= checkpoint_id
        }

        # Rotate file and rewrite
        if self.path.exists():
            backup = self.path.with_suffix(f".{int(time.time())}.bak")
            self.path.rename(backup)

        await self._rewrite_jsonl()

    def get_messages(self) -> list[Message]:
        """Get all messages for the LLM."""
        return list(self.messages)

    async def grow(self, assistant_msg: Message, tool_results: list[Message]) -> None:
        """Append assistant message and tool results atomically."""
        await self.append(assistant_msg)
        for tr in tool_results:
            await self.append(tr)

    def estimate_tokens(self) -> int:
        """Rough token estimate based on character count.

        ~4 characters per token is a reasonable approximation.
        """
        total_chars = sum(len(json.dumps(_message_to_dict(m))) for m in self.messages)
        return total_chars // 4

    @classmethod
    async def restore(cls, path: Path) -> Context:
        """Restore context from a JSONL file."""
        ctx = cls(path=path)
        if not path.exists():
            return ctx

        async with aiofiles.open(path, "r", encoding="utf-8") as f:
            async for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("Skipping malformed JSONL line in %s", path)
                    continue

                if data.get("_type") == "checkpoint":
                    ctx.checkpoints[data["id"]] = len(ctx.messages)
                    ctx._checkpoint_counter = max(
                        ctx._checkpoint_counter, data["id"] + 1
                    )
                elif data.get("_type") == "usage":
                    ctx.token_count = data.get("token_count", 0)
                elif "role" in data:
                    ctx.messages.append(_dict_to_message(data))

        return ctx

    async def _append_jsonl(self, data: dict) -> None:
        """Append a JSON line to the context file."""
        async with aiofiles.open(self.path, "a", encoding="utf-8") as f:
            await f.write(json.dumps(data, ensure_ascii=False) + "\n")

    async def rewrite(self) -> None:
        """Rewrite the JSONL file from current in-memory state.

        Public interface for ``compact_context()`` and other callers
        that mutate ``self.messages`` in-place and need to persist.
        """
        await self._rewrite_jsonl()

    async def _rewrite_jsonl(self) -> None:
        """Rewrite the entire JSONL file from current state.

        Also used by ``context.management.compact_context()`` to persist
        compacted context.
        """
        async with aiofiles.open(self.path, "w", encoding="utf-8") as f:
            for msg in self.messages:
                await f.write(
                    json.dumps(_message_to_dict(msg), ensure_ascii=False) + "\n"
                )
            for cid, idx in sorted(self.checkpoints.items()):
                await f.write(json.dumps({"_type": "checkpoint", "id": cid}) + "\n")


def _message_to_dict(msg: Message) -> dict[str, Any]:
    """Serialize a Message to a dict for JSONL storage."""
    result: dict[str, Any] = {"role": msg.role}

    text_parts = [p for p in msg.parts if isinstance(p, TextPart)]
    tc_parts = [p for p in msg.parts if isinstance(p, ToolCallPart)]
    tr_parts = [p for p in msg.parts if isinstance(p, ToolResultPart)]
    thinking_parts = [p for p in msg.parts if isinstance(p, ThinkingPart)]

    if text_parts:
        result["content"] = "".join(p.text for p in text_parts)

    if tc_parts:
        result["tool_calls"] = [
            {"id": p.id, "name": p.name, "arguments": p.arguments} for p in tc_parts
        ]

    if tr_parts:
        p = tr_parts[0]
        result["tool_call_id"] = p.tool_call_id
        result["content"] = p.content
        result["is_error"] = p.is_error

    if thinking_parts:
        result["thinking"] = "".join(p.thinking for p in thinking_parts)
        # Preserve signature for Anthropic round-tripping
        sig = next((p.signature for p in thinking_parts if p.signature), "")
        if sig:
            result["thinking_signature"] = sig

    return result


def _dict_to_message(data: dict[str, Any]) -> Message:
    """Deserialize a dict from JSONL to a Message."""
    role = data["role"]
    parts = []

    if role == "tool":
        parts.append(
            ToolResultPart(
                tool_call_id=data.get("tool_call_id", ""),
                content=data.get("content", ""),
                is_error=data.get("is_error", False),
            )
        )
    else:
        # Thinking parts come first (matches Anthropic message ordering)
        if data.get("thinking"):
            parts.append(
                ThinkingPart(
                    thinking=data["thinking"],
                    signature=data.get("thinking_signature", ""),
                )
            )
        if data.get("content"):
            parts.append(TextPart(text=data["content"]))
        for tc in data.get("tool_calls", []):
            parts.append(
                ToolCallPart(
                    id=tc.get("id", ""),
                    name=tc.get("name", ""),
                    arguments=tc.get("arguments", ""),
                )
            )

    return Message(role=role, parts=parts)
