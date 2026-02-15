"""Rolling output buffer for PTY sessions."""

from __future__ import annotations

import threading
from collections import deque


class RollingBuffer:
    """Thread-safe rolling buffer for PTY output lines.

    Stores up to `max_lines` lines. When the limit is reached,
    oldest lines are discarded. Supports reading with offset/limit,
    pattern matching, and total line counting.
    """

    def __init__(self, max_lines: int = 50_000) -> None:
        self._lines: deque[str] = deque(maxlen=max_lines)
        self._total_lines: int = 0  # Total lines ever added
        self._lock = threading.Lock()

    def append(self, line: str) -> None:
        """Append a line to the buffer."""
        with self._lock:
            self._lines.append(line)
            self._total_lines += 1

    def append_text(self, text: str) -> None:
        """Append text, splitting into lines."""
        for line in text.split("\n"):
            self.append(line)

    def read(self, offset: int = 0, limit: int = 500) -> list[str]:
        """Read lines from the buffer.

        Args:
            offset: 0-based line offset within the current buffer.
            limit: Maximum number of lines to return.

        Returns:
            List of lines.
        """
        with self._lock:
            lines = list(self._lines)
        start = min(offset, len(lines))
        end = min(start + limit, len(lines))
        return lines[start:end]

    def read_all(self) -> str:
        """Read all buffered content as a single string."""
        with self._lock:
            return "\n".join(self._lines)

    def read_tail(self, n: int = 100) -> list[str]:
        """Read the last N lines."""
        with self._lock:
            lines = list(self._lines)
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
        return self._total_lines

    def clear(self) -> None:
        """Clear the buffer."""
        with self._lock:
            self._lines.clear()
            self._total_lines = 0
