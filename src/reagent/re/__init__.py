"""RE-specific tools for binary analysis.

Rizin tools (require `rzpipe` and `rizin` binary):
    DisassembleTool, DecompileTool, FunctionsTool, XrefsTool,
    StringsTool, SectionsTool, SearchTool

Debugger tools (require GDB or LLDB):
    DebugLaunchTool, DebugBreakpointTool, DebugContinueTool,
    DebugRegistersTool, DebugMemoryTool, DebugBacktraceTool,
    DebugEvalTool, DebugKillTool, DebugSessionsTool,
    DebugSessionRegistry, create_debugger_tools

File info tool (requires `lief`):
    FileInfoTool
"""

from reagent.re.rizin import (
    DisassembleTool,
    DecompileTool,
    FunctionsTool,
    XrefsTool,
    StringsTool,
    SectionsTool,
    SearchTool,
)
from reagent.re.debugger import (
    DebugLaunchTool,
    DebugBreakpointTool,
    DebugContinueTool,
    DebugRegistersTool,
    DebugMemoryTool,
    DebugBacktraceTool,
    DebugEvalTool,
    DebugKillTool,
    DebugSessionsTool,
    DebugSessionRegistry,
    create_debugger_tools,
)
from reagent.re.file_info import FileInfoTool

__all__ = [
    # Rizin tools
    "DisassembleTool",
    "DecompileTool",
    "FunctionsTool",
    "XrefsTool",
    "StringsTool",
    "SectionsTool",
    "SearchTool",
    # Debugger tools
    "DebugLaunchTool",
    "DebugBreakpointTool",
    "DebugContinueTool",
    "DebugRegistersTool",
    "DebugMemoryTool",
    "DebugBacktraceTool",
    "DebugEvalTool",
    "DebugKillTool",
    "DebugSessionsTool",
    "DebugSessionRegistry",
    "create_debugger_tools",
    # File info
    "FileInfoTool",
]
