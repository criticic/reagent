"""Context management — compaction, pruning, and token budgeting.

Three-tier approach to keep context within token limits:

1. **Pruning**: Cheapest — drop tool result bodies from old messages,
   replace with "[pruned: N chars]". Keeps conversation structure intact.

2. **Compaction**: LLM-based — summarize old conversation into a compact
   system message, then drop the original messages. More expensive (one
   LLM call) but much more effective at reducing tokens.

3. **Truncation**: Already handled at the tool level (2000 lines / 50KB).
   This module handles context-level management above that.
"""

from __future__ import annotations

import logging
from typing import Any

from reagent.context import Context
from reagent.llm.message import (
    Message,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolResultPart,
)
from reagent.llm.provider import ChatProvider

logger = logging.getLogger(__name__)

# Pruning replaces tool results longer than this with a stub
PRUNE_THRESHOLD_CHARS = 500

# How many recent messages to protect from pruning
PRUNE_PROTECT_RECENT = 10

# Compaction summary prompt
COMPACTION_SYSTEM = """\
You are a context compactor for a binary analysis agent. Your job is to \
summarize the conversation so far into a compact, information-dense summary \
that preserves all critical details.

Rules:
- Preserve ALL addresses, function names, offsets, register values, and hex data.
- Preserve ALL hypotheses, findings, and their verification status.
- Preserve the analysis goal and current progress.
- Summarize tool outputs by their conclusions, not raw data.
- Use bullet points for density.
- Be precise and technical — this summary replaces the conversation history.
- Maximum 2000 words.
"""

COMPACTION_USER_TEMPLATE = """\
Summarize the following analysis conversation. Preserve all critical \
technical details (addresses, function names, findings, hypotheses). \
The summary will replace the conversation history.

---

{conversation}
"""


async def prune_context(context: Context) -> int:
    """Prune old tool results to save tokens.

    Replaces large tool result bodies with stubs while keeping the
    conversation structure (role, tool_call_id) intact. Protects
    recent messages from pruning.

    Returns the number of messages pruned.
    """
    pruned_count = 0
    cutoff = len(context.messages) - PRUNE_PROTECT_RECENT

    for i, msg in enumerate(context.messages):
        if i >= cutoff:
            break  # Protect recent messages

        # Only prune tool result messages and thinking parts
        if msg.role != "tool" and msg.role != "assistant":
            continue

        new_parts = []
        changed = False
        for part in msg.parts:
            if (
                isinstance(part, ToolResultPart)
                and len(part.content) > PRUNE_THRESHOLD_CHARS
            ):
                stub = f"[pruned: {len(part.content)} chars]"
                new_parts.append(
                    ToolResultPart(
                        tool_call_id=part.tool_call_id,
                        content=stub,
                        is_error=part.is_error,
                    )
                )
                changed = True
            elif isinstance(part, ThinkingPart):
                # Drop thinking parts from old messages — they're verbose
                # and not needed after the model has already acted on them.
                changed = True
            else:
                new_parts.append(part)

        if changed:
            context.messages[i] = Message(role=msg.role, parts=new_parts)
            pruned_count += 1

    if pruned_count > 0:
        logger.info("Pruned %d tool results from context", pruned_count)

    return pruned_count


async def compact_context(
    context: Context,
    provider: ChatProvider,
    compact_provider: ChatProvider | None = None,
    keep_recent: int = 6,
) -> str:
    """Compact old messages into a summary via LLM.

    Takes all messages except the most recent `keep_recent`, asks the
    LLM to summarize them, then replaces them with a single system
    message containing the summary.

    Args:
        context: The context to compact.
        provider: Primary LLM provider (used for context window calculation).
        compact_provider: Provider for generating summaries. Falls back to
            ``provider`` if not set. Use a fast/cheap model here to save cost.
        keep_recent: Number of recent messages to keep verbatim.

    Returns:
        The generated summary text.
    """
    summary_provider = compact_provider or provider

    if len(context.messages) <= keep_recent:
        logger.info("Context too small to compact (%d messages)", len(context.messages))
        return ""

    # Split: old messages to summarize, recent to keep
    old_messages = context.messages[:-keep_recent]
    recent_messages = context.messages[-keep_recent:]

    # Render old messages as text for the compaction prompt
    conversation_text = _render_messages_for_summary(old_messages)

    if not conversation_text.strip():
        return ""

    # Generate summary via LLM
    from reagent.llm.streaming import generate

    user_prompt = COMPACTION_USER_TEMPLATE.format(conversation=conversation_text)
    summary_messages = [Message.user(user_prompt)]

    result = await generate(
        provider=summary_provider,
        system=COMPACTION_SYSTEM,
        messages=summary_messages,
    )

    summary = result.message.text
    if not summary:
        logger.warning("Compaction produced empty summary")
        return ""

    logger.info(
        "Compacted %d messages into %d-char summary",
        len(old_messages),
        len(summary),
    )

    # Replace context: summary system message + recent messages
    summary_msg = Message.system(
        f"[Context compacted — summary of prior {len(old_messages)} messages]\n\n{summary}"
    )
    context.messages = [summary_msg] + recent_messages

    # Rewrite the JSONL file
    await context._rewrite_jsonl()

    return summary


async def auto_manage_context(
    context: Context,
    provider: ChatProvider,
    compact_provider: ChatProvider | None = None,
    target_tokens: int | None = None,
) -> str:
    """Automatically manage context size.

    Called by the agent loop when context is approaching the token limit.
    Strategy:
    1. Try pruning first (cheap, no LLM call)
    2. If still too large, compact (one LLM call via compact_provider)

    Args:
        context: The context to manage.
        provider: Primary LLM provider (for context window calculation).
        compact_provider: Provider for compaction summaries. Falls back to
            ``provider`` if not set. Use a fast/cheap model here to save cost.
        target_tokens: Target token count. Defaults to 70% of context window.

    Returns:
        Action taken: "none", "pruned", "compacted", or "pruned+compacted".
    """
    if target_tokens is None:
        target_tokens = int(provider.config.context_window * 0.7)

    current = context.estimate_tokens()
    if current <= target_tokens:
        return "none"

    actions = []

    # Step 1: Prune
    pruned = await prune_context(context)
    if pruned > 0:
        actions.append("pruned")

    # Check if pruning was enough
    current = context.estimate_tokens()
    if current <= target_tokens:
        return "+".join(actions) if actions else "none"

    # Step 2: Compact
    summary = await compact_context(
        context, provider, compact_provider=compact_provider
    )
    if summary:
        actions.append("compacted")

    return "+".join(actions) if actions else "none"


def _render_messages_for_summary(
    messages: list[Message], max_chars: int = 50000
) -> str:
    """Render messages as readable text for the compaction LLM.

    Truncates individual messages to avoid overwhelming the summarizer.
    """
    lines: list[str] = []
    total_chars = 0

    for msg in messages:
        if total_chars >= max_chars:
            lines.append("[... earlier messages omitted for brevity]")
            break

        role = msg.role.upper()

        for part in msg.parts:
            if isinstance(part, ThinkingPart):
                # Skip thinking parts — internal reasoning doesn't need
                # to be preserved in the compacted summary.
                continue

            if isinstance(part, TextPart):
                text = part.text[:2000] if len(part.text) > 2000 else part.text
                lines.append(f"[{role}]: {text}")
                total_chars += len(text)

            elif isinstance(part, ToolCallPart):
                lines.append(f"[{role} TOOL CALL]: {part.name}({part.arguments[:200]})")
                total_chars += 50 + len(part.name)

            elif isinstance(part, ToolResultPart):
                content = part.content
                if len(content) > 1000:
                    content = content[:1000] + f"... [{len(part.content)} chars total]"
                error_tag = " [ERROR]" if part.is_error else ""
                lines.append(f"[TOOL RESULT{error_tag}]: {content}")
                total_chars += len(content)

    return "\n\n".join(lines)
