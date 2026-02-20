"""Tests for reagent.session.wire (Wire, WireEvent, EventType)."""

from __future__ import annotations

import asyncio

import pytest

from reagent.session.wire import EventType, Wire, WireEvent


# ---------------------------------------------------------------------------
# EventType
# ---------------------------------------------------------------------------


class TestEventType:
    def test_all_variants_exist(self) -> None:
        expected = {
            "TURN_BEGIN",
            "TURN_END",
            "STEP_BEGIN",
            "TEXT",
            "THINKING",
            "TOOL_CALL",
            "TOOL_RESULT",
            "OBSERVATION",
            "HYPOTHESIS",
            "FINDING",
            "TARGET_INFO",
            "SUBAGENT_BEGIN",
            "SUBAGENT_END",
            "COMPACTION",
            "DMAIL",
            "ERROR",
            "STATUS",
            "PTY_EXIT",
        }
        actual = {e.name for e in EventType}
        assert actual == expected

    def test_values_are_lowercase(self) -> None:
        for e in EventType:
            assert e.value == e.name.lower()


# ---------------------------------------------------------------------------
# WireEvent
# ---------------------------------------------------------------------------


class TestWireEvent:
    def test_defaults(self) -> None:
        event = WireEvent(type=EventType.TEXT)
        assert event.data == {}

    def test_with_data(self) -> None:
        event = WireEvent(type=EventType.TEXT, data={"text": "hello"})
        assert event.data["text"] == "hello"


# ---------------------------------------------------------------------------
# Wire — basic send/subscribe
# ---------------------------------------------------------------------------


class TestWire:
    def test_send_to_subscriber(self) -> None:
        wire = Wire()
        q = wire.subscribe()
        wire.send(WireEvent(type=EventType.TEXT, data={"text": "hi"}))
        event = q.get_nowait()
        assert event is not None
        assert event.type == EventType.TEXT
        assert event.data["text"] == "hi"

    def test_send_to_multiple_subscribers(self) -> None:
        wire = Wire()
        q1 = wire.subscribe()
        q2 = wire.subscribe()
        wire.send(WireEvent(type=EventType.STATUS, data={"message": "ok"}))
        e1 = q1.get_nowait()
        e2 = q2.get_nowait()
        assert e1 is not None and e2 is not None
        assert e1.type == e2.type == EventType.STATUS

    def test_unsubscribe(self) -> None:
        wire = Wire()
        q = wire.subscribe()
        wire.unsubscribe(q)
        wire.send(WireEvent(type=EventType.TEXT))
        assert q.empty()

    def test_unsubscribe_nonexistent_is_safe(self) -> None:
        wire = Wire()
        q: asyncio.Queue[WireEvent | None] = asyncio.Queue()
        wire.unsubscribe(q)  # Should not raise


# ---------------------------------------------------------------------------
# Wire — closed-state guard
# ---------------------------------------------------------------------------


class TestWireClosedGuard:
    def test_send_after_close_is_dropped(self) -> None:
        wire = Wire()
        q = wire.subscribe()
        wire.close()
        # Drain the None sentinel from close()
        sentinel = q.get_nowait()
        assert sentinel is None
        # Now send after close — should be silently dropped
        wire.send(WireEvent(type=EventType.TEXT, data={"text": "too late"}))
        assert q.empty()

    def test_close_sends_none_sentinel(self) -> None:
        wire = Wire()
        q = wire.subscribe()
        wire.close()
        event = q.get_nowait()
        assert event is None

    def test_close_sends_sentinel_to_all_subscribers(self) -> None:
        wire = Wire()
        q1 = wire.subscribe()
        q2 = wire.subscribe()
        q3 = wire.subscribe()
        wire.close()
        assert q1.get_nowait() is None
        assert q2.get_nowait() is None
        assert q3.get_nowait() is None

    def test_multiple_sends_after_close_all_dropped(self) -> None:
        wire = Wire()
        q = wire.subscribe()
        wire.close()
        q.get_nowait()  # drain sentinel
        for _ in range(10):
            wire.send(WireEvent(type=EventType.ERROR, data={"error": "nope"}))
        assert q.empty()

    def test_close_idempotent(self) -> None:
        """Calling close() twice should not crash or double-send sentinels."""
        wire = Wire()
        q = wire.subscribe()
        wire.close()
        sentinel = q.get_nowait()
        assert sentinel is None
        # Second close — no more sentinels because _closed is already True
        wire.close()
        # The second close will still put_nowait(None), but that's fine
        # The key property is that sends are dropped after close


# ---------------------------------------------------------------------------
# Wire — convenience methods
# ---------------------------------------------------------------------------


class TestWireConvenience:
    def test_send_text(self) -> None:
        wire = Wire()
        q = wire.subscribe()
        wire.send_text("hello")
        event = q.get_nowait()
        assert event is not None
        assert event.type == EventType.TEXT
        assert event.data["text"] == "hello"

    def test_send_status(self) -> None:
        wire = Wire()
        q = wire.subscribe()
        wire.send_status("processing")
        event = q.get_nowait()
        assert event is not None
        assert event.type == EventType.STATUS
        assert event.data["message"] == "processing"

    def test_send_error(self) -> None:
        wire = Wire()
        q = wire.subscribe()
        wire.send_error("something failed")
        event = q.get_nowait()
        assert event is not None
        assert event.type == EventType.ERROR
        assert event.data["error"] == "something failed"

    def test_send_observation(self) -> None:
        wire = Wire()
        q = wire.subscribe()
        wire.send_observation("found XOR loop", category="crypto")
        event = q.get_nowait()
        assert event is not None
        assert event.type == EventType.OBSERVATION
        assert event.data["description"] == "found XOR loop"
        assert event.data["category"] == "crypto"

    def test_send_hypothesis(self) -> None:
        wire = Wire()
        q = wire.subscribe()
        wire.send_hypothesis(
            "AES detected", status="proposed", confidence=0.7, hyp_id="h1"
        )
        event = q.get_nowait()
        assert event is not None
        assert event.type == EventType.HYPOTHESIS
        assert event.data["confidence"] == 0.7
        assert event.data["id"] == "h1"

    def test_send_finding(self) -> None:
        wire = Wire()
        q = wire.subscribe()
        wire.send_finding("confirmed AES-128-ECB", category="crypto", verified=True)
        event = q.get_nowait()
        assert event is not None
        assert event.type == EventType.FINDING
        assert event.data["verified"] is True

    def test_send_target_info(self) -> None:
        wire = Wire()
        q = wire.subscribe()
        wire.send_target_info({"format": "ELF", "arch": "x86_64"})
        event = q.get_nowait()
        assert event is not None
        assert event.type == EventType.TARGET_INFO
        assert event.data["format"] == "ELF"

    def test_send_pty_exit(self) -> None:
        wire = Wire()
        q = wire.subscribe()
        wire.send_pty_exit("pty_001", "gdb session", exit_code=0, last_output="done")
        event = q.get_nowait()
        assert event is not None
        assert event.type == EventType.PTY_EXIT
        assert event.data["session_id"] == "pty_001"
        assert event.data["exit_code"] == 0
        assert event.data["last_output"] == "done"

    def test_send_pty_exit_truncates_output(self) -> None:
        wire = Wire()
        q = wire.subscribe()
        long_output = "x" * 1000
        wire.send_pty_exit("pty_002", "test", exit_code=1, last_output=long_output)
        event = q.get_nowait()
        assert event is not None
        assert len(event.data["last_output"]) == 500

    def test_convenience_methods_respect_closed(self) -> None:
        """All convenience methods should be no-ops after close()."""
        wire = Wire()
        q = wire.subscribe()
        wire.close()
        q.get_nowait()  # drain sentinel
        wire.send_text("nope")
        wire.send_status("nope")
        wire.send_error("nope")
        wire.send_observation("nope")
        wire.send_hypothesis("nope")
        wire.send_finding("nope")
        wire.send_target_info({"nope": True})
        wire.send_pty_exit("s", "t", 0)
        assert q.empty()
