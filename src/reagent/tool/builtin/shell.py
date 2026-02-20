"""Shell tool — execute commands via a managed PTY session.

When a PTYManager is provided, the tool spawns a persistent bash session
and sends commands through it, giving the agent a true interactive
terminal.  If no PTYManager is available it falls back to one-shot
``asyncio.create_subprocess_shell()``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import signal
from typing import TYPE_CHECKING, ClassVar

from pydantic import BaseModel, Field

from reagent.tool.base import BaseTool, ToolOk, ToolError, ToolResult
from reagent.tool.truncation import strip_ansi, sanitize_binary_output

if TYPE_CHECKING:
    from reagent.pty.manager import PTYManager
    from reagent.pty.session import PTYSession

logger = logging.getLogger(__name__)

# Unique prompt sentinel that won't appear in normal command output.
# The shell PS1 is set to this so we can reliably detect when a command
# finishes.
_SENTINEL = "___REAGENT_PROMPT___"
_PROMPT_RE = re.compile(re.escape(_SENTINEL) + r"\s*$")


class ShellParams(BaseModel):
    command: str = Field(description="The shell command to execute.")
    timeout: int = Field(default=120, description="Timeout in seconds.")
    workdir: str | None = Field(
        default=None, description="Working directory. Defaults to project root."
    )
    stdin: str | None = Field(
        default=None,
        description="Optional input to feed to the command's stdin. "
        "Use this for interactive programs that read from stdin (e.g. password prompts, license key inputs). "
        "The string is sent as-is — include newlines (\\n) where the program expects Enter.",
    )


class ShellTool(BaseTool[ShellParams]):
    """Execute shell commands in a persistent PTY session.

    The first invocation spawns a bash session; subsequent calls reuse it.
    This gives the agent a real terminal: ``cd`` persists, environment
    variables accumulate, and interactive programs work naturally via the
    ``stdin`` parameter.

    Falls back to one-shot subprocess execution when no PTYManager is
    available.
    """

    name: ClassVar[str] = "shell"
    description: ClassVar[str] = (
        "Execute a shell command. Output is captured and returned. "
        "Commands run in a persistent shell session — cd, env vars, and "
        "other state persist between calls. "
        "Use for running analysis tools, compiling, file operations, etc. "
        "IMPORTANT: When running interactive binaries that read input, use the `stdin` parameter "
        "to feed input (e.g. stdin='test123\\n'). Without stdin, the process receives EOF immediately."
    )
    param_model: ClassVar[type[BaseModel]] = ShellParams

    def __init__(
        self,
        cwd: str | None = None,
        pty_manager: PTYManager | None = None,
    ) -> None:
        self._cwd = cwd or os.getcwd()
        self._pty_manager: PTYManager | None = pty_manager
        self._session: PTYSession | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute(self, params: ShellParams) -> ToolResult:
        if self._pty_manager is not None:
            return await self._execute_pty(params)
        return await self._execute_subprocess(params)

    # ------------------------------------------------------------------
    # PTY-based execution (preferred)
    # ------------------------------------------------------------------

    async def _ensure_session(self) -> PTYSession:
        """Return the current shell session, spawning one if needed."""
        if self._session is not None and self._session.alive:
            return self._session

        # Spawn a new bash session with our sentinel prompt
        self._session = await self._pty_manager.spawn(  # type: ignore[union-attr]
            command=["bash", "--norc", "--noprofile", "-i"],
            cwd=self._cwd,
            env={"PS1": _SENTINEL, "PS2": ""},
            title="shell",
        )

        # Wait for the initial prompt
        await self._wait_for_prompt(self._session, timeout=5.0)
        return self._session

    async def _execute_pty(self, params: ShellParams) -> ToolResult:
        """Execute via the persistent PTY session."""
        workdir = params.workdir or self._cwd

        if not os.path.isdir(workdir):
            return ToolError(output=f"Directory does not exist: {workdir}")

        try:
            session = await self._ensure_session()
        except Exception as e:
            logger.warning("Failed to create shell session, falling back: %s", e)
            return await self._execute_subprocess(params)

        try:
            # cd to workdir (if different from where the shell already is)
            # Use a sub-shell-safe approach: always cd before the command
            command = params.command
            if params.workdir:
                command = f"cd {_shell_quote(workdir)} && {command}"

            # If stdin is provided, pipe it through the command using a
            # heredoc.  This avoids the race between sending the command
            # and sending the input that exists with raw fd writes.
            full_command = command
            if params.stdin:
                delimiter = "_REAGENT_EOF_"
                full_command = f"{command} <<'{delimiter}'\n{params.stdin}\n{delimiter}"

            # Send the command and wait for the prompt to reappear
            raw_output = await session.send_and_match(
                full_command, _PROMPT_RE.pattern, timeout=params.timeout
            )

            output = self._clean_output(raw_output, command, params.stdin)

            # Query the exit code of the last command
            exit_code = await self._get_exit_code(session)
            brief = f"exit={exit_code}: {params.command[:50]}"

            if exit_code != 0:
                return ToolError(
                    output=f"[Exit code: {exit_code}]\n{output}",
                    brief=brief,
                )

            return ToolOk(output=output, brief=brief)

        except asyncio.TimeoutError:
            # The command hung — kill the session and let the next call
            # spawn a fresh one.
            if self._session is not None:
                await self._pty_manager.kill(self._session.id)  # type: ignore[union-attr]
                self._session = None
            return ToolError(
                output=f"Command timed out after {params.timeout}s: {params.command}",
                brief=f"Timeout: {params.command[:50]}",
            )
        except Exception as e:
            logger.error("Shell PTY error: %s", e, exc_info=True)
            return ToolError(output=f"Failed to execute command: {e}")

    async def _wait_for_prompt(self, session: PTYSession, timeout: float = 5.0) -> None:
        """Wait for the sentinel prompt to appear."""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            tail = session.buffer.read_tail(5)
            for line in tail:
                if _PROMPT_RE.search(line):
                    return
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                break
            await session.buffer.wait_for_data(timeout=min(remaining, 0.5))
        logger.warning("Timed out waiting for shell prompt")

    async def _get_exit_code(self, session: PTYSession) -> int:
        """Query the exit code of the last command."""
        try:
            raw = await session.send_and_match(
                "echo $?", _PROMPT_RE.pattern, timeout=5.0
            )
            # Parse: output should be just a number between the echo and prompt
            for line in raw.split("\n"):
                stripped = line.strip()
                if stripped.isdigit():
                    return int(stripped)
                # Handle negative-ish exit codes
                try:
                    return int(stripped)
                except ValueError:
                    continue
        except Exception:
            pass
        return 0  # Default to success if we can't determine

    def _clean_output(self, raw: str, command: str, stdin: str | None = None) -> str:
        """Clean up raw PTY output: strip echoed command, prompt lines, ANSI, CR."""
        # PTY output uses \r\n line endings — normalize to \n
        raw = raw.replace("\r\n", "\n").replace("\r", "\n")

        lines = raw.split("\n")

        # --- Phase 1: Strip the echoed input block -----------------------
        # The PTY echoes back everything we typed.  For a simple command
        # like ``echo hello`` this is one line; for a heredoc it includes
        # the body and the closing delimiter (with ``>`` continuation
        # prompts).  We strip these leading echo lines positionally.
        #
        # With heredoc (stdin != None):
        #   cat <<'_REAGENT_EOF_'        <-- echoed command
        #   > hello from stdin           <-- echoed heredoc body
        #   > _REAGENT_EOF_              <-- echoed delimiter
        #   hello from stdin             <-- actual output starts here
        #
        # Without heredoc:
        #   echo hello                   <-- echoed command
        #   hello                        <-- actual output
        #
        # Strategy: find the end of the echoed block and slice.
        start = 0

        if stdin is not None:
            # Find the LAST line matching the heredoc delimiter.  Everything
            # up to and including it is the echoed input block.
            last_delim_idx = -1
            for i, line in enumerate(lines):
                stripped = line.strip().lstrip("> ").strip()
                if stripped == "_REAGENT_EOF_":
                    last_delim_idx = i
            if last_delim_idx >= 0:
                start = last_delim_idx + 1
        else:
            # No heredoc — strip the echoed command at the top.
            # The PTY echoes back exactly what we typed, but the terminal
            # may break it across multiple lines (e.g. embedded newlines
            # in quoted strings get rendered literally).  We find the end
            # of the echo by looking for the last part of the command
            # string.  The echoed block always starts at line 0.
            cmd_parts = [cl.strip() for cl in command.split("\n") if cl.strip()]
            if cmd_parts and lines:
                last_part = cmd_parts[-1]
                # Scan only within a bounded window at the top — the echo
                # can't be longer than about 2× the number of command
                # parts (PTY may insert blank lines between them).
                scan_limit = min(len(lines), max(len(cmd_parts) * 3, 10))
                for i, line in enumerate(lines[:scan_limit]):
                    stripped = line.strip()
                    if last_part in stripped or stripped.endswith(last_part):
                        start = i + 1
                        break
                else:
                    # Fallback: if we can't find the last cmd part, check
                    # if the first line matches the first cmd part and
                    # just skip it (single-line command case).
                    first_stripped = lines[0].strip() if lines else ""
                    if cmd_parts[0] in first_stripped:
                        start = 1

        lines = lines[start:]

        # --- Phase 2: Strip prompt / sentinel lines ----------------------
        cleaned: list[str] = []
        for line in lines:
            stripped = line.strip()
            # Skip prompt-only lines
            if _PROMPT_RE.fullmatch(stripped):
                continue
            # Skip bare sentinel
            if stripped == _SENTINEL:
                continue
            cleaned.append(line)

        result = "\n".join(cleaned).strip()
        result = sanitize_binary_output(result)
        return result

    # ------------------------------------------------------------------
    # Subprocess fallback (no PTYManager)
    # ------------------------------------------------------------------

    async def _execute_subprocess(self, params: ShellParams) -> ToolResult:
        """One-shot subprocess execution — legacy fallback."""
        workdir = params.workdir or self._cwd
        if not os.path.isdir(workdir):
            return ToolError(output=f"Directory does not exist: {workdir}")

        try:
            process = await asyncio.create_subprocess_shell(
                params.command,
                stdin=asyncio.subprocess.PIPE
                if params.stdin
                else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=workdir,
                preexec_fn=os.setpgrp,  # New process group
                env={**os.environ, "TERM": "dumb"},  # Reduce ANSI output
            )

            try:
                stdin_bytes = params.stdin.encode("utf-8") if params.stdin else None
                stdout, _ = await asyncio.wait_for(
                    process.communicate(input=stdin_bytes),
                    timeout=params.timeout,
                )
            except asyncio.TimeoutError:
                # Kill the entire process group
                if process.pid:
                    try:
                        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                return ToolError(
                    output=f"Command timed out after {params.timeout}s: {params.command}",
                    brief=f"Timeout: {params.command[:50]}",
                )

            output = stdout.decode("utf-8", errors="replace") if stdout else ""
            output = strip_ansi(output)
            output = sanitize_binary_output(output)

            exit_code = process.returncode or 0
            brief = f"exit={exit_code}: {params.command[:50]}"

            if exit_code != 0:
                return ToolError(
                    output=f"[Exit code: {exit_code}]\n{output}",
                    brief=brief,
                )

            return ToolOk(output=output, brief=brief)

        except Exception as e:
            return ToolError(output=f"Failed to execute command: {e}")


def _shell_quote(s: str) -> str:
    """Quote a string for safe shell usage."""
    return "'" + s.replace("'", "'\\''") + "'"
