"""The core agent loop — the heart of reagent."""

from __future__ import annotations

import asyncio
import enum
import logging
from collections.abc import Awaitable
from typing import Callable

from reagent.agent.agent import Agent
from reagent.context import Context
from reagent.llm.message import ContentPart, Message
from reagent.llm.provider import ChatProvider
from reagent.llm.streaming import step, StepResult
from reagent.tool.registry import ToolRegistry

logger = logging.getLogger(__name__)

CONTEXT_RESERVE_TOKENS = 20_000


class TurnOutcome(enum.Enum):
    """Why did the agent turn end?"""

    COMPLETE = "complete"  # Agent finished naturally (no more tool calls)
    MAX_STEPS = "max_steps"  # Hit the step limit
    ERROR = "error"  # Unrecoverable error


class BackToTheFuture(BaseException):
    """Raised when D-Mail triggers a context revert.

    Extends BaseException (not Exception) so it propagates through
    generic ``except Exception`` handlers in BaseTool.__call__ and
    streaming._run_tool without being swallowed.
    """

    def __init__(self, checkpoint_id: int, message: str) -> None:
        self.checkpoint_id = checkpoint_id
        self.message = message
        super().__init__(f"D-Mail to checkpoint {checkpoint_id}")


async def agent_loop(
    agent: Agent,
    context: Context,
    provider: ChatProvider,
    tool_registry: ToolRegistry,
    on_step: Callable[[int, StepResult], None] | None = None,
    on_step_begin: Callable[[int, str], None] | None = None,
    on_text: Callable[[str], None] | None = None,
    on_tool_call: Callable[[str, str, str], None] | None = None,
    on_tool_result: Callable[[str, str, str, bool], None] | None = None,
    on_thinking: Callable[[str], None] | None = None,
    on_dmail: Callable[[int, str], None] | None = None,
    compact_fn: Callable[..., Awaitable[str]] | None = None,
    compact_provider: ChatProvider | None = None,
) -> TurnOutcome:
    """Run the core agent loop.

    This is the main execution loop for any agent (orchestrator or specialist):
    1. Check context size, auto-compact if needed
    2. Checkpoint for D-Mail
    3. Call LLM with system prompt + conversation + tools
    4. Dispatch tool calls concurrently
    5. Update context
    6. Loop until the agent signals done or hits max_steps

    Args:
        agent: Agent definition (prompt, tools, max_steps).
        context: Conversation context (JSONL-backed).
        provider: LLM provider.
        tool_registry: Registry with available tools.
        on_step: Callback after each step (step_number, result).
        on_step_begin: Callback before each step (step_number, agent_name).
        on_text: Callback for streaming text content.
        on_tool_call: Callback when a tool call is received (id, name, arguments).
        on_tool_result: Callback when a tool result is ready (id, name, content, is_error).
        on_thinking: Callback for streaming thinking/reasoning text chunks.
        on_dmail: Callback when D-Mail time-travel is triggered (checkpoint_id, message).
        compact_fn: Optional compaction function for auto-compaction.
        compact_provider: Optional fast/cheap provider for compaction.
            Falls back to ``provider`` if not set.
    """
    # Get tool specs for this agent's allowed tools
    if agent.tools:
        tools_specs = tool_registry.get_specs(agent.tools)
    else:
        tools_specs = tool_registry.get_specs()

    step_no = 0
    while step_no < agent.max_steps:
        step_no += 1
        logger.info("Agent %s: step %d/%d", agent.name, step_no, agent.max_steps)

        # 1. Auto-compact if approaching context limit
        estimated = context.estimate_tokens()
        if (
            compact_fn
            and estimated + CONTEXT_RESERVE_TOKENS > provider.config.context_window
        ):
            logger.info("Auto-compacting context (%d tokens)", estimated)
            await compact_fn(context, provider, compact_provider=compact_provider)

        # 2. Checkpoint for D-Mail
        checkpoint_id = await context.checkpoint()

        # 2.5. Notify step begin BEFORE calling step
        if on_step_begin:
            on_step_begin(step_no, agent.name)

        # 3. Build messages and call LLM
        messages = context.get_messages()

        def _on_text_part(part: ContentPart) -> None:
            from reagent.llm.message import TextPart as TP

            if isinstance(part, TP) and on_text:
                on_text(part.text)

        def _on_tool_call_part(tc_id: str, name: str, arguments: str) -> None:
            if on_tool_call:
                on_tool_call(tc_id, name, arguments)

        def _on_tool_result_part(
            tc_id: str, name: str, content: str, is_error: bool
        ) -> None:
            if on_tool_result:
                on_tool_result(tc_id, name, content, is_error)

        def _on_thinking_part(text: str) -> None:
            if on_thinking:
                on_thinking(text)

        try:
            result = await step(
                provider=provider,
                system=agent.system_prompt,
                messages=messages,
                tools=tools_specs if tools_specs else None,
                tool_dispatch=tool_registry.dispatch,
                on_part=_on_text_part,
                on_tool_call=_on_tool_call_part,
                on_tool_result=_on_tool_result_part,
                on_thinking=_on_thinking_part,
            )
        except BackToTheFuture as dmail:
            logger.info(
                "D-Mail received! Reverting to checkpoint %d", dmail.checkpoint_id
            )
            if on_dmail:
                on_dmail(dmail.checkpoint_id, dmail.message)
            await context.revert_to(dmail.checkpoint_id)
            await context.append_system(
                f"[D-Mail from your future self]: {dmail.message}\n\n"
                "Use this knowledge to avoid repeating the same work. "
                "Continue with the task, applying what you now know."
            )
            continue
        except Exception as e:
            logger.error(
                "Agent %s: unrecoverable error at step %d: %s",
                agent.name,
                step_no,
                e,
                exc_info=True,
            )
            return TurnOutcome.ERROR

        # 4. Update context (shielded from cancellation)
        await asyncio.shield(context.grow(result.message, result.tool_results))

        # 5. Update token count from usage
        if result.usage.input_tokens > 0:
            context.token_count = result.usage.input_tokens

        # 6. Notify callback
        if on_step:
            on_step(step_no, result)

        # 7. Check stop conditions
        if not result.message.tool_calls:
            # No tool calls — agent is done
            logger.info("Agent %s completed after %d steps", agent.name, step_no)
            return TurnOutcome.COMPLETE

        # Continue loop (tool calls were handled, feed results back)

    logger.warning("Agent %s hit max steps (%d)", agent.name, agent.max_steps)
    return TurnOutcome.MAX_STEPS
