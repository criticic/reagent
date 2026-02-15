"""Rizin-based reverse engineering tools.

All tools share a lazily-opened rzpipe session to avoid repeated binary analysis.
The session is opened once on first use and reused across all tool calls.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, ClassVar

import rzpipe
from pydantic import BaseModel, Field

from reagent.tool.base import BaseTool, ToolError, ToolOk, ToolResult

logger = logging.getLogger(__name__)


class _RzSession:
    """Thread-safe lazy singleton for a shared rzpipe connection.

    Rizin analysis can take seconds; we pay that cost once and reuse the pipe.
    """

    def __init__(self, binary_path: str) -> None:
        self._binary_path = binary_path
        self._pipe: rzpipe.open | None = None
        self._lock = threading.Lock()
        self._analyzed = False

    @property
    def pipe(self) -> rzpipe.open:
        with self._lock:
            if self._pipe is None:
                logger.info("Opening rizin session for %s", self._binary_path)
                self._pipe = rzpipe.open(
                    self._binary_path, flags=["-2"]
                )  # -2 = no stderr
                # Run initial analysis
                self._pipe.cmd("aaa")  # Full analysis
                self._analyzed = True
                logger.info("Rizin analysis complete for %s", self._binary_path)
            return self._pipe

    def cmd(self, command: str) -> str:
        """Run a rizin command and return string output."""
        result = self.pipe.cmd(command)
        return result if result else ""

    def cmdj(self, command: str) -> Any:
        """Run a rizin command and return parsed JSON."""
        try:
            result = self.pipe.cmdj(command)
            return result if result else None
        except (json.JSONDecodeError, Exception):
            # Fall back to string output if JSON parsing fails
            return None

    def close(self) -> None:
        with self._lock:
            if self._pipe is not None:
                try:
                    self._pipe.quit()
                except Exception:
                    pass
                self._pipe = None
                self._analyzed = False


# Global session cache: binary_path -> _RzSession
_sessions: dict[str, _RzSession] = {}
_sessions_lock = threading.Lock()


def _get_session(binary_path: str) -> _RzSession:
    """Get or create a shared session for the given binary."""
    with _sessions_lock:
        if binary_path not in _sessions:
            _sessions[binary_path] = _RzSession(binary_path)
        return _sessions[binary_path]


# ---------------------------------------------------------------------------
# Tool: disassemble
# ---------------------------------------------------------------------------


class DisassembleParams(BaseModel):
    address: str | None = Field(
        default=None,
        description=(
            "Address or function name to disassemble. "
            "Examples: '0x08048000', 'main', 'sym.check_password'. "
            "If omitted, disassembles the current location (usually entry point)."
        ),
    )
    count: int = Field(
        default=64,
        description="Number of instructions to disassemble (default 64).",
    )


class DisassembleTool(BaseTool[DisassembleParams]):
    """Disassemble instructions at a given address or function."""

    name: ClassVar[str] = "disassemble"
    description: ClassVar[str] = (
        "Disassemble instructions at an address or function name. "
        "Returns annotated assembly with addresses, opcodes, and comments. "
        "Use function names like 'main' or 'sym.check_password', or hex addresses like '0x401000'."
    )
    param_model: ClassVar[type[BaseModel]] = DisassembleParams

    def __init__(self, binary_path: str) -> None:
        self._session = _get_session(binary_path)

    async def execute(self, params: DisassembleParams) -> ToolResult:
        try:
            if params.address:
                self._session.cmd(f"s {params.address}")

            result = self._session.cmd(f"pd {params.count}")
            if not result.strip():
                return ToolError(
                    output=f"No instructions at address {params.address or 'current'}",
                    brief=f"disasm: nothing at {params.address or 'current'}",
                )

            addr = params.address or "current"
            return ToolOk(
                output=result,
                brief=f"disasm {params.count} insns @ {addr}",
            )
        except Exception as e:
            return ToolError(output=f"Disassembly failed: {e}")


# ---------------------------------------------------------------------------
# Tool: decompile
# ---------------------------------------------------------------------------


class DecompileParams(BaseModel):
    function: str = Field(
        description=(
            "Function to decompile. Can be a name like 'main', 'sym.check_password', "
            "or an address like '0x401000'."
        ),
    )


class DecompileTool(BaseTool[DecompileParams]):
    """Decompile a function to pseudo-C using rizin's built-in decompiler."""

    name: ClassVar[str] = "decompile"
    description: ClassVar[str] = (
        "Decompile a function to pseudo-C code. Uses rizin's built-in decompiler "
        "(or r2ghidra plugin if available). Provide a function name or address. "
        "This gives a higher-level view than raw disassembly."
    )
    param_model: ClassVar[type[BaseModel]] = DecompileParams

    def __init__(self, binary_path: str) -> None:
        self._session = _get_session(binary_path)

    async def execute(self, params: DecompileParams) -> ToolResult:
        try:
            self._session.cmd(f"s {params.function}")

            # Try decompilers in order of preference:
            # 1. pdg  — r2ghidra plugin (best quality)
            # 2. pdc  — rz-dec built-in decompiler
            # 3. pds  — function summary (calls, strings, jumps) as last resort
            decompilers = [
                ("pdg", "r2ghidra"),
                ("pdc", "rz-dec"),
            ]

            for cmd, source in decompilers:
                result = self._session.cmd(cmd)
                stripped = result.strip()
                if not stripped:
                    continue
                # Check for actual error messages (not "error" appearing in
                # decompiled code like function names e.g. sym.imp.ferror).
                # Real failures produce short messages starting with these.
                first_line = stripped.split("\n", 1)[0].lower()
                is_error = first_line.startswith("cannot") or (
                    first_line.startswith("error") and len(stripped) < 200
                )
                if not is_error:
                    return ToolOk(
                        output=f"// Decompiled with {source}\n{result}",
                        brief=f"decompiled {params.function}",
                    )

            # Last resort: function summary (always available)
            summary = self._session.cmd("pdsf")
            if summary.strip():
                # Also get the full function disassembly as fallback
                pdf_result = self._session.cmd("pdf")
                output_parts = [
                    f"// No decompiler plugin available (install r2ghidra for best results)",
                    f"// Showing function summary + annotated disassembly for '{params.function}'",
                    "",
                    "== Function Summary (calls, strings, references) ==",
                    summary,
                ]
                if pdf_result.strip():
                    output_parts.extend(
                        [
                            "",
                            "== Full Annotated Disassembly ==",
                            pdf_result,
                        ]
                    )
                return ToolOk(
                    output="\n".join(output_parts),
                    brief=f"summary+disasm {params.function} (no decompiler)",
                )

            return ToolError(
                output=f"Could not decompile function '{params.function}'. "
                "No decompiler plugin is available and the function may not be valid. "
                "Install r2ghidra ('rizin -H RZ_USER_PLUGINS' + build rz-ghidra) for decompilation. "
                "Try using `functions` to list valid function names, "
                "or `disassemble` to view raw assembly.",
                brief=f"decompile failed: {params.function}",
            )
        except Exception as e:
            return ToolError(output=f"Decompilation failed: {e}")


# ---------------------------------------------------------------------------
# Tool: functions
# ---------------------------------------------------------------------------


class FunctionsParams(BaseModel):
    filter: str | None = Field(
        default=None,
        description=(
            "Optional substring filter for function names. "
            "Examples: 'main', 'check', 'password', 'sym.imp'. "
            "If omitted, lists all functions."
        ),
    )


class FunctionsTool(BaseTool[FunctionsParams]):
    """List functions discovered by rizin analysis."""

    name: ClassVar[str] = "functions"
    description: ClassVar[str] = (
        "List functions found in the binary by rizin's analysis. "
        "Returns function name, address, size, and type. "
        "Use the optional filter to search for specific function names."
    )
    param_model: ClassVar[type[BaseModel]] = FunctionsParams

    def __init__(self, binary_path: str) -> None:
        self._session = _get_session(binary_path)

    async def execute(self, params: FunctionsParams) -> ToolResult:
        try:
            funcs = self._session.cmdj("aflj")
            if not funcs:
                return ToolError(
                    output="No functions found. The binary may not have been analyzed.",
                    brief="no functions found",
                )

            if params.filter:
                needle = params.filter.lower()
                funcs = [f for f in funcs if needle in f.get("name", "").lower()]
                if not funcs:
                    return ToolOk(
                        output=f"No functions matching '{params.filter}'.",
                        brief=f"0 functions matching '{params.filter}'",
                    )

            # Format as a readable table
            lines = [f"{'Address':<14} {'Size':>6} {'Name'}"]
            lines.append("-" * 60)
            for f in funcs:
                addr = f"0x{f.get('offset', 0):08x}"
                size = f.get("size", 0)
                name = f.get("name", "unknown")
                lines.append(f"{addr:<14} {size:>6} {name}")

            output = "\n".join(lines)
            count = len(funcs)
            qualifier = f" matching '{params.filter}'" if params.filter else ""
            return ToolOk(
                output=output,
                brief=f"{count} functions{qualifier}",
            )
        except Exception as e:
            return ToolError(output=f"Failed to list functions: {e}")


# ---------------------------------------------------------------------------
# Tool: xrefs
# ---------------------------------------------------------------------------


class XrefsParams(BaseModel):
    target: str = Field(
        description=(
            "Address or function name to find cross-references for. "
            "Examples: 'main', 'sym.check_password', '0x401000'."
        ),
    )
    direction: str = Field(
        default="to",
        description=(
            "'to' = who calls/references this address (default), "
            "'from' = what does this address call/reference."
        ),
    )


class XrefsTool(BaseTool[XrefsParams]):
    """Find cross-references to or from an address."""

    name: ClassVar[str] = "xrefs"
    description: ClassVar[str] = (
        "Find cross-references (xrefs) to or from a function/address. "
        "Direction 'to' shows callers (who references this). "
        "Direction 'from' shows callees (what this references). "
        "Useful for tracing control flow and finding how functions are used."
    )
    param_model: ClassVar[type[BaseModel]] = XrefsParams

    def __init__(self, binary_path: str) -> None:
        self._session = _get_session(binary_path)

    async def execute(self, params: XrefsParams) -> ToolResult:
        try:
            self._session.cmd(f"s {params.target}")

            if params.direction == "from":
                xrefs = self._session.cmdj("axfj")
                direction_label = "from"
            else:
                xrefs = self._session.cmdj("axtj")
                direction_label = "to"

            if not xrefs:
                return ToolOk(
                    output=f"No xrefs {direction_label} {params.target}.",
                    brief=f"0 xrefs {direction_label} {params.target}",
                )

            lines = [f"Cross-references {direction_label} {params.target}:", ""]
            for x in xrefs:
                addr = f"0x{x.get('from', x.get('addr', 0)):08x}"
                ref_type = x.get("type", "?")
                # Try to get the function name at the xref source
                fcn = x.get("fcn_name", x.get("name", ""))
                opcode = x.get("opcode", "")
                line = f"  {addr}  [{ref_type}]"
                if fcn:
                    line += f"  in {fcn}"
                if opcode:
                    line += f"  ({opcode})"
                lines.append(line)

            return ToolOk(
                output="\n".join(lines),
                brief=f"{len(xrefs)} xrefs {direction_label} {params.target}",
            )
        except Exception as e:
            return ToolError(output=f"Failed to get xrefs: {e}")


# ---------------------------------------------------------------------------
# Tool: strings
# ---------------------------------------------------------------------------


class StringsParams(BaseModel):
    filter: str | None = Field(
        default=None,
        description=(
            "Optional substring filter for strings. "
            "Examples: 'password', 'error', 'flag{'. "
            "If omitted, lists all strings found in the binary."
        ),
    )
    min_length: int = Field(
        default=4,
        description="Minimum string length to include (default 4).",
    )


class StringsTool(BaseTool[StringsParams]):
    """List strings found in the binary."""

    name: ClassVar[str] = "strings"
    description: ClassVar[str] = (
        "List strings found in the binary's data sections. "
        "Strings often reveal important information: error messages, URLs, "
        "file paths, encryption keys, format strings, debug info. "
        "Use the filter parameter to search for specific content."
    )
    param_model: ClassVar[type[BaseModel]] = StringsParams

    def __init__(self, binary_path: str) -> None:
        self._session = _get_session(binary_path)

    async def execute(self, params: StringsParams) -> ToolResult:
        try:
            strings = self._session.cmdj("izj")
            if not strings:
                return ToolOk(
                    output="No strings found in the binary.",
                    brief="0 strings",
                )

            # Filter by length
            strings = [
                s for s in strings if len(s.get("string", "")) >= params.min_length
            ]

            # Filter by substring
            if params.filter:
                needle = params.filter.lower()
                strings = [s for s in strings if needle in s.get("string", "").lower()]

            if not strings:
                qualifier = f" matching '{params.filter}'" if params.filter else ""
                return ToolOk(
                    output=f"No strings{qualifier} (min length {params.min_length}).",
                    brief=f"0 strings{qualifier}",
                )

            lines = [f"{'Address':<14} {'Section':<12} {'String'}"]
            lines.append("-" * 70)
            for s in strings:
                addr = f"0x{s.get('vaddr', s.get('paddr', 0)):08x}"
                section = s.get("section", "?")
                string = s.get("string", "")
                # Escape any control characters for clean display
                string = (
                    string.replace("\n", "\\n")
                    .replace("\r", "\\r")
                    .replace("\t", "\\t")
                )
                lines.append(f"{addr:<14} {section:<12} {string}")

            count = len(strings)
            qualifier = f" matching '{params.filter}'" if params.filter else ""
            return ToolOk(
                output="\n".join(lines),
                brief=f"{count} strings{qualifier}",
            )
        except Exception as e:
            return ToolError(output=f"Failed to list strings: {e}")


# ---------------------------------------------------------------------------
# Tool: sections
# ---------------------------------------------------------------------------


class SectionsParams(BaseModel):
    pass  # No parameters needed


class SectionsTool(BaseTool[SectionsParams]):
    """List binary sections/segments with their properties."""

    name: ClassVar[str] = "sections"
    description: ClassVar[str] = (
        "List all sections/segments in the binary with their addresses, sizes, "
        "permissions, and names. Useful for understanding memory layout and "
        "identifying code vs data regions."
    )
    param_model: ClassVar[type[BaseModel]] = SectionsParams

    def __init__(self, binary_path: str) -> None:
        self._session = _get_session(binary_path)

    async def execute(self, params: SectionsParams) -> ToolResult:
        try:
            sections = self._session.cmdj("iSj")
            if not sections:
                return ToolOk(
                    output="No sections found.",
                    brief="0 sections",
                )

            lines = [f"{'VAddr':<14} {'Size':>8} {'Perm':<5} {'Name'}"]
            lines.append("-" * 55)
            for s in sections:
                vaddr = f"0x{s.get('vaddr', 0):08x}"
                size = s.get("vsize", s.get("size", 0))
                perm = s.get("perm", "---")
                if perm is None:
                    perm = "---"
                name = s.get("name", "?")
                lines.append(f"{vaddr:<14} {size:>8} {perm:<5} {name}")

            return ToolOk(
                output="\n".join(lines),
                brief=f"{len(sections)} sections",
            )
        except Exception as e:
            return ToolError(output=f"Failed to list sections: {e}")


# ---------------------------------------------------------------------------
# Tool: search
# ---------------------------------------------------------------------------


class SearchParams(BaseModel):
    pattern: str = Field(
        description=(
            "Pattern to search for. Interpreted based on 'mode'. "
            "For 'string': a text string. "
            "For 'hex': hex bytes like 'deadbeef' or '90 90 90'. "
            "For 'rop': a ROP gadget pattern like 'pop rdi; ret'."
        ),
    )
    mode: str = Field(
        default="string",
        description="Search mode: 'string', 'hex', or 'rop' (default 'string').",
    )


class SearchTool(BaseTool[SearchParams]):
    """Search for patterns in the binary."""

    name: ClassVar[str] = "search"
    description: ClassVar[str] = (
        "Search the binary for strings, hex byte patterns, or ROP gadgets. "
        "Returns matching addresses and context. "
        "Useful for finding specific constants, magic bytes, or exploit primitives."
    )
    param_model: ClassVar[type[BaseModel]] = SearchParams

    def __init__(self, binary_path: str) -> None:
        self._session = _get_session(binary_path)

    async def execute(self, params: SearchParams) -> ToolResult:
        try:
            if params.mode == "hex":
                # Normalize hex input: remove spaces
                hex_pattern = params.pattern.replace(" ", "")
                result = self._session.cmd(f"/x {hex_pattern}")
            elif params.mode == "rop":
                result = self._session.cmd(f"/R {params.pattern}")
            else:  # string
                result = self._session.cmd(f"/ {params.pattern}")

            if not result.strip():
                return ToolOk(
                    output=f"No matches for {params.mode} pattern '{params.pattern}'.",
                    brief=f"0 matches for '{params.pattern}'",
                )

            # Count matches
            match_lines = [
                l for l in result.strip().split("\n") if l.strip() and "0x" in l
            ]
            count = len(match_lines)

            return ToolOk(
                output=result,
                brief=f"{count} matches for '{params.pattern}'",
            )
        except Exception as e:
            return ToolError(output=f"Search failed: {e}")
