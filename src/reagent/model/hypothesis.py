"""Hypothesis, Observation, and Finding data types."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal


def _gen_id() -> str:
    return uuid.uuid4().hex[:8]


@dataclass
class Observation:
    """Raw data observed during analysis.

    Observations are facts: disassembly output, hex dumps, string extractions,
    memory dumps, register values, etc. They don't carry interpretation.
    """

    id: str = field(default_factory=_gen_id)
    type: str = ""  # "disassembly", "strings", "hex", "trace", "memory", "info"
    source: str = ""  # which agent/tool produced this
    address: int | None = None
    data: str = ""  # the raw observation
    timestamp: float = field(default_factory=time.time)


@dataclass
class Hypothesis:
    """An interpretive claim about the binary.

    Hypotheses are proposed by agents and need verification.
    Example: "Function sub_401230 is an AES-128-ECB encryption routine"
    """

    id: str = field(default_factory=_gen_id)
    description: str = ""
    category: str = ""  # "crypto", "auth", "c2", "anti-debug", "vuln", "protocol"
    confidence: float = 0.5  # 0.0 - 1.0
    evidence: list[str] = field(default_factory=list)  # observation IDs
    status: Literal["proposed", "testing", "confirmed", "rejected"] = "proposed"
    proposed_by: str = ""  # agent name
    verified_by: str | None = None
    address: int | None = None  # primary address this hypothesis relates to

    def confirm(self, agent: str, additional_evidence: list[str] | None = None) -> None:
        """Mark this hypothesis as confirmed."""
        self.status = "confirmed"
        self.verified_by = agent
        self.confidence = 1.0
        if additional_evidence:
            self.evidence.extend(additional_evidence)

    def reject(self, agent: str, reason: str = "") -> None:
        """Mark this hypothesis as rejected."""
        self.status = "rejected"
        self.verified_by = agent
        self.confidence = 0.0


@dataclass
class Finding:
    """A verified, confirmed fact about the binary.

    Findings are the final output of analysis — promoted from confirmed hypotheses
    or directly established through definitive evidence.
    """

    id: str = field(default_factory=_gen_id)
    description: str = ""
    category: str = ""  # "crypto", "auth", "c2", "anti-debug", "vuln", "protocol"
    addresses: list[int] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)  # observation IDs
    verified: bool = False
    verified_by: str = ""  # "static" | "dynamic" | "both"
    details: dict[str, Any] = field(default_factory=dict)  # category-specific data
