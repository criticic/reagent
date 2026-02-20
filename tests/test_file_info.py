"""Tests for reagent.re.file_info (ELFSecurityInfo, _detect_elf_security)."""

from __future__ import annotations

from reagent.re.file_info import ELFSecurityInfo


# ---------------------------------------------------------------------------
# ELFSecurityInfo dataclass
# ---------------------------------------------------------------------------


class TestELFSecurityInfo:
    def test_defaults(self) -> None:
        info = ELFSecurityInfo()
        assert info.pie is False
        assert info.nx is False
        assert info.has_relro is False
        assert info.full_relro is False
        assert info.canary is False
        assert info.fortified == []

    def test_relro_str_none(self) -> None:
        info = ELFSecurityInfo()
        assert info.relro_str == "No"

    def test_relro_str_partial(self) -> None:
        info = ELFSecurityInfo(has_relro=True)
        assert info.relro_str == "Partial"

    def test_relro_str_full(self) -> None:
        info = ELFSecurityInfo(has_relro=True, full_relro=True)
        assert info.relro_str == "Full"

    def test_relro_str_full_without_has_relro(self) -> None:
        """full_relro=True takes precedence even if has_relro=False (edge case)."""
        info = ELFSecurityInfo(full_relro=True)
        assert info.relro_str == "Full"

    def test_all_features_enabled(self) -> None:
        info = ELFSecurityInfo(
            pie=True,
            nx=True,
            has_relro=True,
            full_relro=True,
            canary=True,
            fortified=["__printf_chk", "__memcpy_chk"],
        )
        assert info.pie is True
        assert info.nx is True
        assert info.relro_str == "Full"
        assert info.canary is True
        assert len(info.fortified) == 2

    def test_fortified_is_independent(self) -> None:
        """Each instance gets its own fortified list (default_factory)."""
        info1 = ELFSecurityInfo()
        info2 = ELFSecurityInfo()
        info1.fortified.append("__printf_chk")
        assert info2.fortified == []
