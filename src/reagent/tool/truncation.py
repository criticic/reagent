"""Output truncation — bound all tool output before it reaches the LLM."""

from __future__ import annotations

import os
import tempfile

MAX_LINES = 2000
MAX_BYTES = 50 * 1024  # 50KB


def truncate_output(
    text: str,
    max_lines: int = MAX_LINES,
    max_bytes: int = MAX_BYTES,
    save_full: bool = True,
) -> str:
    """Truncate tool output to fit within context budget.

    If the output exceeds limits, the full output is saved to a temp file
    and the truncated version includes a note about where to find it.

    Args:
        text: Raw tool output.
        max_lines: Maximum number of lines to keep.
        max_bytes: Maximum bytes to keep.
        save_full: Whether to save full output to a temp file when truncating.

    Returns:
        Truncated output string.
    """
    if not text:
        return text

    lines = text.split("\n")
    byte_count = len(text.encode("utf-8", errors="replace"))

    needs_truncation = len(lines) > max_lines or byte_count > max_bytes

    if not needs_truncation:
        return text

    # Save full output to temp file
    full_path = None
    if save_full:
        full_path = _save_to_temp(text)

    # Truncate by lines first
    if len(lines) > max_lines:
        # Keep tail (errors tend to be at the end, like pi-mono)
        kept = lines[-max_lines:]
        skipped = len(lines) - max_lines
    else:
        kept = lines
        skipped = 0

    # Then truncate by bytes
    result = "\n".join(kept)
    result_bytes = result.encode("utf-8", errors="replace")
    if len(result_bytes) > max_bytes:
        # Truncate at a safe UTF-8 boundary
        result = result_bytes[:max_bytes].decode("utf-8", errors="ignore")
        skipped_bytes = byte_count - max_bytes
    else:
        skipped_bytes = 0

    # Build truncation notice
    notice_parts = []
    if skipped > 0:
        notice_parts.append(f"{skipped} lines skipped")
    if skipped_bytes > 0:
        notice_parts.append(f"{skipped_bytes} bytes skipped")

    notice = f"[Output truncated: {', '.join(notice_parts)}. Total: {len(lines)} lines, {byte_count} bytes]"
    if full_path:
        notice += f"\n[Full output saved to: {full_path}]"

    return f"{notice}\n{result}"


def _save_to_temp(text: str) -> str:
    """Save full output to a temp file and return the path."""
    os.makedirs(os.path.expanduser("~/.reagent/tool-output"), exist_ok=True)
    fd, path = tempfile.mkstemp(
        prefix="reagent-",
        suffix=".txt",
        dir=os.path.expanduser("~/.reagent/tool-output"),
    )
    with os.fdopen(fd, "w") as f:
        f.write(text)
    return path


def strip_ansi(text: str) -> str:
    """Strip ANSI escape sequences from text."""
    import re

    return re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)


def sanitize_binary_output(text: str) -> str:
    """Remove binary garbage from output.

    Keeps printable chars, tabs, newlines, and carriage returns.
    Strips everything else (control chars, undefined code points, format chars).
    """
    cleaned = []
    for ch in text:
        cp = ord(ch)
        # Keep: printable, tab, newline, carriage return
        if ch in ("\t", "\n", "\r"):
            cleaned.append(ch)
        elif cp >= 32 and cp not in range(0x7F, 0xA0):
            # Skip C0 controls (except above), C1 controls, and format chars
            if cp not in range(0xFFF9, 0xFFFC):
                cleaned.append(ch)
    return "".join(cleaned)
