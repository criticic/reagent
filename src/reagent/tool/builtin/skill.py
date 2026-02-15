"""ActivateSkillTool — progressive loading of domain-specific knowledge."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from reagent.skill import SkillRegistry
from reagent.tool.base import BaseTool, ToolError, ToolOk, ToolResult


class ActivateSkillParams(BaseModel):
    skill: str = Field(
        description=(
            "The skill to activate, as 'domain/name' (e.g. 'rizin/commands', "
            "'gdb/commands'). Use 'list' to see all available skills."
        )
    )


class ActivateSkillTool(BaseTool[ActivateSkillParams]):
    """Load domain-specific reference material into context on demand.

    Use this when you need detailed knowledge about a specific tool or domain
    (e.g., rizin commands, GDB workflows). The skill content will be injected
    into context so you can reference it for subsequent analysis steps.

    Call with skill='list' to see what skills are available.
    """

    name: ClassVar[str] = "activate_skill"
    description: ClassVar[str] = (
        "Load domain-specific reference material (command cheat sheets, API docs, "
        "workflows) into context. Call with skill='list' to see available skills. "
        "Use 'domain/name' format to load a specific skill."
    )
    param_model: ClassVar[type[BaseModel]] = ActivateSkillParams

    def __init__(self, registry: SkillRegistry) -> None:
        self._registry = registry
        # Dynamically update description with available skills
        available = registry.describe()
        self.__class__.description = (
            "Load domain-specific reference material into context. "
            f"{available} "
            "Use 'domain/name' format (e.g. 'rizin/commands') to load a skill, "
            "or 'list' to see all available skills."
        )

    async def execute(self, params: ActivateSkillParams) -> ToolResult:
        key = params.skill.strip()

        # List mode
        if key == "list":
            listing = self._registry.describe()
            return ToolOk(output=listing, brief="Listed skills")

        # Try loading by exact key (domain/name)
        content = self._registry.load(key)
        if content is not None:
            skill = self._registry.get(key)
            assert skill is not None
            header = f"=== Skill: {skill.key} ==="
            if skill.description:
                header += f"\n{skill.description}"
            return ToolOk(
                output=f"{header}\n\n{content}",
                brief=f"Loaded skill: {key}",
            )

        # Try loading entire domain
        domain_skills = self._registry.get_by_domain(key)
        if domain_skills:
            parts: list[str] = []
            for skill in domain_skills:
                header = f"=== {skill.key} ==="
                body = skill.load()
                parts.append(f"{header}\n{body}")
            combined = "\n\n".join(parts)
            return ToolOk(
                output=combined,
                brief=f"Loaded {len(domain_skills)} skills from domain: {key}",
            )

        # Not found
        available = self._registry.describe()
        return ToolError(
            output=f"Skill '{key}' not found.\n\n{available}",
            brief=f"Skill not found: {key}",
        )
