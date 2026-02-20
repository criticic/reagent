"""Tests for reagent.llm.provider (retry logic, ProviderConfig, create_provider)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from reagent.llm.provider import (
    LiteLLMProvider,
    ProviderConfig,
    _acompletion_with_retry,
    _chunk_to_dict,
    create_provider,
)


# ---------------------------------------------------------------------------
# ProviderConfig
# ---------------------------------------------------------------------------


class TestProviderConfig:
    def test_defaults(self) -> None:
        config = ProviderConfig(model="test/model")
        assert config.model == "test/model"
        assert config.temperature is None
        assert config.max_tokens is None
        assert config.context_window == 200_000
        assert config.reasoning_effort is None

    def test_custom_values(self) -> None:
        config = ProviderConfig(
            model="anthropic/claude-sonnet-4-5-20250929",
            temperature=0.5,
            max_tokens=4096,
            context_window=100_000,
            reasoning_effort="high",
        )
        assert config.temperature == 0.5
        assert config.max_tokens == 4096
        assert config.context_window == 100_000
        assert config.reasoning_effort == "high"


# ---------------------------------------------------------------------------
# create_provider
# ---------------------------------------------------------------------------


class TestCreateProvider:
    def test_returns_litellm_provider(self) -> None:
        provider = create_provider("test/model")
        assert isinstance(provider, LiteLLMProvider)

    def test_config_propagated(self) -> None:
        provider = create_provider(
            "anthropic/claude-sonnet-4-5-20250929",
            temperature=0.7,
            max_tokens=2048,
            context_window=150_000,
            reasoning_effort="medium",
        )
        assert provider.config.model == "anthropic/claude-sonnet-4-5-20250929"
        assert provider.config.temperature == 0.7
        assert provider.config.max_tokens == 2048
        assert provider.config.context_window == 150_000
        assert provider.config.reasoning_effort == "medium"


# ---------------------------------------------------------------------------
# _acompletion_with_retry — retry logic
# ---------------------------------------------------------------------------


class TestRetryLogic:
    async def test_success_on_first_try(self) -> None:
        mock_acompletion = AsyncMock(return_value="ok")
        with patch("litellm.acompletion", mock_acompletion):
            result = await _acompletion_with_retry(model="test", messages=[])
            assert result == "ok"
            assert mock_acompletion.call_count == 1

    async def test_retries_on_connection_error(self) -> None:
        mock_acompletion = AsyncMock(side_effect=[ConnectionError("conn failed"), "ok"])
        with patch("litellm.acompletion", mock_acompletion):
            result = await _acompletion_with_retry(model="test", messages=[])
            assert result == "ok"
            assert mock_acompletion.call_count == 2

    async def test_retries_on_timeout_error(self) -> None:
        mock_acompletion = AsyncMock(side_effect=[TimeoutError("timed out"), "ok"])
        with patch("litellm.acompletion", mock_acompletion):
            result = await _acompletion_with_retry(model="test", messages=[])
            assert result == "ok"
            assert mock_acompletion.call_count == 2

    async def test_retries_on_os_error(self) -> None:
        mock_acompletion = AsyncMock(side_effect=[OSError("network error"), "ok"])
        with patch("litellm.acompletion", mock_acompletion):
            result = await _acompletion_with_retry(model="test", messages=[])
            assert result == "ok"
            assert mock_acompletion.call_count == 2

    async def test_gives_up_after_3_attempts(self) -> None:
        mock_acompletion = AsyncMock(
            side_effect=[
                ConnectionError("fail 1"),
                ConnectionError("fail 2"),
                ConnectionError("fail 3"),
            ]
        )
        with patch("litellm.acompletion", mock_acompletion):
            with pytest.raises(ConnectionError, match="fail 3"):
                await _acompletion_with_retry(model="test", messages=[])
            assert mock_acompletion.call_count == 3

    async def test_does_not_retry_on_value_error(self) -> None:
        """Non-transient errors should not be retried."""
        mock_acompletion = AsyncMock(side_effect=ValueError("bad input"))
        with patch("litellm.acompletion", mock_acompletion):
            with pytest.raises(ValueError, match="bad input"):
                await _acompletion_with_retry(model="test", messages=[])
            assert mock_acompletion.call_count == 1

    async def test_does_not_retry_on_runtime_error(self) -> None:
        mock_acompletion = AsyncMock(side_effect=RuntimeError("fatal"))
        with patch("litellm.acompletion", mock_acompletion):
            with pytest.raises(RuntimeError, match="fatal"):
                await _acompletion_with_retry(model="test", messages=[])
            assert mock_acompletion.call_count == 1


# ---------------------------------------------------------------------------
# _chunk_to_dict — normalization
# ---------------------------------------------------------------------------


class _FakeDelta:
    def __init__(
        self,
        content: str | None = None,
        role: str | None = None,
        tool_calls: list | None = None,
    ) -> None:
        self.content = content
        self.role = role
        self.tool_calls = tool_calls


class _FakeChoice:
    def __init__(self, delta: _FakeDelta, finish_reason: str | None = None) -> None:
        self.delta = delta
        self.finish_reason = finish_reason


class _FakeChunk:
    def __init__(
        self,
        choices: list[_FakeChoice] | None = None,
        usage: object | None = None,
        chunk_id: str = "chunk_1",
    ) -> None:
        self.id = chunk_id
        self.object = "chat.completion.chunk"
        self.choices = choices
        self.usage = usage


class TestChunkToDict:
    def test_text_content(self) -> None:
        chunk = _FakeChunk(choices=[_FakeChoice(delta=_FakeDelta(content="hello"))])
        d = _chunk_to_dict(chunk)
        assert d["delta"]["content"] == "hello"
        assert d["finish_reason"] is None

    def test_finish_reason(self) -> None:
        chunk = _FakeChunk(
            choices=[_FakeChoice(delta=_FakeDelta(), finish_reason="stop")]
        )
        d = _chunk_to_dict(chunk)
        assert d["finish_reason"] == "stop"

    def test_no_choices(self) -> None:
        chunk = _FakeChunk(choices=None)
        d = _chunk_to_dict(chunk)
        assert d["finish_reason"] is None
        assert d["delta"] == {}

    def test_empty_choices(self) -> None:
        """Empty choices list behaves like no choices."""
        chunk = _FakeChunk(choices=[])
        # This would raise IndexError accessing choices[0] with the current code,
        # but the current code checks `if choices:` which is falsy for empty list.
        d = _chunk_to_dict(chunk)
        assert d["finish_reason"] is None

    def test_usage_present(self) -> None:
        class FakeUsage:
            prompt_tokens = 100
            completion_tokens = 50
            total_tokens = 150

        chunk = _FakeChunk(
            choices=[_FakeChoice(delta=_FakeDelta())],
            usage=FakeUsage(),
        )
        d = _chunk_to_dict(chunk)
        assert d["usage"]["prompt_tokens"] == 100
        assert d["usage"]["completion_tokens"] == 50
        assert d["usage"]["total_tokens"] == 150

    def test_role_present(self) -> None:
        chunk = _FakeChunk(choices=[_FakeChoice(delta=_FakeDelta(role="assistant"))])
        d = _chunk_to_dict(chunk)
        assert d["delta"]["role"] == "assistant"

    def test_content_none_not_in_delta(self) -> None:
        chunk = _FakeChunk(choices=[_FakeChoice(delta=_FakeDelta(content=None))])
        d = _chunk_to_dict(chunk)
        assert "content" not in d["delta"]
