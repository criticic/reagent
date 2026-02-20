"""Debugger tools — GDB/LLDB interaction via PTY sessions.

Provides tools for interactive debugging: launching debug sessions,
setting breakpoints, stepping, reading registers/memory, and evaluating
expressions. Automatically detects and adapts to GDB or LLDB.

All tools share a debugger session registry keyed by session ID.
The first tool (DebugLaunchTool) spawns a PTY session; subsequent
tools operate on that session by ID.
"""

from __future__ import annotations

import asyncio
import enum
import logging
import os
import re
import shutil
import threading
from dataclasses import dataclass
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from reagent.pty.manager import PTYManager
from reagent.pty.session import PTYSession
from reagent.tool.base import BaseTool, ToolError, ToolOk, ToolResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Debugger type detection and command abstraction
# ---------------------------------------------------------------------------


class DebuggerType(enum.StrEnum):
    GDB = "gdb"
    LLDB = "lldb"


# Prompt patterns for detecting when the debugger is ready
_PROMPT_PATTERNS: dict[DebuggerType, str] = {
    DebuggerType.GDB: r"\(gdb\)\s*$",
    DebuggerType.LLDB: r"\(lldb\)\s*$",
}

# Command translation: abstract -> debugger-specific
_CMD_MAP: dict[DebuggerType, dict[str, str]] = {
    DebuggerType.GDB: {
        "run": "run",
        "continue": "continue",
        "step_into": "step",
        "step_over": "next",
        "step_out": "finish",
        "breakpoint": "break {location}",
        "breakpoint_delete": "delete {number}",
        "registers": "info registers",
        "registers_all": "info all-registers",
        "backtrace": "backtrace",
        "backtrace_full": "backtrace full",
        "memory": "x/{count}{format} {address}",
        "print": "print {expression}",
        "disassemble": "disassemble {location}",
        "info_locals": "info locals",
        "info_args": "info args",
        "info_breakpoints": "info breakpoints",
        "quit": "quit",
    },
    DebuggerType.LLDB: {
        "run": "run",
        "continue": "continue",
        "step_into": "step",
        "step_over": "next",
        "step_out": "finish",
        "breakpoint": "breakpoint set --name {location}",
        "breakpoint_addr": "breakpoint set --address {address}",
        "breakpoint_delete": "breakpoint delete {number}",
        "registers": "register read",
        "registers_all": "register read --all",
        "backtrace": "bt",
        "backtrace_full": "bt all",
        "memory": "memory read {address} --count {count} --format {format}",
        "print": "expression -- {expression}",
        "disassemble": "disassemble --name {location}",
        "info_locals": "frame variable",
        "info_args": "frame variable --no-locals",
        "info_breakpoints": "breakpoint list",
        "quit": "quit",
    },
}


def _xml_wrap(tag: str, content: str, **attrs: str) -> str:
    """Wrap content in an XML tag with optional attributes.

    Provides structural cues to the LLM so it can reliably parse
    debug tool output (inspired by opencode-pty's XML-tagged responses).
    """
    attr_str = "".join(f' {k}="{v}"' for k, v in attrs.items())
    return f"<{tag}{attr_str}>\n{content}\n</{tag}>"


def _detect_debugger() -> str | None:
    """Detect available debugger, preferring LLDB on macOS."""
    import platform

    if platform.system() == "Darwin":
        # macOS: prefer lldb
        if shutil.which("lldb"):
            return DebuggerType.LLDB
        if shutil.which("gdb"):
            return DebuggerType.GDB
    else:
        # Linux: prefer gdb
        if shutil.which("gdb"):
            return DebuggerType.GDB
        if shutil.which("lldb"):
            return DebuggerType.LLDB
    return None


# ---------------------------------------------------------------------------
# Debug session registry
# ---------------------------------------------------------------------------


@dataclass
class DebugSessionInfo:
    """Tracks a live debugger session."""

    session_id: str
    pty_session: PTYSession
    debugger_type: DebuggerType
    binary_path: str
    prompt_pattern: re.Pattern


class DebugSessionRegistry:
    """Registry of active debug sessions, shared across all debugger tools."""

    def __init__(self, pty_manager: PTYManager) -> None:
        self._pty_manager = pty_manager
        self._sessions: dict[str, DebugSessionInfo] = {}
        self._lock = threading.Lock()

    async def launch(
        self,
        binary_path: str,
        args: list[str] | None = None,
        debugger: str | None = None,
        env: dict[str, str] | None = None,
    ) -> DebugSessionInfo:
        """Launch a new debugger session."""
        # Detect debugger
        dbg_type = debugger or _detect_debugger()
        if not dbg_type:
            raise RuntimeError("No debugger found. Install GDB or LLDB.")

        if dbg_type not in (DebuggerType.GDB, DebuggerType.LLDB):
            raise ValueError(f"Unknown debugger type: {dbg_type}")

        # Build command
        if dbg_type == DebuggerType.GDB:
            cmd = ["gdb", "-q", "--nx", binary_path]
        else:
            cmd = ["lldb", "--no-use-colors", binary_path]

        # If args provided, we'll set them after launch
        cwd = os.path.dirname(os.path.abspath(binary_path)) or "."

        # Spawn PTY session
        pty_session = await self._pty_manager.spawn(
            command=cmd,
            cwd=cwd,
            env=env or {},
            title=f"{dbg_type}: {os.path.basename(binary_path)}",
        )

        # Wait for initial prompt
        prompt_pattern = re.compile(_PROMPT_PATTERNS[dbg_type])
        await self._wait_for_prompt(pty_session, prompt_pattern, timeout=10.0)

        # Set arguments if provided
        if args:
            if dbg_type == DebuggerType.GDB:
                set_args_cmd = f"set args {' '.join(args)}"
            else:
                set_args_cmd = f"settings set target.run-args {' '.join(args)}"
            await self._send_cmd(pty_session, set_args_cmd, prompt_pattern)

        info = DebugSessionInfo(
            session_id=pty_session.id,
            pty_session=pty_session,
            debugger_type=dbg_type,
            binary_path=binary_path,
            prompt_pattern=prompt_pattern,
        )

        with self._lock:
            self._sessions[pty_session.id] = info

        return info

    def get(self, session_id: str) -> DebugSessionInfo | None:
        with self._lock:
            return self._sessions.get(session_id)

    async def send_command(
        self, session_id: str, command: str, timeout: float = 30.0
    ) -> str:
        """Send a raw command to the debugger and return output."""
        info = self.get(session_id)
        if not info:
            raise ValueError(f"No debug session with ID '{session_id}'")
        if not info.pty_session.alive:
            raise RuntimeError(f"Debug session '{session_id}' is no longer running")

        return await self._send_cmd(
            info.pty_session, command, info.prompt_pattern, timeout
        )

    async def send_abstract_command(
        self,
        session_id: str,
        abstract_cmd: str,
        params: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> str:
        """Send an abstract command, translated to the right debugger syntax."""
        info = self.get(session_id)
        if not info:
            raise ValueError(f"No debug session with ID '{session_id}'")

        cmd_map = _CMD_MAP[info.debugger_type]
        template = cmd_map.get(abstract_cmd)
        if not template:
            raise ValueError(
                f"Unknown abstract command '{abstract_cmd}' for {info.debugger_type}"
            )

        if params:
            command = template.format(**params)
        else:
            command = template

        return await self.send_command(session_id, command, timeout)

    async def kill(self, session_id: str) -> None:
        """Kill a debug session."""
        with self._lock:
            info = self._sessions.pop(session_id, None)
        if info:
            # Try graceful quit first via the PTY send API
            try:
                if info.pty_session.alive:
                    await info.pty_session.send("quit", timeout=2.0)
                    await asyncio.sleep(0.3)
                    if info.pty_session.alive:
                        # Force confirm quit (GDB asks "Quit anyway?")
                        await info.pty_session.send("y", timeout=2.0)
                        await asyncio.sleep(0.2)
            except Exception as e:
                logger.debug(
                    "Error during graceful debugger quit for %s: %s", session_id, e
                )
            # Force kill via PTY manager
            await self._pty_manager.kill(session_id)

    def list_sessions(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "id": info.session_id,
                    "debugger": info.debugger_type,
                    "binary": info.binary_path,
                    "alive": info.pty_session.alive,
                }
                for info in self._sessions.values()
            ]

    async def _send_cmd(
        self,
        pty_session: PTYSession,
        command: str,
        prompt_pattern: re.Pattern,
        timeout: float = 30.0,
    ) -> str:
        """Send command and wait for the prompt to reappear."""
        output = await pty_session.send_and_match(
            command, prompt_pattern.pattern, timeout=timeout
        )
        # Clean up: strip the echoed command and trailing prompt
        lines = output.split("\n")
        cleaned = []
        for line in lines:
            stripped = line.strip()
            # Skip echoed command line
            if stripped == command.strip():
                continue
            # Skip prompt-only lines
            if prompt_pattern.fullmatch(stripped):
                continue
            cleaned.append(line)
        return "\n".join(cleaned).strip()

    async def _wait_for_prompt(
        self,
        pty_session: PTYSession,
        prompt_pattern: re.Pattern,
        timeout: float = 10.0,
    ) -> None:
        """Wait for the debugger prompt to appear in the output."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            tail = pty_session.buffer.read_tail(5)
            for line in tail:
                if prompt_pattern.search(line):
                    return
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            await pty_session.buffer.wait_for_data(timeout=min(remaining, 0.5))
        logger.warning("Timed out waiting for debugger prompt")


# ---------------------------------------------------------------------------
# Tool: debug_launch
# ---------------------------------------------------------------------------


class DebugLaunchParams(BaseModel):
    binary_path: str = Field(description="Path to the binary to debug.")
    args: list[str] = Field(
        default_factory=list,
        description=(
            "Arguments to pass to the binary when it runs. "
            "Example: ['--verbose', 'input.txt']."
        ),
    )
    debugger: str | None = Field(
        default=None,
        description=(
            "Debugger to use: 'gdb' or 'lldb'. "
            "Auto-detected if omitted (LLDB on macOS, GDB on Linux)."
        ),
    )


class DebugLaunchTool(BaseTool[DebugLaunchParams]):
    """Launch a debugger session for a binary."""

    name: ClassVar[str] = "debug_launch"
    description: ClassVar[str] = (
        "Launch a GDB or LLDB debugging session for a binary. "
        "Returns a session_id to use with other debug_* tools. "
        "The binary is loaded but NOT started — use debug_continue to run it. "
        "Auto-detects GDB vs LLDB based on platform."
    )
    param_model: ClassVar[type[BaseModel]] = DebugLaunchParams

    def __init__(self, registry: DebugSessionRegistry, cwd: str | None = None) -> None:
        self._registry = registry
        self._cwd = cwd or os.getcwd()

    async def execute(self, params: DebugLaunchParams) -> ToolResult:
        try:
            # Resolve binary path
            # If the path is relative, first try resolving it against the current working directory.
            # If that fails, it might be because the agent is operating in a different directory (e.g., --mask temp dir)
            # but the Python process is in the project root.
            # We trust the agent's intent if the file exists in the directory implied by the shell tool.

            # Attempt to resolve against the provided CWD
            binary = os.path.abspath(os.path.join(self._cwd, params.binary_path))

            # If not found there, try normal resolution (project root)
            if not os.path.isfile(binary):
                binary_fallback = os.path.abspath(params.binary_path)
                if os.path.isfile(binary_fallback):
                    binary = binary_fallback
                else:
                    # One last try: check relative to CWD if params.binary_path is relative
                    if not os.path.isabs(params.binary_path):
                        # Already checked join(self._cwd, params.binary_path) above
                        pass

            if not os.path.isfile(binary):
                return ToolError(
                    output=f"Binary not found: {binary} (cwd: {self._cwd})"
                )

            info = await self._registry.launch(
                binary_path=binary,
                args=params.args if params.args else None,
                debugger=params.debugger,
            )

            output_parts = [
                f"Debug session started.",
                f"  Session ID: {info.session_id}",
                f"  Debugger: {info.debugger_type}",
                f"  Binary: {info.binary_path}",
            ]
            if params.args:
                output_parts.append(f"  Args: {' '.join(params.args)}")
            output_parts.append(
                "\nThe binary is loaded but NOT running. "
                "Use debug_breakpoint to set breakpoints, then debug_continue to start."
            )

            return ToolOk(
                output=_xml_wrap(
                    "debug_launched",
                    "\n".join(output_parts),
                    session_id=info.session_id,
                    debugger=info.debugger_type,
                ),
                brief=f"debug session {info.session_id} ({info.debugger_type})",
            )
        except Exception as e:
            return ToolError(output=f"Failed to launch debugger: {e}")


# ---------------------------------------------------------------------------
# Tool: debug_breakpoint
# ---------------------------------------------------------------------------


class DebugBreakpointParams(BaseModel):
    session_id: str = Field(description="Debug session ID from debug_launch.")
    location: str = Field(
        description=(
            "Where to set the breakpoint. Can be:\n"
            "- Function name: 'main', 'check_password'\n"
            "- Address: '0x401000'\n"
            "- File:line: 'main.c:42'"
        ),
    )
    delete: bool = Field(
        default=False,
        description="If true, delete breakpoint at this location instead of setting one.",
    )


class DebugBreakpointTool(BaseTool[DebugBreakpointParams]):
    """Set or delete breakpoints in a debug session."""

    name: ClassVar[str] = "debug_breakpoint"
    description: ClassVar[str] = (
        "Set or delete a breakpoint in the debugger. "
        "Specify a function name, address (0x...), or file:line. "
        "Returns confirmation with breakpoint number."
    )
    param_model: ClassVar[type[BaseModel]] = DebugBreakpointParams

    def __init__(self, registry: DebugSessionRegistry) -> None:
        self._registry = registry

    async def execute(self, params: DebugBreakpointParams) -> ToolResult:
        try:
            info = self._registry.get(params.session_id)
            if not info:
                return ToolError(output=f"No debug session '{params.session_id}'")

            if params.delete:
                output = await self._registry.send_abstract_command(
                    params.session_id,
                    "breakpoint_delete",
                    {"number": params.location},
                )
                return ToolOk(
                    output=_xml_wrap(
                        "debug_output",
                        output or "Breakpoint deleted.",
                        session_id=params.session_id,
                        action="breakpoint_delete",
                        location=params.location,
                    ),
                    brief=f"deleted breakpoint {params.location}",
                )

            # Detect if it's an address (0x...) for LLDB special handling
            location = params.location
            if info.debugger_type == DebuggerType.LLDB and location.startswith("0x"):
                output = await self._registry.send_abstract_command(
                    params.session_id,
                    "breakpoint_addr",
                    {"address": location},
                )
            else:
                # For LLDB with function names, use --name
                # For file:line, send raw command
                if info.debugger_type == DebuggerType.LLDB and ":" in location:
                    # file:line format
                    parts = location.rsplit(":", 1)
                    cmd = f"breakpoint set --file {parts[0]} --line {parts[1]}"
                    output = await self._registry.send_command(params.session_id, cmd)
                else:
                    output = await self._registry.send_abstract_command(
                        params.session_id,
                        "breakpoint",
                        {"location": location},
                    )

            return ToolOk(
                output=_xml_wrap(
                    "debug_output",
                    output or "Breakpoint set.",
                    session_id=params.session_id,
                    action="breakpoint_set",
                    location=params.location,
                ),
                brief=f"breakpoint @ {params.location}",
            )
        except Exception as e:
            return ToolError(output=f"Breakpoint failed: {e}")


# ---------------------------------------------------------------------------
# Tool: debug_continue
# ---------------------------------------------------------------------------


class DebugContinueParams(BaseModel):
    session_id: str = Field(description="Debug session ID from debug_launch.")
    action: str = Field(
        default="continue",
        description=(
            "Action to take:\n"
            "- 'run': Start the program from the beginning\n"
            "- 'continue': Continue from current position (default)\n"
            "- 'step_into': Step one instruction, entering function calls\n"
            "- 'step_over': Step one instruction, skipping function calls\n"
            "- 'step_out': Run until the current function returns"
        ),
    )


class DebugContinueTool(BaseTool[DebugContinueParams]):
    """Control program execution: run, continue, step."""

    name: ClassVar[str] = "debug_continue"
    description: ClassVar[str] = (
        "Control execution of the debugged program. Actions: "
        "'run' (start from beginning), 'continue' (resume), "
        "'step_into', 'step_over', 'step_out'. "
        "Returns output showing where execution stopped (e.g., at a breakpoint)."
    )
    param_model: ClassVar[type[BaseModel]] = DebugContinueParams

    def __init__(self, registry: DebugSessionRegistry) -> None:
        self._registry = registry

    async def execute(self, params: DebugContinueParams) -> ToolResult:
        valid_actions = {"run", "continue", "step_into", "step_over", "step_out"}
        if params.action not in valid_actions:
            return ToolError(
                output=f"Invalid action '{params.action}'. Must be one of: {valid_actions}"
            )

        try:
            output = await self._registry.send_abstract_command(
                params.session_id,
                params.action,
                timeout=60.0,  # Execution may take a while
            )
            return ToolOk(
                output=_xml_wrap(
                    "debug_output",
                    output or f"({params.action} completed)",
                    session_id=params.session_id,
                    action=params.action,
                ),
                brief=f"{params.action}",
            )
        except Exception as e:
            return ToolError(output=f"Execution control failed: {e}")


# ---------------------------------------------------------------------------
# Tool: debug_registers
# ---------------------------------------------------------------------------


class DebugRegistersParams(BaseModel):
    session_id: str = Field(description="Debug session ID from debug_launch.")
    all_registers: bool = Field(
        default=False,
        description="If true, show all registers (including FP/SIMD). Default shows GP registers only.",
    )


class DebugRegistersTool(BaseTool[DebugRegistersParams]):
    """Read CPU register values."""

    name: ClassVar[str] = "debug_registers"
    description: ClassVar[str] = (
        "Read CPU register values from the debugged program. "
        "The program must be stopped at a breakpoint. "
        "By default shows general-purpose registers; set all_registers=true for everything."
    )
    param_model: ClassVar[type[BaseModel]] = DebugRegistersParams

    def __init__(self, registry: DebugSessionRegistry) -> None:
        self._registry = registry

    async def execute(self, params: DebugRegistersParams) -> ToolResult:
        try:
            cmd = "registers_all" if params.all_registers else "registers"
            output = await self._registry.send_abstract_command(params.session_id, cmd)
            if not output.strip():
                return ToolError(
                    output="No register data. Is the program stopped at a breakpoint?",
                    brief="no registers (not stopped?)",
                )
            return ToolOk(
                output=_xml_wrap(
                    "debug_output",
                    output,
                    session_id=params.session_id,
                    action=cmd,
                ),
                brief="registers",
            )
        except Exception as e:
            return ToolError(output=f"Failed to read registers: {e}")


# ---------------------------------------------------------------------------
# Tool: debug_memory
# ---------------------------------------------------------------------------


class DebugMemoryParams(BaseModel):
    session_id: str = Field(description="Debug session ID from debug_launch.")
    address: str = Field(
        description=(
            "Memory address to read. Examples: '0x7fffffffe000', '$rsp', '$sp'. "
            "Can use register names prefixed with $."
        ),
    )
    count: int = Field(
        default=64,
        description="Number of units to read (default 64).",
    )
    format: str = Field(
        default="x",
        description=(
            "Display format:\n"
            "- 'x': hex (default)\n"
            "- 'b': bytes\n"
            "- 's': string\n"
            "- 'i': instructions"
        ),
    )


class DebugMemoryTool(BaseTool[DebugMemoryParams]):
    """Read memory from the debugged process."""

    name: ClassVar[str] = "debug_memory"
    description: ClassVar[str] = (
        "Read memory from the debugged process at a given address. "
        "The program must be stopped at a breakpoint. "
        "Supports hex, byte, string, and instruction display formats."
    )
    param_model: ClassVar[type[BaseModel]] = DebugMemoryParams

    def __init__(self, registry: DebugSessionRegistry) -> None:
        self._registry = registry

    async def execute(self, params: DebugMemoryParams) -> ToolResult:
        try:
            info = self._registry.get(params.session_id)
            if not info:
                return ToolError(output=f"No debug session '{params.session_id}'")

            # Format differs between GDB and LLDB
            if info.debugger_type == DebuggerType.GDB:
                # GDB: x/COUNTformat ADDRESS
                fmt_char = params.format
                if fmt_char == "b":
                    fmt_char = "bx"  # bytes in hex
                cmd = f"x/{params.count}{fmt_char} {params.address}"
            else:
                # LLDB: memory read ADDRESS --count COUNT --format FORMAT
                fmt_map = {
                    "x": "hex",
                    "b": "bytes",
                    "s": "c-string",
                    "i": "instruction",
                }
                lldb_fmt = fmt_map.get(params.format, "hex")
                if params.format == "i":
                    # For instructions, use disassemble instead
                    cmd = f"disassemble --start-address {params.address} --count {params.count}"
                else:
                    cmd = f"memory read {params.address} --count {params.count} --format {lldb_fmt}"

            output = await self._registry.send_command(params.session_id, cmd)
            if not output.strip():
                return ToolError(
                    output="No memory data. Is the program stopped? Is the address valid?",
                    brief="memory read failed",
                )
            return ToolOk(
                output=_xml_wrap(
                    "debug_output",
                    output,
                    session_id=params.session_id,
                    action="memory_read",
                    address=params.address,
                    count=str(params.count),
                    format=params.format,
                ),
                brief=f"memory @ {params.address} ({params.count} {params.format})",
            )
        except Exception as e:
            return ToolError(output=f"Memory read failed: {e}")


# ---------------------------------------------------------------------------
# Tool: debug_backtrace
# ---------------------------------------------------------------------------


class DebugBacktraceParams(BaseModel):
    session_id: str = Field(description="Debug session ID from debug_launch.")
    full: bool = Field(
        default=False,
        description="If true, show full backtrace with local variables (GDB) or all threads (LLDB).",
    )


class DebugBacktraceTool(BaseTool[DebugBacktraceParams]):
    """Get the current stack backtrace."""

    name: ClassVar[str] = "debug_backtrace"
    description: ClassVar[str] = (
        "Get the call stack backtrace at the current stop point. "
        "Shows function names, addresses, and source locations. "
        "The program must be stopped at a breakpoint."
    )
    param_model: ClassVar[type[BaseModel]] = DebugBacktraceParams

    def __init__(self, registry: DebugSessionRegistry) -> None:
        self._registry = registry

    async def execute(self, params: DebugBacktraceParams) -> ToolResult:
        try:
            cmd = "backtrace_full" if params.full else "backtrace"
            output = await self._registry.send_abstract_command(params.session_id, cmd)
            if not output.strip():
                return ToolError(
                    output="No backtrace. Is the program stopped at a breakpoint?",
                    brief="no backtrace",
                )
            return ToolOk(
                output=_xml_wrap(
                    "debug_output",
                    output,
                    session_id=params.session_id,
                    action=cmd,
                ),
                brief="backtrace",
            )
        except Exception as e:
            return ToolError(output=f"Backtrace failed: {e}")


# ---------------------------------------------------------------------------
# Tool: debug_eval
# ---------------------------------------------------------------------------


class DebugEvalParams(BaseModel):
    session_id: str = Field(description="Debug session ID from debug_launch.")
    command: str = Field(
        description=(
            "Raw debugger command to execute. This is sent directly to GDB/LLDB. "
            "Use this for advanced operations not covered by other debug_* tools. "
            "Examples: 'info locals', 'disassemble main', 'print argc', 'watchpoint set variable x'."
        ),
    )


class DebugEvalTool(BaseTool[DebugEvalParams]):
    """Execute a raw debugger command."""

    name: ClassVar[str] = "debug_eval"
    description: ClassVar[str] = (
        "Execute a raw GDB/LLDB command in the debug session. "
        "Use this as a catch-all for advanced operations: printing variables, "
        "watchpoints, disassembling specific regions, modifying memory, etc. "
        "The command is sent directly to the debugger."
    )
    param_model: ClassVar[type[BaseModel]] = DebugEvalParams

    def __init__(self, registry: DebugSessionRegistry) -> None:
        self._registry = registry

    async def execute(self, params: DebugEvalParams) -> ToolResult:
        try:
            output = await self._registry.send_command(
                params.session_id, params.command
            )
            return ToolOk(
                output=_xml_wrap(
                    "debug_output",
                    output or "(no output)",
                    session_id=params.session_id,
                    action="eval",
                    command=params.command,
                ),
                brief=f"eval: {params.command[:50]}",
            )
        except Exception as e:
            return ToolError(output=f"Command failed: {e}")


# ---------------------------------------------------------------------------
# Tool: debug_kill
# ---------------------------------------------------------------------------


class DebugKillParams(BaseModel):
    session_id: str = Field(description="Debug session ID to terminate.")


class DebugKillTool(BaseTool[DebugKillParams]):
    """Terminate a debug session."""

    name: ClassVar[str] = "debug_kill"
    description: ClassVar[str] = (
        "Terminate a running debug session. Kills the debugger and debugged process. "
        "Use when done with a debugging session to free resources."
    )
    param_model: ClassVar[type[BaseModel]] = DebugKillParams

    def __init__(self, registry: DebugSessionRegistry) -> None:
        self._registry = registry

    async def execute(self, params: DebugKillParams) -> ToolResult:
        try:
            info = self._registry.get(params.session_id)
            if not info:
                return ToolError(output=f"No debug session '{params.session_id}'")

            await self._registry.kill(params.session_id)
            return ToolOk(
                output=_xml_wrap(
                    "debug_killed",
                    f"Debug session '{params.session_id}' terminated.",
                    session_id=params.session_id,
                ),
                brief=f"killed {params.session_id}",
            )
        except Exception as e:
            return ToolError(output=f"Failed to kill session: {e}")


# ---------------------------------------------------------------------------
# Tool: debug_sessions
# ---------------------------------------------------------------------------


class DebugSessionsParams(BaseModel):
    pass  # No parameters


class DebugSessionsTool(BaseTool[DebugSessionsParams]):
    """List active debug sessions."""

    name: ClassVar[str] = "debug_sessions"
    description: ClassVar[str] = (
        "List all active debug sessions with their IDs, debugger type, "
        "binary path, and status. Use the session ID from this list "
        "with other debug_* tools."
    )
    param_model: ClassVar[type[BaseModel]] = DebugSessionsParams

    def __init__(self, registry: DebugSessionRegistry) -> None:
        self._registry = registry

    async def execute(self, params: DebugSessionsParams) -> ToolResult:
        sessions = self._registry.list_sessions()
        if not sessions:
            return ToolOk(
                output=_xml_wrap(
                    "debug_sessions",
                    "No active debug sessions. Use debug_launch to start one.",
                    count="0",
                ),
                brief="0 debug sessions",
            )

        lines = [f"{'ID':<12} {'Debugger':<8} {'Alive':<6} {'Binary'}"]
        lines.append("-" * 60)
        for s in sessions:
            lines.append(
                f"{s['id']:<12} {s['debugger']:<8} {'yes' if s['alive'] else 'no':<6} {s['binary']}"
            )

        return ToolOk(
            output=_xml_wrap(
                "debug_sessions",
                "\n".join(lines),
                count=str(len(sessions)),
            ),
            brief=f"{len(sessions)} debug session(s)",
        )


# ---------------------------------------------------------------------------
# Factory: create all debugger tools from a shared registry
# ---------------------------------------------------------------------------


def create_debugger_tools(
    pty_manager: PTYManager,
    cwd: str | None = None,
) -> tuple[DebugSessionRegistry, list[BaseTool]]:
    """Create all debugger tools sharing a single registry.

    Returns:
        Tuple of (registry, list_of_tools). The registry is returned
        so it can be cleaned up on shutdown.
    """
    registry = DebugSessionRegistry(pty_manager)
    tools: list[BaseTool] = [
        DebugLaunchTool(registry, cwd=cwd),
        DebugBreakpointTool(registry),
        DebugContinueTool(registry),
        DebugRegistersTool(registry),
        DebugMemoryTool(registry),
        DebugBacktraceTool(registry),
        DebugEvalTool(registry),
        DebugKillTool(registry),
        DebugSessionsTool(registry),
    ]
    return registry, tools
