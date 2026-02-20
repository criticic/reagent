"""Tests for reagent.pty.buffer.RollingBuffer."""

from __future__ import annotations

from reagent.pty.buffer import RollingBuffer


class TestRollingBufferBasics:
    def test_empty(self) -> None:
        buf = RollingBuffer()
        assert buf.line_count == 0
        assert buf.total_lines == 0
        assert buf.read_all() == ""

    def test_append(self) -> None:
        buf = RollingBuffer()
        buf.append("hello")
        buf.append("world")
        assert buf.line_count == 2
        assert buf.total_lines == 2

    def test_append_text(self) -> None:
        buf = RollingBuffer()
        buf.append_text("line1\nline2\nline3")
        assert buf.line_count == 3
        assert buf.total_lines == 3

    def test_append_text_trailing_newline(self) -> None:
        buf = RollingBuffer()
        buf.append_text("line1\nline2\n")
        # Trailing newline creates an empty string after split
        assert buf.line_count == 3

    def test_read_all(self) -> None:
        buf = RollingBuffer()
        buf.append("a")
        buf.append("b")
        buf.append("c")
        assert buf.read_all() == "a\nb\nc"


class TestRollingBufferOverflow:
    def test_maxlen_enforced(self) -> None:
        buf = RollingBuffer(max_lines=5)
        for i in range(10):
            buf.append(f"line {i}")
        assert buf.line_count == 5
        assert buf.total_lines == 10
        # Should have the last 5 lines
        lines = buf.read()
        assert lines == ["line 5", "line 6", "line 7", "line 8", "line 9"]

    def test_overflow_drops_oldest(self) -> None:
        buf = RollingBuffer(max_lines=3)
        buf.append("a")
        buf.append("b")
        buf.append("c")
        buf.append("d")
        lines = buf.read()
        assert "a" not in lines
        assert lines == ["b", "c", "d"]


class TestRollingBufferRead:
    def test_read_with_offset(self) -> None:
        buf = RollingBuffer()
        for i in range(10):
            buf.append(f"line {i}")
        lines = buf.read(offset=5, limit=3)
        assert lines == ["line 5", "line 6", "line 7"]

    def test_read_with_limit(self) -> None:
        buf = RollingBuffer()
        for i in range(10):
            buf.append(f"line {i}")
        lines = buf.read(offset=0, limit=3)
        assert len(lines) == 3
        assert lines[0] == "line 0"

    def test_read_beyond_end(self) -> None:
        buf = RollingBuffer()
        buf.append("only line")
        lines = buf.read(offset=5, limit=10)
        assert lines == []

    def test_read_tail(self) -> None:
        buf = RollingBuffer()
        for i in range(10):
            buf.append(f"line {i}")
        tail = buf.read_tail(3)
        assert tail == ["line 7", "line 8", "line 9"]

    def test_read_tail_more_than_available(self) -> None:
        buf = RollingBuffer()
        buf.append("a")
        buf.append("b")
        tail = buf.read_tail(10)
        assert tail == ["a", "b"]


class TestRollingBufferSearch:
    def test_search_basic(self) -> None:
        buf = RollingBuffer()
        buf.append("error: something failed")
        buf.append("info: all good")
        buf.append("error: another failure")
        results = buf.search("error")
        assert len(results) == 2
        assert results[0][1] == "error: something failed"
        assert results[1][1] == "error: another failure"

    def test_search_regex(self) -> None:
        buf = RollingBuffer()
        buf.append("addr: 0x401000")
        buf.append("addr: 0x402000")
        buf.append("no address here")
        results = buf.search(r"0x[0-9a-f]+")
        assert len(results) == 2

    def test_search_no_matches(self) -> None:
        buf = RollingBuffer()
        buf.append("hello")
        results = buf.search("xyz")
        assert results == []

    def test_search_invalid_regex(self) -> None:
        buf = RollingBuffer()
        buf.append("hello")
        results = buf.search("[invalid")
        assert results == []

    def test_search_limit(self) -> None:
        buf = RollingBuffer()
        for i in range(10):
            buf.append(f"match {i}")
        results = buf.search("match", limit=3)
        assert len(results) == 3


class TestRollingBufferClear:
    def test_clear(self) -> None:
        buf = RollingBuffer()
        for i in range(5):
            buf.append(f"line {i}")
        buf.clear()
        assert buf.line_count == 0
        assert buf.total_lines == 0
        assert buf.read_all() == ""
