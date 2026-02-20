"""PTY Manager — manages multiple PTY sessions."""

from __future__ import annotations

import logging
from typing import Any, Callable, TYPE_CHECKING

from reagent.pty.session import PTYSession

if TYPE_CHECKING:
    from reagent.session.wire import Wire

logger = logging.getLogger(__name__)


class PTYManager:
    """Manages the lifecycle of multiple PTY sessions.

    All debugger and tool sessions go through here. The manager ensures:
    - Sessions are tracked and can be looked up by ID
    - All sessions are killed on cleanup (no orphan processes)
    - Session limits are enforced
    - Exit notifications are fired via Wire (if attached)
    """

    MAX_SESSIONS = 10

    def __init__(self, wire: Wire | None = None) -> None:
        self._sessions: dict[str, PTYSession] = {}
        self._wire = wire

    async def spawn(
        self,
        command: list[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        title: str = "",
    ) -> PTYSession:
        """Spawn a new PTY session.

        Args:
            command: Command and arguments (e.g., ["gdb", "-q", "binary"]).
            cwd: Working directory.
            env: Additional environment variables.
            title: Human-readable title for the session.

        Returns:
            The new PTY session.
        """
        if len(self._sessions) >= self.MAX_SESSIONS:
            # Kill the oldest session
            oldest = next(iter(self._sessions))
            logger.warning("Max sessions reached, killing oldest: %s", oldest)
            await self.kill(oldest)

        session = PTYSession(
            command=command,
            cwd=cwd or ".",
            env=env or {},
            title=title,
        )

        # Wire up exit notification
        if self._wire:
            wire = self._wire

            def _on_exit(s: PTYSession, exit_code: int | None) -> None:
                tail = s.buffer.read_tail(3)
                last_output = "\n".join(tail) if tail else ""
                wire.send_pty_exit(s.id, s.title, exit_code, last_output)

            session.set_on_exit(_on_exit)

        await session.start()
        self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> PTYSession | None:
        """Get a session by ID."""
        return self._sessions.get(session_id)

    async def kill(self, session_id: str) -> None:
        """Kill a session and remove it from tracking."""
        session = self._sessions.pop(session_id, None)
        if session:
            session.kill()

    def list_sessions(self) -> list[dict[str, Any]]:
        """List all active sessions."""
        return [
            {
                "id": s.id,
                "title": s.title,
                "command": " ".join(s.command),
                "alive": s.alive,
                "status": s.status.value,
                "lines": s.buffer.line_count,
            }
            for s in self._sessions.values()
        ]

    async def cleanup(self) -> None:
        """Kill all sessions. Called on shutdown."""
        for session_id in list(self._sessions.keys()):
            await self.kill(session_id)
        logger.info("All PTY sessions cleaned up")

    def __len__(self) -> int:
        return len(self._sessions)
