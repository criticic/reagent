"""Read file tool."""

from __future__ import annotations

import os
from typing import ClassVar

from pydantic import BaseModel, Field

from reagent.tool.base import BaseTool, ToolOk, ToolError, ToolResult


class ReadFileParams(BaseModel):
    path: str = Field(description="Absolute or relative path to the file to read.")
    offset: int = Field(
        default=0, description="Line number to start reading from (0-indexed)."
    )
    limit: int = Field(default=2000, description="Maximum number of lines to read.")


class ReadFileTool(BaseTool[ReadFileParams]):
    """Read file contents with optional offset and limit."""

    name: ClassVar[str] = "read_file"
    description: ClassVar[str] = (
        "Read the contents of a file. Returns numbered lines. "
        "Use offset and limit for large files."
    )
    param_model: ClassVar[type[BaseModel]] = ReadFileParams

    def __init__(self, cwd: str | None = None) -> None:
        self._cwd = cwd or os.getcwd()

    async def execute(self, params: ReadFileParams) -> ToolResult:
        path = params.path
        if not os.path.isabs(path):
            path = os.path.join(self._cwd, path)

        if not os.path.exists(path):
            return ToolError(output=f"File not found: {path}")

        if os.path.isdir(path):
            try:
                entries = sorted(os.listdir(path))
                formatted = []
                for e in entries:
                    full = os.path.join(path, e)
                    suffix = "/" if os.path.isdir(full) else ""
                    formatted.append(f"{e}{suffix}")
                return ToolOk(
                    output="\n".join(formatted),
                    brief=f"Listed {len(entries)} entries in {os.path.basename(path)}",
                )
            except PermissionError:
                return ToolError(output=f"Permission denied: {path}")

        try:
            with open(path, "r", errors="replace") as f:
                all_lines = f.readlines()
        except PermissionError:
            return ToolError(output=f"Permission denied: {path}")
        except Exception as e:
            return ToolError(output=f"Error reading file: {e}")

        total = len(all_lines)
        start = min(params.offset, total)
        end = min(start + params.limit, total)
        selected = all_lines[start:end]

        numbered = []
        for i, line in enumerate(selected, start=start + 1):
            numbered.append(f"{i}: {line.rstrip()}")

        result = "\n".join(numbered)
        if end < total:
            result += f"\n\n[{total - end} more lines. Use offset={end} to continue.]"

        return ToolOk(
            output=result,
            brief=f"Read {path} ({end - start}/{total} lines)",
        )
