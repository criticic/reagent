"""Write file tool."""

from __future__ import annotations

import os
from typing import ClassVar

from pydantic import BaseModel, Field

from reagent.tool.base import BaseTool, ToolOk, ToolError, ToolResult


class WriteFileParams(BaseModel):
    path: str = Field(description="Path to the file to write.")
    content: str = Field(description="Content to write to the file.")


class WriteFileTool(BaseTool[WriteFileParams]):
    """Write content to a file, creating directories as needed."""

    name: ClassVar[str] = "write_file"
    description: ClassVar[str] = (
        "Write content to a file. Creates the file and parent directories if they don't exist. "
        "Overwrites existing content."
    )
    param_model: ClassVar[type[BaseModel]] = WriteFileParams

    def __init__(self, cwd: str | None = None) -> None:
        self._cwd = cwd or os.getcwd()

    async def execute(self, params: WriteFileParams) -> ToolResult:
        path = params.path
        if not os.path.isabs(path):
            path = os.path.join(self._cwd, path)

        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(params.content)

            lines = params.content.count("\n") + 1
            return ToolOk(
                output=f"Wrote {lines} lines to {path}",
                brief=f"Wrote {path}",
            )
        except Exception as e:
            return ToolError(output=f"Error writing file: {e}")
