"""Tests for reagent.tool.truncation."""

from __future__ import annotations

import os

from reagent.tool.truncation import (
    MAX_BYTES,
    MAX_LINES,
    sanitize_binary_output,
    strip_ansi,
    truncate_output,
)


# ---------------------------------------------------------------------------
# truncate_output
# ---------------------------------------------------------------------------


class TestTruncateOutput:
    def test_empty_string(self) -> None:
        assert truncate_output("") == ""

    def test_within_limits(self) -> None:
        text = "hello\nworld\n"
        assert truncate_output(text) == text

    def test_single_line_within_limits(self) -> None:
        text = "just one line"
        assert truncate_output(text) == text

    def test_over_line_limit(self) -> None:
        lines = [f"line {i}" for i in range(MAX_LINES + 500)]
        text = "\n".join(lines)
        result = truncate_output(text, save_full=False)
        # Should contain truncation notice
        assert "truncated" in result.lower() or "skipped" in result.lower()
        # Should contain some of the lines (tail)
        assert f"line {MAX_LINES + 499}" in result

    def test_over_byte_limit(self) -> None:
        # Create text that's over byte limit but within line limit
        text = "x" * (MAX_BYTES + 1000)
        result = truncate_output(text, save_full=False)
        assert len(result.encode()) <= MAX_BYTES + 500  # Allow header overhead

    def test_save_full_creates_file(self) -> None:
        lines = [f"line {i}" for i in range(MAX_LINES + 100)]
        text = "\n".join(lines)
        result = truncate_output(text, save_full=True)
        # Should mention the temp file path
        assert (
            "reagent" in result.lower()
            or "/tmp" in result.lower()
            or ".reagent" in result.lower()
        )

    def test_save_full_false(self) -> None:
        lines = [f"line {i}" for i in range(MAX_LINES + 100)]
        text = "\n".join(lines)
        result = truncate_output(text, save_full=False)
        # Should still truncate but not mention a file
        assert "truncated" in result.lower() or "skipped" in result.lower()

    def test_custom_limits(self) -> None:
        text = "a\nb\nc\nd\ne\nf\n"
        result = truncate_output(
            text, max_lines=3, max_bytes=MAX_BYTES, save_full=False
        )
        # 7 lines (including trailing empty), limit 3 — should truncate
        assert "d" in result or "e" in result or "f" in result

    def test_exact_line_limit(self) -> None:
        """Exactly at the limit should NOT truncate."""
        lines = [f"line {i}" for i in range(MAX_LINES)]
        text = "\n".join(lines)
        result = truncate_output(text)
        # Should not add truncation header (text is at limit, not over)
        assert result == text


# ---------------------------------------------------------------------------
# strip_ansi
# ---------------------------------------------------------------------------


class TestStripAnsi:
    def test_no_ansi(self) -> None:
        assert strip_ansi("hello world") == "hello world"

    def test_color_codes(self) -> None:
        assert strip_ansi("\x1b[31mred\x1b[0m") == "red"

    def test_bold(self) -> None:
        assert strip_ansi("\x1b[1mbold\x1b[0m") == "bold"

    def test_multiple_codes(self) -> None:
        text = "\x1b[1;31;40mhello\x1b[0m \x1b[32mworld\x1b[0m"
        assert strip_ansi(text) == "hello world"

    def test_cursor_movement(self) -> None:
        assert strip_ansi("\x1b[2Ahello") == "hello"

    def test_empty_string(self) -> None:
        assert strip_ansi("") == ""


# ---------------------------------------------------------------------------
# sanitize_binary_output
# ---------------------------------------------------------------------------


class TestSanitizeBinaryOutput:
    def test_clean_text(self) -> None:
        assert sanitize_binary_output("hello world") == "hello world"

    def test_preserves_tab(self) -> None:
        assert sanitize_binary_output("a\tb") == "a\tb"

    def test_preserves_newline(self) -> None:
        assert sanitize_binary_output("a\nb") == "a\nb"

    def test_preserves_carriage_return(self) -> None:
        assert sanitize_binary_output("a\rb") == "a\rb"

    def test_strips_null(self) -> None:
        assert sanitize_binary_output("a\x00b") == "ab"

    def test_strips_bell(self) -> None:
        assert sanitize_binary_output("a\x07b") == "ab"

    def test_strips_c1_control(self) -> None:
        # 0x7F (DEL) and 0x80-0x9F (C1 controls) should be stripped
        assert sanitize_binary_output("a\x7fb") == "ab"
        assert sanitize_binary_output("a\x80b") == "ab"
        assert sanitize_binary_output("a\x9fb") == "ab"

    def test_keeps_normal_unicode(self) -> None:
        assert sanitize_binary_output("café") == "café"
        assert sanitize_binary_output("日本語") == "日本語"

    def test_strips_format_chars(self) -> None:
        # U+FFF9 through U+FFFB are format characters
        assert sanitize_binary_output("a\ufff9b") == "ab"
        assert sanitize_binary_output("a\ufffab") == "ab"
        assert sanitize_binary_output("a\ufffbb") == "ab"

    def test_empty_string(self) -> None:
        assert sanitize_binary_output("") == ""
