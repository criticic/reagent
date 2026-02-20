"""BinaryModel — the shared knowledge base for binary analysis."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from reagent.model.hypothesis import Observation, Hypothesis, Finding


@dataclass
class TargetInfo:
    """Basic information about the analysis target."""

    path: str = ""
    format: str = ""  # "ELF", "PE", "Mach-O", "raw"
    arch: str = ""  # "x86_64", "arm64", "arm", "mips"
    endian: str = ""  # "little", "big"
    bits: int = 0  # 32 or 64
    stripped: bool = False
    pie: bool = False
    nx: bool = False
    canary: bool = False
    relro: str = ""  # "none", "partial", "full"


@dataclass
class BinaryModel:
    """The shared knowledge base for binary analysis.

    Tracks observations (raw data), hypotheses (interpretive claims),
    and findings (verified facts) across all agents. The orchestrator
    uses this to decide what work to delegate next and to generate
    the final report.
    """

    target: TargetInfo = field(default_factory=TargetInfo)
    observations: list[Observation] = field(default_factory=list)
    hypotheses: list[Hypothesis] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    functions: dict[str, str] = field(default_factory=dict)  # address -> name
    strings: list[dict[str, Any]] = field(default_factory=list)  # interesting strings

    def add_observation(self, obs: Observation) -> str:
        """Add an observation and return its ID."""
        self.observations.append(obs)
        return obs.id

    def add_hypothesis(self, hyp: Hypothesis) -> str:
        """Add a hypothesis and return its ID."""
        self.hypotheses.append(hyp)
        return hyp.id

    def add_finding(self, finding: Finding) -> str:
        """Add a finding and return its ID."""
        self.findings.append(finding)
        return finding.id

    def promote_hypothesis(
        self, hypothesis_id: str, agent: str, details: dict | None = None
    ) -> Finding | None:
        """Promote a confirmed hypothesis to a finding."""
        hyp = self.get_hypothesis(hypothesis_id)
        if hyp is None:
            return None

        hyp.confirm(agent)

        finding = Finding(
            description=hyp.description,
            category=hyp.category,
            addresses=[hyp.address] if hyp.address is not None else [],
            evidence=hyp.evidence,
            verified=True,
            verified_by=agent,
            details=details or {},
        )
        self.findings.append(finding)
        return finding

    def get_hypothesis(self, hypothesis_id: str) -> Hypothesis | None:
        """Get a hypothesis by ID."""
        for h in self.hypotheses:
            if h.id == hypothesis_id:
                return h
        return None

    def unverified_hypotheses(self) -> list[Hypothesis]:
        """Get hypotheses that need verification."""
        return [h for h in self.hypotheses if h.status == "proposed"]

    def summary(self, for_agent: str | None = None, max_chars: int = 16000) -> str:
        """Render a context-appropriate summary for injection into prompts.

        Args:
            for_agent: If "dynamic", only include hypotheses needing verification.
                       If "static", include observations + hypotheses.
                       If None, include everything.
            max_chars: Maximum summary length.
        """
        sections = []

        # Target info
        t = self.target
        if t.path:
            sections.append(
                f"## Target\n"
                f"Path: {t.path}\n"
                f"Format: {t.format} | Arch: {t.arch} | Bits: {t.bits} | Endian: {t.endian}\n"
                f"Stripped: {t.stripped} | PIE: {t.pie} | NX: {t.nx}"
            )

        # Functions (abbreviated)
        if self.functions:
            func_lines = [
                f"  {addr}: {name}" for addr, name in list(self.functions.items())[:50]
            ]
            sections.append(
                f"## Functions ({len(self.functions)} total)\n" + "\n".join(func_lines)
            )

        # Observations (for static agent or general)
        if for_agent != "dynamic":
            recent_obs = self.observations[-20:]  # Last 20
            if recent_obs:
                obs_lines = [
                    f"  [{o.id}] {o.type} @ {hex(o.address) if o.address is not None else 'N/A'}: {o.data[:200]}"
                    for o in recent_obs
                ]
                sections.append(
                    f"## Observations ({len(self.observations)} total, showing last {len(recent_obs)})\n"
                    + "\n".join(obs_lines)
                )

        # Hypotheses
        if for_agent == "dynamic":
            hyps = self.unverified_hypotheses()
            label = "Hypotheses Needing Verification"
        else:
            hyps = self.hypotheses
            label = "Hypotheses"
        if hyps:
            hyp_lines = [
                f"  [{h.id}] [{h.status}] (conf: {h.confidence:.1f}) {h.description}"
                for h in hyps
            ]
            sections.append(f"## {label}\n" + "\n".join(hyp_lines))

        # Findings
        if self.findings:
            find_lines = [
                f"  [{f.id}] [{f.category}] {f.description} (verified: {f.verified_by})"
                for f in self.findings
            ]
            sections.append(f"## Confirmed Findings\n" + "\n".join(find_lines))

        result = "\n\n".join(sections)
        if len(result) > max_chars:
            result = result[:max_chars] + "\n[... summary truncated]"
        return result

    def to_dict(self) -> dict[str, Any]:
        """Serialize the entire model to a dict."""
        import dataclasses

        return {
            "target": dataclasses.asdict(self.target),
            "observations": [dataclasses.asdict(o) for o in self.observations],
            "hypotheses": [dataclasses.asdict(h) for h in self.hypotheses],
            "findings": [dataclasses.asdict(f) for f in self.findings],
            "functions": self.functions,
            "strings": self.strings,
        }

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=2, default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BinaryModel:
        """Deserialize from a dict (inverse of to_dict)."""
        target = TargetInfo(**data.get("target", {}))
        observations = [Observation(**o) for o in data.get("observations", [])]
        hypotheses = [Hypothesis(**h) for h in data.get("hypotheses", [])]
        findings = [Finding(**f) for f in data.get("findings", [])]
        return cls(
            target=target,
            observations=observations,
            hypotheses=hypotheses,
            findings=findings,
            functions=data.get("functions", {}),
            strings=data.get("strings", []),
        )

    @classmethod
    def from_json(cls, json_str: str) -> BinaryModel:
        """Deserialize from a JSON string."""
        return cls.from_dict(json.loads(json_str))
