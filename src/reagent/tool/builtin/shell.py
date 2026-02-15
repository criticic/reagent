"""Shell tool — execute commands in a subprocess."""

from __future__ import annotations

import asyncio
import os
import signal
from typing import ClassVar

from pydantic import BaseModel, Field

from reagent.tool.base import BaseTool, ToolOk, ToolError, ToolResult
from reagent.tool.truncation import strip_ansi, sanitize_binary_output


class ShellParams(BaseModel):
    command: str = Field(description="The shell command to execute.")
    timeout: int = Field(default=120, description="Timeout in seconds.")
    workdir: str | None = Field(
        default=None, description="Working directory. Defaults to project root."
    )


class ShellTool(BaseTool[ShellParams]):
    """Execute shell commands with process group isolation and output sanitization."""

    name: ClassVar[str] = "shell"
    description: ClassVar[str] = (
        "Execute a shell command. Output is captured and returned. "
        "Commands run in a process group for safe cleanup. "
        "Use for running analysis tools, compiling, file operations, etc."
    )
    param_model: ClassVar[type[BaseModel]] = ShellParams

    def __init__(self, cwd: str | None = None) -> None:
        self._cwd = cwd or os.getcwd()

    async def execute(self, params: ShellParams) -> ToolResult:
        workdir = params.workdir or self._cwd
        if not os.path.isdir(workdir):
            return ToolError(output=f"Directory does not exist: {workdir}")

        try:
            process = await asyncio.create_subprocess_shell(
                params.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=workdir,
                preexec_fn=os.setpgrp,  # New process group
                env={**os.environ, "TERM": "dumb"},  # Reduce ANSI output
            )

            try:
                stdout, _ = await asyncio.wait_for(
                    process.communicate(),
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
