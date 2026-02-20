"""Rolling output buffer for PTY sessions."""

from __future__ import annotations

import asyncio
import threading
from collections import deque


class RollingBuffer:
    """Thread-safe rolling buffer for PTY output lines.

    Stores up to ``max_lines`` lines in two parallel tracks:

    * **cleaned** (``_lines``) — ANSI-stripped, binary-sanitized text
      used by the agent / LLM.
    * **raw** (``_raw_lines``) — original terminal output preserving
      ANSI escape sequences, suitable for xterm.js-style rendering.

    An ``asyncio.Event`` is set whenever new data arrives, allowing
    consumers to ``await`` instead of polling.  Call ``attach_loop()``
    once from the asyncio thread to enable this.
    """

    def __init__(self, max_lines: int = 50_000) -> None:
        self._lines: deque[str] = deque(maxlen=max_lines)
        self._raw_lines: deque[str] = deque(maxlen=max_lines)
        self._total_lines: int = 0  # Total lines ever added
        self._lock = threading.Lock()
        # Event-based notification (set after attach_loop)
        self._data_event: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def attach_loop(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """Attach an asyncio event loop so append() can signal waiters.

        Must be called from the asyncio thread (or pass an explicit loop).
        After this, ``wait_for_data()`` becomes usable.
        """
        self._loop = loop or asyncio.get_running_loop()
        self._data_event = asyncio.Event()

    def append(self, line: str, raw_line: str | None = None) -> None:
        """Append a line to the buffer.

        Args:
            line: Cleaned (ANSI-stripped) text.
            raw_line: Original text with ANSI codes preserved.
                      Defaults to ``line`` if not provided.
        """
        with self._lock:
            self._lines.append(line)
            self._raw_lines.append(raw_line if raw_line is not None else line)
            self._total_lines += 1
        # Signal waiters (thread-safe)
        if self._data_event is not None and self._loop is not None:
            self._loop.call_soon_threadsafe(self._data_event.set)

    def append_text(self, text: str, raw_text: str | None = None) -> None:
        """Append text, splitting into lines.

        Args:
            text: Cleaned text (ANSI-stripped).
            raw_text: Original text with ANSI preserved.
                      Defaults to ``text`` if not provided.
        """
        cleaned_lines = text.split("\n")
        raw_lines = (raw_text or text).split("\n")
        # Ensure same number of lines (pad raw if needed)
        while len(raw_lines) < len(cleaned_lines):
            raw_lines.append("")
        with self._lock:
            for cl, rl in zip(cleaned_lines, raw_lines):
                self._lines.append(cl)
                self._raw_lines.append(rl)
                self._total_lines += 1
        # Signal once after batch
        if self._data_event is not None and self._loop is not None:
            self._loop.call_soon_threadsafe(self._data_event.set)

    async def wait_for_data(self, timeout: float | None = None) -> bool:
        """Wait until new data is appended (or timeout).

        Returns True if data arrived, False on timeout.
        Resets the event so the next call blocks again.
        """
        if self._data_event is None:
            # Fallback: no loop attached, just sleep briefly
            await asyncio.sleep(0.05)
            return True
        try:
            await asyncio.wait_for(self._data_event.wait(), timeout=timeout)
            self._data_event.clear()
            return True
        except asyncio.TimeoutError:
            return False

    def read(self, offset: int = 0, limit: int = 500) -> list[str]:
        """Read cleaned lines from the buffer.

        Args:
            offset: 0-based line offset within the current buffer.
            limit: Maximum number of lines to return.

        Returns:
            List of cleaned lines.
        """
        with self._lock:
            lines = list(self._lines)
        start = min(offset, len(lines))
        end = min(start + limit, len(lines))
        return lines[start:end]

    def read_raw(self, offset: int = 0, limit: int = 500) -> list[str]:
        """Read raw lines (with ANSI codes preserved) from the buffer.

        Args:
            offset: 0-based line offset within the current buffer.
            limit: Maximum number of lines to return.

        Returns:
            List of raw lines.
        """
        with self._lock:
            lines = list(self._raw_lines)
        start = min(offset, len(lines))
        end = min(start + limit, len(lines))
        return lines[start:end]

    def read_all(self) -> str:
        """Read all buffered cleaned content as a single string."""
        with self._lock:
            return "\n".join(self._lines)

    def read_all_raw(self) -> str:
        """Read all buffered raw content as a single string."""
        with self._lock:
            return "\n".join(self._raw_lines)

    def read_tail(self, n: int = 100) -> list[str]:
        """Read the last N cleaned lines."""
        with self._lock:
            lines = list(self._lines)
        return lines[-n:] if len(lines) > n else lines

    def read_tail_raw(self, n: int = 100) -> list[str]:
        """Read the last N raw lines (ANSI preserved)."""
        with self._lock:
            lines = list(self._raw_lines)
        return lines[-n:] if len(lines) > n else lines

    def search(self, pattern: str, limit: int = 50) -> list[tuple[int, str]]:
        """Search for lines matching a regex pattern.

        Returns list of (line_number, line_text) tuples.
        """
        import re

        try:
            compiled = re.compile(pattern)
        except re.error:
            return []

        results = []
        with self._lock:
            for i, line in enumerate(self._lines):
                if compiled.search(line):
                    results.append((i, line))
                    if len(results) >= limit:
                        break
        return results

    @property
    def line_count(self) -> int:
        """Current number of lines in the buffer."""
        with self._lock:
            return len(self._lines)

    @property
    def total_lines(self) -> int:
        """Total number of lines ever added."""
        with self._lock:
            return self._total_lines

    def clear(self) -> None:
        """Clear the buffer."""
        with self._lock:
            self._lines.clear()
            self._raw_lines.clear()
            self._total_lines = 0
