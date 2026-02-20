"""LLM provider abstraction — unified via litellm.

litellm handles all provider-specific details (Anthropic native SDK,
OpenAI, Gemini, etc.) and normalizes streaming to OpenAI-format chunks.
We convert those to our internal chunk dict format for streaming.py.

Normalized chunk format (same as before):
    {
        "id": str,
        "object": str,
        "finish_reason": str | None,
        "delta": {
            "role": str | None,
            "content": str | None,
            "tool_calls": [...] | None,   # OpenAI-style tool call deltas
        },
        "usage": {
            "prompt_tokens": int,
            "completion_tokens": int,
            "total_tokens": int,
        } | None,
    }
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

if TYPE_CHECKING:
    from litellm import CustomStreamWrapper, ModelResponse, ModelResponseStream

logger = logging.getLogger(__name__)


@dataclass
class ProviderConfig:
    """Configuration for an LLM provider."""

    model: str
    temperature: float | None = None
    max_tokens: int | None = None
    context_window: int = 200_000
    reasoning_effort: str | None = None  # "low", "medium", or "high"


@runtime_checkable
class ChatProvider(Protocol):
    """Protocol for LLM providers."""

    @property
    def config(self) -> ProviderConfig: ...

    def stream(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream a chat completion. Yields normalized chunk dicts."""
        ...


# ---------------------------------------------------------------------------
# litellm provider
# ---------------------------------------------------------------------------


@dataclass
class LiteLLMProvider:
    """Unified LLM provider using litellm.

    litellm handles provider detection from the model string prefix
    (e.g. "anthropic/claude-...", "gemini/gemini-...", "openai/gpt-...")
    and reads API keys from environment variables automatically.
    """

    _config: ProviderConfig

    @property
    def config(self) -> ProviderConfig:
        return self._config

    async def stream(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream from litellm, yielding normalized chunk dicts."""
        import litellm

        api_messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            *messages,
        ]

        kwargs: dict[str, Any] = {
            "model": self._config.model,
            "messages": api_messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        if tools:
            kwargs["tools"] = tools

        if self._config.temperature is not None:
            kwargs["temperature"] = self._config.temperature

        if self._config.max_tokens is not None:
            kwargs["max_tokens"] = self._config.max_tokens

        # Reasoning effort (provider-agnostic via litellm)
        if self._config.reasoning_effort:
            # Enable modify_params so litellm auto-handles the case where
            # thinking_blocks are missing from prior assistant messages
            # (e.g. after tool call round-trips through OpenAI-compat clients).
            # NOTE: This is a global side-effect on litellm's module state.
            litellm.modify_params = True
            kwargs["reasoning_effort"] = self._config.reasoning_effort

        response = await _acompletion_with_retry(**kwargs)

        async for chunk in response:  # type: ignore[union-attr]
            yield _chunk_to_dict(chunk)


@retry(
    retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=30),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
async def _acompletion_with_retry(**kwargs: Any) -> CustomStreamWrapper | ModelResponse:
    """Call litellm.acompletion with retry on transient errors."""
    import litellm

    return await litellm.acompletion(**kwargs)


def _chunk_to_dict(chunk: ModelResponseStream) -> dict[str, Any]:
    """Convert a litellm ModelResponseStream chunk to our normalized dict.

    litellm chunks have the same shape as OpenAI ChatCompletionChunk objects:
      chunk.id, chunk.object, chunk.choices[0].delta.{content, role, tool_calls},
      chunk.choices[0].finish_reason, chunk.usage
    """
    result: dict[str, Any] = {
        "id": getattr(chunk, "id", ""),
        "object": getattr(chunk, "object", "chat.completion.chunk"),
    }

    choices = getattr(chunk, "choices", None)
    if choices:
        choice = choices[0]
        delta = choice.delta
        result["finish_reason"] = choice.finish_reason
        result["delta"] = {}

        if delta.content is not None:
            result["delta"]["content"] = delta.content

        if delta.role is not None:
            result["delta"]["role"] = delta.role

        # Thinking / reasoning content (Anthropic extended thinking, DeepSeek, etc.)
        reasoning = getattr(delta, "reasoning_content", None)
        if reasoning is not None:
            result["delta"]["reasoning_content"] = reasoning

        thinking_blocks = getattr(delta, "thinking_blocks", None)
        if thinking_blocks:
            result["delta"]["thinking_blocks"] = thinking_blocks

        if delta.tool_calls:
            result["delta"]["tool_calls"] = []
            for tc in delta.tool_calls:
                tc_dict: dict[str, Any] = {
                    "index": tc.index,
                    "id": tc.id,
                    "type": tc.type,
                    "function": {
                        "name": tc.function.name
                        if tc.function and tc.function.name
                        else None,
                        "arguments": tc.function.arguments if tc.function else None,
                    }
                    if tc.function
                    else None,
                }
                result["delta"]["tool_calls"].append(tc_dict)
    else:
        result["finish_reason"] = None
        result["delta"] = {}

    usage = getattr(chunk, "usage", None)
    if usage:
        result["usage"] = {
            "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
            "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
            "total_tokens": getattr(usage, "total_tokens", 0) or 0,
        }

    return result


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_provider(
    model: str,
    temperature: float | None = None,
    max_tokens: int | None = None,
    context_window: int = 200_000,
    reasoning_effort: str | None = None,
) -> ChatProvider:
    """Create a LiteLLM provider.

    Args:
        model: Model name with provider prefix (e.g. "gemini/gemini-3-flash-preview",
               "anthropic/claude-sonnet-4-5-20250929", "openai/gpt-4o").
               litellm detects the provider from the prefix and reads
               API keys from env vars automatically.
        temperature: Sampling temperature.
        max_tokens: Max output tokens.
        context_window: Context window size.
        reasoning_effort: Reasoning effort level ("low", "medium", "high").
            Pass ``None`` to disable reasoning/thinking.

    Returns:
        A ChatProvider instance.
    """
    config = ProviderConfig(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        context_window=context_window,
        reasoning_effort=reasoning_effort,
    )
    return LiteLLMProvider(_config=config)
