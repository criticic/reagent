"""Tests for reagent.re.debugger (DebuggerType, command maps, helpers)."""

from __future__ import annotations

import enum

from reagent.re.debugger import DebuggerType, _CMD_MAP, _PROMPT_PATTERNS, _xml_wrap


# ---------------------------------------------------------------------------
# DebuggerType StrEnum
# ---------------------------------------------------------------------------


class TestDebuggerType:
    def test_is_str_enum(self) -> None:
        assert issubclass(DebuggerType, enum.StrEnum)

    def test_values(self) -> None:
        assert DebuggerType.GDB == "gdb"
        assert DebuggerType.LLDB == "lldb"

    def test_string_comparison(self) -> None:
        """StrEnum values can be compared directly with strings."""
        assert DebuggerType.GDB == "gdb"
        assert DebuggerType.LLDB == "lldb"
        assert "gdb" == DebuggerType.GDB

    def test_str_conversion(self) -> None:
        assert str(DebuggerType.GDB) == "gdb"
        assert str(DebuggerType.LLDB) == "lldb"

    def test_enum_iteration(self) -> None:
        members = list(DebuggerType)
        assert len(members) == 2
        assert DebuggerType.GDB in members
        assert DebuggerType.LLDB in members

    def test_from_string(self) -> None:
        """Can construct from string value."""
        assert DebuggerType("gdb") is DebuggerType.GDB
        assert DebuggerType("lldb") is DebuggerType.LLDB

    def test_invalid_value_raises(self) -> None:
        import pytest

        with pytest.raises(ValueError):
            DebuggerType("radare2")

    def test_membership_check(self) -> None:
        """Can use 'in' with string values."""
        assert (
            "gdb" in DebuggerType.__members__.values()
            or DebuggerType("gdb") in DebuggerType
        )


# ---------------------------------------------------------------------------
# _PROMPT_PATTERNS
# ---------------------------------------------------------------------------


class TestPromptPatterns:
    def test_keys_are_debugger_types(self) -> None:
        for key in _PROMPT_PATTERNS:
            assert isinstance(key, DebuggerType)

    def test_gdb_pattern(self) -> None:
        import re

        pattern = re.compile(_PROMPT_PATTERNS[DebuggerType.GDB])
        assert pattern.search("(gdb) ")
        assert not pattern.search("(lldb) ")

    def test_lldb_pattern(self) -> None:
        import re

        pattern = re.compile(_PROMPT_PATTERNS[DebuggerType.LLDB])
        assert pattern.search("(lldb) ")
        assert not pattern.search("(gdb) ")


# ---------------------------------------------------------------------------
# _CMD_MAP
# ---------------------------------------------------------------------------


class TestCmdMap:
    def test_keys_are_debugger_types(self) -> None:
        for key in _CMD_MAP:
            assert isinstance(key, DebuggerType)

    def test_gdb_commands_present(self) -> None:
        gdb_cmds = _CMD_MAP[DebuggerType.GDB]
        assert "run" in gdb_cmds
        assert "continue" in gdb_cmds
        assert "breakpoint" in gdb_cmds
        assert "registers" in gdb_cmds
        assert "quit" in gdb_cmds

    def test_lldb_commands_present(self) -> None:
        lldb_cmds = _CMD_MAP[DebuggerType.LLDB]
        assert "run" in lldb_cmds
        assert "continue" in lldb_cmds
        assert "breakpoint" in lldb_cmds
        assert "registers" in lldb_cmds
        assert "quit" in lldb_cmds

    def test_gdb_lldb_same_abstract_commands(self) -> None:
        """Both debuggers should support the same abstract command set."""
        gdb_keys = set(_CMD_MAP[DebuggerType.GDB].keys())
        lldb_keys = set(_CMD_MAP[DebuggerType.LLDB].keys())
        # LLDB has an extra 'breakpoint_addr' command
        assert gdb_keys.issubset(lldb_keys)

    def test_gdb_breakpoint_format(self) -> None:
        template = _CMD_MAP[DebuggerType.GDB]["breakpoint"]
        result = template.format(location="main")
        assert result == "break main"

    def test_lldb_breakpoint_format(self) -> None:
        template = _CMD_MAP[DebuggerType.LLDB]["breakpoint"]
        result = template.format(location="main")
        assert result == "breakpoint set --name main"


# ---------------------------------------------------------------------------
# _xml_wrap
# ---------------------------------------------------------------------------


class TestXmlWrap:
    def test_basic_wrap(self) -> None:
        result = _xml_wrap("tag", "content")
        assert result == "<tag>\ncontent\n</tag>"

    def test_with_attributes(self) -> None:
        result = _xml_wrap("debug_output", "data", session_id="s1", action="step")
        assert 'session_id="s1"' in result
        assert 'action="step"' in result
        assert result.startswith("<debug_output")
        assert result.endswith("</debug_output>")
        assert "\ndata\n" in result

    def test_empty_content(self) -> None:
        result = _xml_wrap("empty", "")
        assert result == "<empty>\n\n</empty>"

    def test_multiline_content(self) -> None:
        content = "line1\nline2\nline3"
        result = _xml_wrap("output", content)
        assert f"<output>\n{content}\n</output>" == result
