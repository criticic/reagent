"""Wire protocol — decouples agent logic from UI.

Events flow from the agent (soul) to the UI. The UI subscribes to the
wire and renders events. This enables TUI, CLI pipe mode, and future
web UI from the same agent code.
"""

from __future__ import annotations

import asyncio
import enum
from dataclasses import dataclass, field
from typing import Any


class EventType(enum.Enum):
    TURN_BEGIN = "turn_begin"
    TURN_END = "turn_end"
    STEP_BEGIN = "step_begin"
    TEXT = "text"
    THINKING = "thinking"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    OBSERVATION = "observation"
    HYPOTHESIS = "hypothesis"
    FINDING = "finding"
    TARGET_INFO = "target_info"
    SUBAGENT_BEGIN = "subagent_begin"
    SUBAGENT_END = "subagent_end"
    COMPACTION = "compaction"
    DMAIL = "dmail"
    ERROR = "error"
    STATUS = "status"
    PTY_EXIT = "pty_exit"


@dataclass
class WireEvent:
    """An event on the wire."""

    type: EventType
    data: dict[str, Any] = field(default_factory=dict)


class Wire:
    """Async message bus: agent -> UI subscribers.

    Single-producer, multi-consumer broadcast.
    """

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[WireEvent | None]] = []
        self._closed: bool = False

    def send(self, event: WireEvent) -> None:
        """Send an event to all subscribers.

        Silently drops events after ``close()`` has been called.
        """
        if self._closed:
            return
        for q in self._subscribers:
            q.put_nowait(event)

    def send_text(self, text: str) -> None:
        self.send(WireEvent(type=EventType.TEXT, data={"text": text}))

    def send_status(self, message: str) -> None:
        self.send(WireEvent(type=EventType.STATUS, data={"message": message}))

    def send_error(self, error: str) -> None:
        self.send(WireEvent(type=EventType.ERROR, data={"error": error}))

    def send_observation(self, description: str, category: str = "general") -> None:
        self.send(
            WireEvent(
                type=EventType.OBSERVATION,
                data={"description": description, "category": category},
            )
        )

    def send_hypothesis(
        self,
        description: str,
        status: str = "proposed",
        confidence: float = 0.5,
        hyp_id: str = "",
    ) -> None:
        self.send(
            WireEvent(
                type=EventType.HYPOTHESIS,
                data={
                    "description": description,
                    "status": status,
                    "confidence": confidence,
                    "id": hyp_id,
                },
            )
        )

    def send_finding(
        self,
        description: str,
        category: str = "general",
        verified: bool = True,
    ) -> None:
        self.send(
            WireEvent(
                type=EventType.FINDING,
                data={
                    "description": description,
                    "category": category,
                    "verified": verified,
                },
            )
        )

    def send_target_info(self, target_data: dict[str, Any]) -> None:
        """Send target info update to the UI sidebar."""
        self.send(
            WireEvent(
                type=EventType.TARGET_INFO,
                data=target_data,
            )
        )

    def send_pty_exit(
        self,
        session_id: str,
        title: str,
        exit_code: int | None,
        last_output: str = "",
    ) -> None:
        """Notify subscribers that a PTY session exited unexpectedly."""
        self.send(
            WireEvent(
                type=EventType.PTY_EXIT,
                data={
                    "session_id": session_id,
                    "title": title,
                    "exit_code": exit_code,
                    "last_output": last_output[:500],
                },
            )
        )

    def subscribe(self) -> asyncio.Queue[WireEvent | None]:
        """Subscribe to events. Returns a queue to read from."""
        q: asyncio.Queue[WireEvent | None] = asyncio.Queue()
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        """Unsubscribe from events."""
        if q in self._subscribers:
            self._subscribers.remove(q)

    def close(self) -> None:
        """Signal all subscribers that the wire is closing."""
        self._closed = True
        for q in self._subscribers:
            q.put_nowait(None)
