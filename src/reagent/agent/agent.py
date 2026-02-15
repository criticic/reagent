"""Agent definition — loaded from YAML frontmatter in markdown files."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentConfig:
    """Configuration for an agent, typically from YAML frontmatter."""

    name: str
    description: str = ""
    mode: str = "subagent"  # "primary" | "subagent"
    tools: list[str] = field(default_factory=list)
    max_steps: int = 50
    model: str | None = None  # Override model for this agent
    temperature: float | None = None


@dataclass
class Agent:
    """A configured agent ready to run.

    Agents are defined as markdown files with YAML frontmatter:

        ---
        name: static
        description: Deep static analysis
        mode: subagent
        tools: [disassemble, decompile, xrefs]
        max_steps: 50
        ---

        You are the Static Analysis Specialist...
    """

    config: AgentConfig
    system_prompt: str = ""

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def tools(self) -> list[str]:
        return self.config.tools

    @property
    def max_steps(self) -> int:
        return self.config.max_steps

    @classmethod
    def from_markdown(cls, path: str) -> Agent:
        """Load an agent definition from a markdown file with YAML frontmatter."""
        with open(path, "r") as f:
            content = f.read()

        config_dict, prompt = _parse_frontmatter(content)
        config = AgentConfig(**config_dict)
        return cls(config=config, system_prompt=prompt.strip())

    @classmethod
    def from_dict(cls, data: dict[str, Any], system_prompt: str = "") -> Agent:
        """Create an agent from a dictionary config."""
        config = AgentConfig(**data)
        return cls(config=config, system_prompt=system_prompt)


def _parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter from markdown content.

    Returns (config_dict, body_text).
    """
    import yaml  # lazy import — only needed when loading agents

    pattern = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)", re.DOTALL)
    match = pattern.match(content)

    if not match:
        return {}, content

    frontmatter = match.group(1)
    body = match.group(2)

    try:
        config = yaml.safe_load(frontmatter) or {}
    except Exception:
        config = {}

    return config, body


def discover_agents(search_dirs: list[str]) -> list[Agent]:
    """Discover agent definitions from markdown files in directories.

    Searches for *.md files with YAML frontmatter containing a 'name' field.
    """
    agents = []
    for dir_path in search_dirs:
        if not os.path.isdir(dir_path):
            continue
        for fname in sorted(os.listdir(dir_path)):
            if not fname.endswith(".md"):
                continue
            full_path = os.path.join(dir_path, fname)
            try:
                agent = Agent.from_markdown(full_path)
                if agent.config.name:
                    agents.append(agent)
            except Exception:
                continue
    return agents
