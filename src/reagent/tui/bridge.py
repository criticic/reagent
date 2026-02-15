"""Bridge between agent_loop callbacks and the Wire event bus.

This module creates callback functions that emit WireEvents onto the Wire,
allowing the TUI to receive agent events through a clean subscription model.

Events are emitted in real-time:
- STEP_BEGIN fires *before* the LLM call (via on_step_begin)
- THINKING fires as each streaming thinking/reasoning chunk arrives (via on_thinking)
- TEXT fires as each streaming text chunk arrives (via on_text)
- TOOL_CALL fires as soon as the LLM finishes generating each tool call (via on_tool_call)
- TOOL_RESULT fires as each tool completes execution (via on_tool_result)
- STATUS (usage) fires after the step completes (via on_step)

For subagent events, each factory accepts an optional ``agent_name`` to tag
the wire event so the UI can attribute it to the right subagent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from reagent.session.wire import EventType, Wire, WireEvent


def make_on_text(wire: Wire) -> Any:
    """Create an on_text callback that emits TEXT events."""

    def on_text(text: str) -> None:
        wire.send(WireEvent(type=EventType.TEXT, data={"text": text}))

    return on_text


def make_on_thinking(wire: Wire) -> Any:
    """Create an on_thinking callback that emits THINKING events."""

    def on_thinking(text: str) -> None:
        wire.send(WireEvent(type=EventType.THINKING, data={"text": text}))

    return on_thinking


def make_on_step_begin(wire: Wire) -> Any:
    """Create an on_step_begin callback that emits STEP_BEGIN before the LLM call."""

    def on_step_begin(step_no: int, agent_name: str) -> None:
        wire.send(
            WireEvent(
                type=EventType.STEP_BEGIN,
                data={"step": step_no, "agent": agent_name},
            )
        )

    return on_step_begin


def make_on_tool_call(wire: Wire) -> Any:
    """Create an on_tool_call callback that emits TOOL_CALL in real-time."""

    def on_tool_call(tc_id: str, name: str, arguments: str) -> None:
        wire.send(
            WireEvent(
                type=EventType.TOOL_CALL,
                data={"name": name, "id": tc_id},
            )
        )

    return on_tool_call


def make_on_tool_result(wire: Wire) -> Any:
    """Create an on_tool_result callback that emits TOOL_RESULT in real-time."""

    def on_tool_result(tc_id: str, name: str, content: str, is_error: bool) -> None:
        wire.send(
            WireEvent(
                type=EventType.TOOL_RESULT,
                data={
                    "name": name,
                    "id": tc_id,
                    "content": content[:500],
                    "is_error": is_error,
                },
            )
        )

    return on_tool_result


def make_on_dmail(wire: Wire) -> Any:
    """Create an on_dmail callback that emits DMAIL events."""

    def on_dmail(checkpoint_id: int, message: str) -> None:
        wire.send(
            WireEvent(
                type=EventType.DMAIL,
                data={"checkpoint_id": checkpoint_id, "message": message},
            )
        )

    return on_dmail


def make_on_step(wire: Wire) -> Any:
    """Create an on_step callback that emits usage/status after the step completes.

    STEP_BEGIN, TOOL_CALL, and TOOL_RESULT are now emitted in real-time via
    their own dedicated callbacks. This callback only handles post-step
    bookkeeping (token usage).
    """

    def on_step(step_no: int, result: Any) -> None:
        # Emit token usage
        if hasattr(result, "usage") and result.usage:
            wire.send(
                WireEvent(
                    type=EventType.STATUS,
                    data={"tokens": result.usage.total_tokens},
                )
            )

    return on_step


def make_on_subagent_text(wire: Wire) -> Any:
    """Create an on_subagent_text callback that emits TEXT events with agent info."""

    def on_subagent_text(agent_name: str, text: str) -> None:
        wire.send(
            WireEvent(
                type=EventType.TEXT,
                data={"text": text, "agent": agent_name},
            )
        )

    return on_subagent_text


# ---------------------------------------------------------------------------
# Subagent callback bundle
# ---------------------------------------------------------------------------


@dataclass
class SubagentCallbacks:
    """All callbacks for a subagent, ready to pass to agent_loop().

    Each callback has the same signature as the orchestrator's callbacks
    (so agent_loop() can use them directly), but the wire events carry an
    ``"agent"`` field so the UI can attribute them to the right subagent.
    """

    on_text: Callable[[str], None]
    on_thinking: Callable[[str], None]
    on_step_begin: Callable[[int, str], None]
    on_tool_call: Callable[[str, str, str], None]
    on_tool_result: Callable[[str, str, str, bool], None]
    on_step: Callable[[int, Any], None]
    on_dmail: Callable[[int, str], None]
    on_begin: Callable[[], None]
    on_end: Callable[[], None]


def make_subagent_callbacks(wire: Wire, agent_name: str) -> SubagentCallbacks:
    """Create a full set of wire-emitting callbacks for a subagent.

    Every event carries ``"agent": agent_name`` so the UI can distinguish
    subagent activity from orchestrator activity.
    """

    def on_text(text: str) -> None:
        wire.send(
            WireEvent(
                type=EventType.TEXT,
                data={"text": text, "agent": agent_name},
            )
        )

    def on_thinking(text: str) -> None:
        wire.send(
            WireEvent(
                type=EventType.THINKING,
                data={"text": text, "agent": agent_name},
            )
        )

    def on_step_begin(step_no: int, _agent_name: str) -> None:
        wire.send(
            WireEvent(
                type=EventType.STEP_BEGIN,
                data={"step": step_no, "agent": agent_name},
            )
        )

    def on_tool_call(tc_id: str, name: str, arguments: str) -> None:
        wire.send(
            WireEvent(
                type=EventType.TOOL_CALL,
                data={"name": name, "id": tc_id, "agent": agent_name},
            )
        )

    def on_tool_result(tc_id: str, name: str, content: str, is_error: bool) -> None:
        wire.send(
            WireEvent(
                type=EventType.TOOL_RESULT,
                data={
                    "name": name,
                    "id": tc_id,
                    "content": content[:500],
                    "is_error": is_error,
                    "agent": agent_name,
                },
            )
        )

    def on_step(step_no: int, result: Any) -> None:
        if hasattr(result, "usage") and result.usage:
            wire.send(
                WireEvent(
                    type=EventType.STATUS,
                    data={"tokens": result.usage.total_tokens, "agent": agent_name},
                )
            )

    def on_begin() -> None:
        wire.send(
            WireEvent(
                type=EventType.SUBAGENT_BEGIN,
                data={"agent": agent_name},
            )
        )

    def on_end() -> None:
        wire.send(
            WireEvent(
                type=EventType.SUBAGENT_END,
                data={"agent": agent_name},
            )
        )

    def on_dmail(checkpoint_id: int, message: str) -> None:
        wire.send(
            WireEvent(
                type=EventType.DMAIL,
                data={
                    "checkpoint_id": checkpoint_id,
                    "message": message,
                    "agent": agent_name,
                },
            )
        )

    return SubagentCallbacks(
        on_text=on_text,
        on_thinking=on_thinking,
        on_step_begin=on_step_begin,
        on_tool_call=on_tool_call,
        on_tool_result=on_tool_result,
        on_step=on_step,
        on_dmail=on_dmail,
        on_begin=on_begin,
        on_end=on_end,
    )
