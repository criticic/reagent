"""PTY session — a managed pseudo-terminal for interactive tools."""

from __future__ import annotations

import asyncio
import enum
import logging
import os
import pty
import re
import signal
import subprocess
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from reagent.pty.buffer import RollingBuffer
from reagent.tool.truncation import strip_ansi, sanitize_binary_output

logger = logging.getLogger(__name__)


class PTYStatus(enum.Enum):
    """Lifecycle states for a PTY session."""

    RUNNING = "running"
    KILLING = "killing"  # Kill requested, waiting for process to die
    KILLED = "killed"  # Killed by us (SIGKILL)
    EXITED = "exited"  # Process exited on its own


@dataclass
class PTYSession:
    """A managed pseudo-terminal session.

    Wraps an interactive process (debugger, shell, etc.) with:
    - Process group isolation (start_new_session) for safe tree-killing
    - Rolling output buffer (50K lines)
    - ANSI stripping and binary sanitization
    - Prompt-based command/response interaction
    - Timeout support
    - Exit notification callback

    Uses subprocess.Popen (not os.fork) to avoid deadlocks when
    spawned from within an asyncio event loop on macOS.
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    command: list[str] = field(default_factory=list)
    cwd: str = field(default_factory=os.getcwd)
    env: dict[str, str] = field(default_factory=dict)
    title: str = ""

    # Internal state
    buffer: RollingBuffer = field(default_factory=RollingBuffer)
    _master_fd: int = field(default=-1, init=False)
    _proc: subprocess.Popen | None = field(default=None, init=False)
    _pid: int = field(default=0, init=False)
    _pgid: int = field(default=0, init=False)
    _reader_task: asyncio.Task | None = field(default=None, init=False)
    _status: PTYStatus = field(default=PTYStatus.RUNNING, init=False)
    _on_exit: Callable[[PTYSession, int | None], None] | None = field(
        default=None, init=False
    )

    def set_on_exit(self, callback: Callable[[PTYSession, int | None], None]) -> None:
        """Set a callback to be invoked when the process exits unexpectedly.

        The callback receives (session, exit_code). It is called from the
        reader task when the process dies on its own — NOT when killed via
        kill().
        """
        self._on_exit = callback

    async def start(self) -> None:
        """Spawn the process in a new PTY with its own process group."""
        # Create PTY pair
        master_fd, slave_fd = pty.openpty()
        self._master_fd = master_fd

        # Build environment
        env = {**os.environ, **self.env}
        env["TERM"] = "dumb"  # Minimize ANSI escape sequences
        env.pop("PROMPT_COMMAND", None)

        try:
            # Use subprocess.Popen instead of os.fork to avoid
            # deadlocks in asyncio contexts (especially on macOS)
            self._proc = subprocess.Popen(
                self.command,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                start_new_session=True,  # Creates new process group
                env=env,
                cwd=self.cwd,
            )
        finally:
            # Parent always closes slave fd
            os.close(slave_fd)

        self._pid = self._proc.pid
        self._pgid = os.getpgid(self._pid)
        self._status = PTYStatus.RUNNING

        # Attach the asyncio event loop to the buffer for event-based notification
        self.buffer.attach_loop(asyncio.get_running_loop())

        # Start async reader
        self._reader_task = asyncio.create_task(self._read_loop())

        logger.info(
            "PTY session %s started: pid=%d pgid=%d cmd=%s",
            self.id,
            self._pid,
            self._pgid,
            " ".join(self.command),
        )

    async def _read_loop(self) -> None:
        """Continuously read output from the PTY master fd."""
        loop = asyncio.get_running_loop()
        try:
            while self._status == PTYStatus.RUNNING:
                try:
                    data = await loop.run_in_executor(
                        None, lambda: os.read(self._master_fd, 4096)
                    )
                except OSError:
                    break

                if not data:
                    break

                raw_text = data.decode("utf-8", errors="replace")
                cleaned = strip_ansi(raw_text)
                cleaned = sanitize_binary_output(cleaned)
                self.buffer.append_text(cleaned, raw_text=raw_text)
        except Exception as e:
            logger.debug("PTY reader %s ended: %s", self.id, e)
        finally:
            # Only transition to EXITED if we weren't already killing
            if self._status == PTYStatus.RUNNING:
                exit_code = self._proc.poll() if self._proc else None
                self._status = PTYStatus.EXITED
                logger.info("PTY session %s exited (code=%s)", self.id, exit_code)
                if self._on_exit:
                    try:
                        self._on_exit(self, exit_code)
                    except Exception:
                        logger.exception(
                            "Error in on_exit callback for session %s", self.id
                        )

    async def send(self, data: str, timeout: float = 30.0) -> str:
        """Send input to the PTY and capture output.

        Sends the command, waits for new output to settle (no new output
        for a brief period), then returns what was produced.

        Args:
            data: Input to send (command text, will have \\n appended if missing).
            timeout: Maximum seconds to wait for output.

        Returns:
            New output produced after the command.
        """
        if self._status != PTYStatus.RUNNING:
            raise RuntimeError(f"PTY session {self.id} is not running")

        # Record current buffer position
        before = self.buffer.line_count

        # Send the command
        if not data.endswith("\n"):
            data += "\n"
        os.write(self._master_fd, data.encode())

        # Wait for output to settle
        output_lines = await self._wait_for_output(before, timeout)
        return "\n".join(output_lines)

    async def send_and_match(
        self, data: str, pattern: str, timeout: float = 30.0
    ) -> str:
        """Send input and wait for a regex pattern in the output.

        Args:
            data: Command to send.
            pattern: Regex pattern to wait for.
            timeout: Maximum seconds to wait.

        Returns:
            All output from command send until pattern match (inclusive).
        """
        if self._status != PTYStatus.RUNNING:
            raise RuntimeError(f"PTY session {self.id} is not running")

        before = self.buffer.line_count

        if not data.endswith("\n"):
            data += "\n"
        os.write(self._master_fd, data.encode())

        compiled = re.compile(pattern)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout

        while loop.time() < deadline:
            current = self.buffer.line_count
            if current > before:
                new_lines = self.buffer.read(offset=before, limit=current - before)
                for i, line in enumerate(new_lines):
                    if compiled.search(line):
                        return "\n".join(new_lines[: i + 1])
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            await self.buffer.wait_for_data(timeout=min(remaining, 0.5))

        # Timeout — return whatever we have
        current = self.buffer.line_count
        new_lines = self.buffer.read(offset=before, limit=current - before)
        return "\n".join(new_lines)

    async def _wait_for_output(
        self, start_line: int, timeout: float, settle_time: float = 0.3
    ) -> list[str]:
        """Wait for output to settle after a command.

        Uses event-based notification instead of fixed-interval polling.
        Returns new lines produced after start_line.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        last_count = start_line
        settled_at = None

        while loop.time() < deadline:
            current = self.buffer.line_count
            if current > last_count:
                last_count = current
                settled_at = loop.time()
            elif settled_at and (loop.time() - settled_at) > settle_time:
                # Output has settled
                break
            elif current > start_line and settled_at is None:
                settled_at = loop.time()

            # Wait for new data or settle timeout, whichever comes first
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            wait_time = settle_time if settled_at else min(remaining, 0.5)
            await self.buffer.wait_for_data(timeout=wait_time)

        # Return new lines
        count = self.buffer.line_count - start_line
        if count > 0:
            return self.buffer.read(offset=start_line, limit=count)
        return []

    def kill(self) -> None:
        """Kill the entire process tree."""
        if self._status not in (PTYStatus.RUNNING, PTYStatus.KILLING):
            return

        self._status = PTYStatus.KILLING
        try:
            os.killpg(self._pgid, signal.SIGKILL)
            logger.info("Killed PTY session %s (pgid=%d)", self.id, self._pgid)
        except ProcessLookupError:
            logger.debug("Process group already gone: %d", self._pgid)
        except Exception as e:
            logger.warning("Error killing PTY session %s: %s", self.id, e)

        # Wait for process to be reaped (avoids zombies)
        if self._proc is not None:
            try:
                self._proc.wait(timeout=2)
            except Exception:
                pass

        try:
            os.close(self._master_fd)
        except OSError:
            pass

        self._status = PTYStatus.KILLED

    @property
    def alive(self) -> bool:
        return self._status == PTYStatus.RUNNING

    @property
    def status(self) -> PTYStatus:
        return self._status

    async def wait_for_exit(self, timeout: float = 10.0) -> int | None:
        """Wait for the process to exit. Returns exit code or None on timeout."""
        if self._proc is None:
            return -1
        try:
            loop = asyncio.get_running_loop()
            deadline = loop.time() + timeout
            while loop.time() < deadline:
                ret = self._proc.poll()
                if ret is not None:
                    if self._status == PTYStatus.RUNNING:
                        self._status = PTYStatus.EXITED
                    return ret
                await asyncio.sleep(0.1)
        except Exception:
            if self._status == PTYStatus.RUNNING:
                self._status = PTYStatus.EXITED
            return -1
        return None

    def __del__(self) -> None:
        """Ensure cleanup on garbage collection."""
        if self._status in (PTYStatus.RUNNING, PTYStatus.KILLING):
            self.kill()
