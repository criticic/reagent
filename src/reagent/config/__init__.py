"""Configuration — Pydantic models for reagent settings."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    """LLM provider configuration.

    Model names use litellm's provider-prefix format:
        "gemini/gemini-3-flash-preview"
        "anthropic/claude-sonnet-4-5-20250929"
        "openai/gpt-4o"

    API keys are read from env vars automatically by litellm
    (ANTHROPIC_API_KEY, GEMINI_API_KEY, OPENAI_API_KEY).
    """

    model: str = Field(default="anthropic/claude-sonnet-4-5-20250929")
    fast_model: str = Field(
        default="anthropic/claude-haiku-4-5-20251001",
        description="Lightweight model for compaction/summarization (litellm format)",
    )
    temperature: float | None = Field(default=None)
    max_tokens: int | None = Field(default=None)
    context_window: int = Field(default=200_000)
    reasoning_effort: str | None = Field(
        default=None,
        description=(
            "Reasoning effort level for the main model: 'low', 'medium', or 'high'. "
            "Enables thinking/reasoning tokens on supported models "
            "(Anthropic, DeepSeek, Gemini, etc.)."
        ),
    )
    fast_reasoning_effort: str | None = Field(
        default=None,
        description=(
            "Reasoning effort level for the fast/compaction model: 'low', 'medium', or 'high'. "
            "Usually left unset (no reasoning) since the compaction model just summarizes."
        ),
    )


class AnalysisConfig(BaseModel):
    """Analysis session configuration."""

    max_steps: int = Field(default=100, description="Max agent steps per turn")
    auto_compact: bool = Field(
        default=True, description="Auto-compact context when approaching limit"
    )
    enable_dmail: bool = Field(
        default=True, description="Enable D-Mail context time-travel"
    )


class ReagentConfig(BaseModel):
    """Top-level reagent configuration."""

    llm: LLMConfig = Field(default_factory=LLMConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    agents_dir: str = Field(
        default="agents", description="Directory for agent definitions"
    )
    skills_dir: str = Field(default="skills", description="Directory for skill files")
    session_dir: str = Field(
        default="~/.reagent/sessions", description="Directory for session data"
    )

    @classmethod
    def load(cls, config_path: str | None = None) -> ReagentConfig:
        """Load config from file, env vars, or defaults.

        Priority: env vars > config file > defaults.

        Env vars:
            ANTHROPIC_API_KEY              - Anthropic API key (read by litellm automatically)
            OPENAI_API_KEY                 - OpenAI API key (read by litellm automatically)
            GEMINI_API_KEY                 - Gemini API key (read by litellm automatically)
            REAGENT_MODEL                  - Override primary model (litellm format with provider prefix)
            REAGENT_FAST_MODEL             - Override fast/lightweight model
            REAGENT_CONTEXT_WINDOW         - Override context window size
            REAGENT_REASONING_EFFORT       - Reasoning effort for main model (low/medium/high)
            REAGENT_FAST_REASONING_EFFORT  - Reasoning effort for fast model (low/medium/high)
        """
        # Load .env file if present.
        # override=True ensures .env values take precedence over stale
        # shell env vars — so when a user updates their .env with a new
        # API key, it actually gets picked up instead of silently using
        # whatever was previously exported in the shell.
        try:
            from dotenv import load_dotenv

            load_dotenv(override=True)
        except ImportError:
            pass

        config_data: dict[str, Any] = {}

        # Try loading from file
        if config_path and os.path.exists(config_path):
            import json

            with open(config_path) as f:
                config_data = json.load(f)

        # Override with env vars
        llm = config_data.get("llm", {})

        # Model overrides
        env_model = os.environ.get("REAGENT_MODEL")
        if env_model:
            llm["model"] = env_model

        env_fast_model = os.environ.get("REAGENT_FAST_MODEL")
        if env_fast_model:
            llm["fast_model"] = env_fast_model

        env_context_window = os.environ.get("REAGENT_CONTEXT_WINDOW")
        if env_context_window:
            llm["context_window"] = int(env_context_window)

        env_reasoning_effort = os.environ.get("REAGENT_REASONING_EFFORT")
        if env_reasoning_effort:
            llm["reasoning_effort"] = env_reasoning_effort.lower()

        env_fast_reasoning_effort = os.environ.get("REAGENT_FAST_REASONING_EFFORT")
        if env_fast_reasoning_effort:
            llm["fast_reasoning_effort"] = env_fast_reasoning_effort.lower()

        if llm:
            config_data["llm"] = llm

        return cls.model_validate(config_data)
