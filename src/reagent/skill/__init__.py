"""Progressive skill loading system.

Skills are domain-specific reference files (command cheat sheets, API references,
workflow guides) that agents load on demand via the ActivateSkillTool.

Skills live in the configured skills_dir (default: skills/) organized by domain:
    skills/
      rizin/
        commands.md
      gdb/
        commands.md
      frida/
        basics.md

Each .md file in a domain directory is a loadable skill. The directory name
is the skill domain, and files within it are individual skill pages.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class Skill:
    """A single loadable skill reference."""

    domain: str  # e.g. "rizin", "gdb"
    name: str  # e.g. "commands", "workflows"
    path: Path
    description: str = ""  # first line of file, if starts with #

    def load(self) -> str:
        """Load skill content from disk."""
        return self.path.read_text()

    @property
    def key(self) -> str:
        """Unique identifier: domain/name."""
        return f"{self.domain}/{self.name}"


@dataclass
class SkillRegistry:
    """Discovers and manages available skills from a directory.

    Skills are organized as: skills_dir/<domain>/<name>.md
    Discovery happens once at construction; content is loaded on demand.
    """

    skills_dir: Path
    _skills: dict[str, Skill] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self._discover()

    def _discover(self) -> None:
        """Scan skills_dir for available skill files."""
        if not self.skills_dir.is_dir():
            logger.warning("Skills directory not found: %s", self.skills_dir)
            return

        for domain_dir in sorted(self.skills_dir.iterdir()):
            if not domain_dir.is_dir() or domain_dir.name.startswith("."):
                continue
            domain = domain_dir.name
            for skill_file in sorted(domain_dir.iterdir()):
                if skill_file.suffix not in (".md", ".txt", ".rst"):
                    continue
                name = skill_file.stem
                # Extract description from first heading
                desc = ""
                try:
                    first_line = skill_file.read_text().split("\n", 1)[0]
                    if first_line.startswith("# "):
                        desc = first_line[2:].strip()
                except Exception:
                    pass

                skill = Skill(
                    domain=domain,
                    name=name,
                    path=skill_file,
                    description=desc,
                )
                self._skills[skill.key] = skill
                logger.debug("Discovered skill: %s (%s)", skill.key, desc)

        logger.info("Discovered %d skills in %s", len(self._skills), self.skills_dir)

    def list_skills(self) -> list[Skill]:
        """Return all available skills."""
        return list(self._skills.values())

    def list_domains(self) -> list[str]:
        """Return unique domain names."""
        return sorted({s.domain for s in self._skills.values()})

    def get(self, key: str) -> Skill | None:
        """Get a skill by key (domain/name)."""
        return self._skills.get(key)

    def get_by_domain(self, domain: str) -> list[Skill]:
        """Get all skills in a domain."""
        return [s for s in self._skills.values() if s.domain == domain]

    def load(self, key: str) -> str | None:
        """Load skill content by key. Returns None if not found."""
        skill = self.get(key)
        if skill is None:
            return None
        return skill.load()

    def describe(self) -> str:
        """Human-readable listing of available skills for tool descriptions."""
        if not self._skills:
            return "No skills available."
        lines = ["Available skills:"]
        for domain in self.list_domains():
            skills = self.get_by_domain(domain)
            names = ", ".join(s.name for s in skills)
            lines.append(f"  {domain}: {names}")
        return "\n".join(lines)
