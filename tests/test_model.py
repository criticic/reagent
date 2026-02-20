"""Tests for reagent.model (BinaryModel, Hypothesis, Observation, Finding)."""

from __future__ import annotations

import json

from reagent.model import BinaryModel, Finding, Hypothesis, Observation, TargetInfo


# ---------------------------------------------------------------------------
# TargetInfo
# ---------------------------------------------------------------------------


class TestTargetInfo:
    def test_defaults(self) -> None:
        t = TargetInfo()
        assert t.path == ""
        assert t.format == ""
        assert t.arch == ""
        assert t.endian == ""
        assert t.bits == 0
        assert t.stripped is False
        assert t.pie is False
        assert t.nx is False
        assert t.canary is False
        assert t.relro == ""

    def test_custom_values(self) -> None:
        t = TargetInfo(
            path="/bin/ls",
            format="ELF",
            arch="x86_64",
            endian="little",
            bits=64,
            stripped=True,
            pie=True,
            nx=True,
            canary=True,
            relro="full",
        )
        assert t.path == "/bin/ls"
        assert t.bits == 64
        assert t.relro == "full"


# ---------------------------------------------------------------------------
# Observation
# ---------------------------------------------------------------------------


class TestObservation:
    def test_id_generated(self) -> None:
        o = Observation()
        assert len(o.id) == 8
        assert isinstance(o.id, str)

    def test_unique_ids(self) -> None:
        ids = {Observation().id for _ in range(100)}
        assert len(ids) == 100

    def test_defaults(self) -> None:
        o = Observation()
        assert o.type == ""
        assert o.source == ""
        assert o.address is None
        assert o.data == ""
        assert isinstance(o.timestamp, float)

    def test_custom_values(self) -> None:
        o = Observation(
            type="disassembly", source="static", address=0x401000, data="nop"
        )
        assert o.type == "disassembly"
        assert o.address == 0x401000

    def test_address_zero(self) -> None:
        """Address 0 is valid and should not be treated as None."""
        o = Observation(address=0)
        assert o.address is not None
        assert o.address == 0


# ---------------------------------------------------------------------------
# Hypothesis
# ---------------------------------------------------------------------------


class TestHypothesis:
    def test_defaults(self) -> None:
        h = Hypothesis()
        assert h.status == "proposed"
        assert h.confidence == 0.5
        assert h.evidence == []
        assert h.verified_by is None
        assert h.reject_reason == ""

    def test_confirm(self) -> None:
        h = Hypothesis(description="test")
        h.confirm("static_agent")
        assert h.status == "confirmed"
        assert h.verified_by == "static_agent"
        assert h.confidence == 1.0

    def test_confirm_with_evidence(self) -> None:
        h = Hypothesis(description="test", evidence=["obs1"])
        h.confirm("agent", additional_evidence=["obs2", "obs3"])
        assert h.evidence == ["obs1", "obs2", "obs3"]

    def test_reject(self) -> None:
        h = Hypothesis(description="test")
        h.reject("dynamic_agent", reason="not reproducible")
        assert h.status == "rejected"
        assert h.verified_by == "dynamic_agent"
        assert h.confidence == 0.0
        assert h.reject_reason == "not reproducible"

    def test_reject_no_reason(self) -> None:
        h = Hypothesis(description="test")
        h.reject("agent")
        assert h.reject_reason == ""

    def test_address_zero(self) -> None:
        """Address 0 is valid for hypotheses too."""
        h = Hypothesis(address=0)
        assert h.address is not None
        assert h.address == 0


# ---------------------------------------------------------------------------
# Finding
# ---------------------------------------------------------------------------


class TestFinding:
    def test_defaults(self) -> None:
        f = Finding()
        assert f.verified is False
        assert f.verified_by == ""
        assert f.details == {}
        assert f.addresses == []
        assert f.evidence == []

    def test_id_generated(self) -> None:
        f = Finding()
        assert len(f.id) == 8


# ---------------------------------------------------------------------------
# BinaryModel — core operations
# ---------------------------------------------------------------------------


class TestBinaryModel:
    def test_empty(self) -> None:
        m = BinaryModel()
        assert m.observations == []
        assert m.hypotheses == []
        assert m.findings == []
        assert m.functions == {}

    def test_add_observation(self) -> None:
        m = BinaryModel()
        obs = Observation(data="test")
        oid = m.add_observation(obs)
        assert oid == obs.id
        assert len(m.observations) == 1
        assert m.observations[0] is obs

    def test_add_hypothesis(self) -> None:
        m = BinaryModel()
        h = Hypothesis(description="maybe XOR")
        hid = m.add_hypothesis(h)
        assert hid == h.id
        assert len(m.hypotheses) == 1

    def test_add_finding(self) -> None:
        m = BinaryModel()
        f = Finding(description="confirmed")
        fid = m.add_finding(f)
        assert fid == f.id
        assert len(m.findings) == 1

    def test_get_hypothesis_found(self) -> None:
        m = BinaryModel()
        h = Hypothesis(description="test")
        m.add_hypothesis(h)
        result = m.get_hypothesis(h.id)
        assert result is h

    def test_get_hypothesis_not_found(self) -> None:
        m = BinaryModel()
        assert m.get_hypothesis("nonexistent") is None

    def test_unverified_hypotheses(self) -> None:
        m = BinaryModel()
        h1 = Hypothesis(description="proposed one")
        h2 = Hypothesis(description="confirmed one")
        h2.confirm("agent")
        h3 = Hypothesis(description="proposed two")
        m.add_hypothesis(h1)
        m.add_hypothesis(h2)
        m.add_hypothesis(h3)
        unverified = m.unverified_hypotheses()
        assert len(unverified) == 2
        assert h1 in unverified
        assert h3 in unverified

    def test_promote_hypothesis(self) -> None:
        m = BinaryModel()
        h = Hypothesis(description="XOR cipher", category="crypto", address=0x1000)
        m.add_hypothesis(h)
        finding = m.promote_hypothesis(h.id, agent="static")
        assert finding is not None
        assert finding.description == "XOR cipher"
        assert finding.category == "crypto"
        assert 0x1000 in finding.addresses
        assert finding.verified is True
        assert finding.verified_by == "static"
        # Original hypothesis should be confirmed
        assert h.status == "confirmed"

    def test_promote_hypothesis_not_found(self) -> None:
        m = BinaryModel()
        result = m.promote_hypothesis("nonexistent", agent="agent")
        assert result is None

    def test_promote_hypothesis_with_details(self) -> None:
        m = BinaryModel()
        h = Hypothesis(description="test")
        m.add_hypothesis(h)
        finding = m.promote_hypothesis(h.id, agent="a", details={"key": "value"})
        assert finding is not None
        assert finding.details == {"key": "value"}

    def test_promote_hypothesis_address_zero(self) -> None:
        """address=0 should be included in finding.addresses."""
        m = BinaryModel()
        h = Hypothesis(description="entry point", address=0)
        m.add_hypothesis(h)
        finding = m.promote_hypothesis(h.id, agent="agent")
        assert finding is not None
        assert 0 in finding.addresses


# ---------------------------------------------------------------------------
# BinaryModel — summary
# ---------------------------------------------------------------------------


class TestBinaryModelSummary:
    def test_empty_summary(self) -> None:
        m = BinaryModel()
        s = m.summary()
        assert isinstance(s, str)

    def test_summary_with_target(self) -> None:
        m = BinaryModel(target=TargetInfo(path="/bin/ls", format="ELF", arch="x86_64"))
        s = m.summary()
        assert "/bin/ls" in s or "ELF" in s

    def test_summary_truncation(self) -> None:
        m = BinaryModel()
        # Add lots of observations to exceed max_chars
        for i in range(100):
            m.add_observation(Observation(data="x" * 200))
        s = m.summary(max_chars=500)
        assert len(s) <= 600  # Allow some slack for truncation message

    def test_summary_for_dynamic_agent(self) -> None:
        m = BinaryModel()
        m.add_observation(Observation(data="should be hidden"))
        h = Hypothesis(description="unverified")
        m.add_hypothesis(h)
        s = m.summary(for_agent="dynamic")
        # Dynamic agent summary should not include raw observations
        assert "should be hidden" not in s


# ---------------------------------------------------------------------------
# BinaryModel — serialization round-trip
# ---------------------------------------------------------------------------


class TestBinaryModelSerialization:
    def test_to_dict(self) -> None:
        m = BinaryModel(target=TargetInfo(path="/test"))
        m.add_observation(Observation(data="obs1"))
        m.add_hypothesis(Hypothesis(description="hyp1"))
        m.add_finding(Finding(description="find1"))
        d = m.to_dict()
        assert d["target"]["path"] == "/test"
        assert len(d["observations"]) == 1
        assert len(d["hypotheses"]) == 1
        assert len(d["findings"]) == 1

    def test_to_json(self) -> None:
        m = BinaryModel(target=TargetInfo(path="/test"))
        j = m.to_json()
        parsed = json.loads(j)
        assert parsed["target"]["path"] == "/test"

    def test_from_dict_round_trip(self) -> None:
        m = BinaryModel(target=TargetInfo(path="/test", format="ELF", bits=64))
        m.add_observation(Observation(data="obs1", address=0x1000))
        m.add_hypothesis(Hypothesis(description="hyp1", confidence=0.8))
        m.add_finding(Finding(description="find1", addresses=[0x2000], verified=True))
        d = m.to_dict()
        m2 = BinaryModel.from_dict(d)
        assert m2.target.path == "/test"
        assert m2.target.bits == 64
        assert len(m2.observations) == 1
        assert m2.observations[0].data == "obs1"
        assert m2.observations[0].address == 0x1000
        assert len(m2.hypotheses) == 1
        assert m2.hypotheses[0].confidence == 0.8
        assert len(m2.findings) == 1
        assert m2.findings[0].verified is True

    def test_from_json_round_trip(self) -> None:
        m = BinaryModel(target=TargetInfo(path="/test"))
        m.add_hypothesis(Hypothesis(description="test", category="crypto"))
        j = m.to_json()
        m2 = BinaryModel.from_json(j)
        assert m2.hypotheses[0].category == "crypto"

    def test_from_dict_empty(self) -> None:
        m = BinaryModel.from_dict({})
        assert m.target.path == ""
        assert m.observations == []
