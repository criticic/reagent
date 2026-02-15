"""Orchestrator — coordinates multi-agent analysis.

The orchestrator is the top-level controller that:
1. Breaks down analysis goals into subtasks
2. Dispatches subtasks to specialist subagents (triage, static, dynamic)
3. Collects results and updates the shared BinaryModel
4. Decides when the analysis is complete
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, ClassVar

from pydantic import BaseModel, Field

from reagent.agent.agent import Agent, AgentConfig, discover_agents
from reagent.agent.loop import agent_loop, TurnOutcome
from reagent.agent.registry import AgentRegistry
from reagent.context import Context
from reagent.llm.message import Message
from reagent.llm.provider import ChatProvider
from reagent.model import BinaryModel
from reagent.model.hypothesis import Observation, Hypothesis, Finding
from reagent.session.wire import Wire
from reagent.tool.base import BaseTool, ToolError, ToolOk, ToolResult
from reagent.tool.registry import ToolRegistry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool: dispatch_subagent
# ---------------------------------------------------------------------------


class DispatchSubagentParams(BaseModel):
    agent: str = Field(
        description=(
            "Name of the subagent to dispatch. Available:\n"
            "- 'triage': Quick binary identification and recon\n"
            "- 'static': Deep static analysis (decompile, xrefs)\n"
            "- 'dynamic': Runtime analysis (debug, breakpoints)\n"
            "- 'coding': Write/run Python scripts to verify findings computationally"
        ),
    )
    task: str = Field(
        description=(
            "Clear, specific task description for the subagent. "
            "Be specific: include addresses, function names, and what to look for. "
            "Bad: 'analyze the binary'. "
            "Good: 'Decompile the function at 0x401000 and determine if it validates user input'."
        ),
    )
    context: str = Field(
        default="",
        description=(
            "Additional context for the subagent: relevant findings, "
            "hypotheses to verify, addresses to focus on."
        ),
    )


class DispatchSubagentTool(BaseTool[DispatchSubagentParams]):
    """Dispatch a task to a specialist subagent."""

    name: ClassVar[str] = "dispatch_subagent"
    description: ClassVar[str] = (
        "Dispatch a task to a specialist subagent. Available agents: "
        "'triage' (binary recon), 'static' (decompilation/xrefs), "
        "'dynamic' (debugging/runtime), 'coding' (write/run Python scripts "
        "for computational verification). The subagent runs independently "
        "and returns its findings. Include specific details in the task."
    )
    param_model: ClassVar[type[BaseModel]] = DispatchSubagentParams

    def __init__(
        self,
        agent_registry: AgentRegistry,
        tool_registry: ToolRegistry,
        provider: ChatProvider,
        binary_model: BinaryModel,
        binary_path: str,
        wire: Wire | None = None,
        on_subagent_text: Callable[[str, str], None] | None = None,
    ) -> None:
        self._agent_registry = agent_registry
        self._tool_registry = tool_registry
        self._provider = provider
        self._binary_model = binary_model
        self._binary_path = binary_path
        self._wire = wire
        self._on_subagent_text = on_subagent_text

    async def execute(self, params: DispatchSubagentParams) -> ToolResult:
        agent = self._agent_registry.get(params.agent)
        if not agent:
            available = self._agent_registry.names()
            return ToolError(
                output=(
                    f"Unknown agent '{params.agent}'. "
                    f"Available agents: {', '.join(available)}"
                )
            )

        logger.info(
            "Orchestrator dispatching '%s' subagent: %s",
            params.agent,
            params.task[:100],
        )

        try:
            result_text = await _run_subagent(
                agent=agent,
                task=params.task,
                context_text=params.context,
                provider=self._provider,
                tool_registry=self._tool_registry,
                binary_model=self._binary_model,
                binary_path=self._binary_path,
                wire=self._wire,
                on_subagent_text=self._on_subagent_text,
                agent_name=params.agent,
            )

            return ToolOk(
                output=result_text,
                brief=f"subagent:{params.agent} completed",
            )
        except Exception as e:
            logger.error("Subagent '%s' failed: %s", params.agent, e)
            return ToolError(
                output=f"Subagent '{params.agent}' failed: {e}",
                brief=f"subagent:{params.agent} failed",
            )


# ---------------------------------------------------------------------------
# Tool: update_model
# ---------------------------------------------------------------------------


class UpdateModelParams(BaseModel):
    action: str = Field(
        description=(
            "What to add to the knowledge base:\n"
            "- 'observation': A raw fact (e.g., 'Function main calls check_password')\n"
            "- 'hypothesis': An interpretive claim to verify (e.g., 'check_password uses strcmp for validation')\n"
            "- 'finding': A verified fact with evidence"
        ),
    )
    description: str = Field(
        description="Description of the observation, hypothesis, or finding.",
    )
    category: str = Field(
        default="general",
        description=(
            "Category: 'vulnerability', 'authentication', 'crypto', "
            "'network', 'file_io', 'general', 'control_flow'"
        ),
    )
    address: str = Field(
        default="",
        description="Related address (e.g., '0x401000'). Optional.",
    )
    confidence: float = Field(
        default=0.5,
        description="Confidence level for hypotheses (0.0 to 1.0). Default 0.5.",
    )
    evidence: str = Field(
        default="",
        description="Evidence supporting a finding (e.g., 'confirmed via breakpoint at 0x401000, rax=0x1').",
    )
    hypothesis_id: str = Field(
        default="",
        description="For findings: the hypothesis ID being confirmed. Use this to promote a hypothesis.",
    )


class UpdateModelTool(BaseTool[UpdateModelParams]):
    """Update the shared binary analysis knowledge base."""

    name: ClassVar[str] = "update_model"
    description: ClassVar[str] = (
        "Record observations, hypotheses, or findings in the shared knowledge base. "
        "Use 'observation' for raw facts, 'hypothesis' for claims to verify, "
        "and 'finding' for verified facts. All agents should use this to track "
        "analysis progress. Findings appear in the sidebar in real-time."
    )
    param_model: ClassVar[type[BaseModel]] = UpdateModelParams

    def __init__(self, binary_model: BinaryModel, wire: Wire | None = None) -> None:
        self._model = binary_model
        self._wire = wire

    async def execute(self, params: UpdateModelParams) -> ToolResult:
        addr = int(params.address, 16) if params.address.startswith("0x") else None

        # Normalize the action — LLMs sometimes send "finding, confirmation:"
        # or "observation (raw)" instead of just the action name.
        raw_action = params.action.strip().lower()
        action = raw_action.split(",")[0].split("(")[0].split(":")[0].strip()
        # Also handle common synonyms
        if action in ("observe", "obs", "note"):
            action = "observation"
        elif action in ("hypothesize", "hyp", "claim", "guess"):
            action = "hypothesis"
        elif action in ("find", "confirm", "verify", "verified", "result"):
            action = "finding"

        if action == "observation":
            obs = Observation(
                type=params.category,
                data=params.description,
                address=addr,
            )
            obs_id = self._model.add_observation(obs)
            if self._wire:
                self._wire.send_observation(params.description, params.category)
            return ToolOk(
                output=f"Observation recorded: [{obs_id}] {params.description}",
                brief=f"observation: {obs_id}",
            )

        elif action == "hypothesis":
            hyp = Hypothesis(
                description=params.description,
                category=params.category,
                confidence=params.confidence,
                address=addr,
                evidence=[params.evidence] if params.evidence else [],
            )
            hyp_id = self._model.add_hypothesis(hyp)
            if self._wire:
                self._wire.send_hypothesis(
                    params.description,
                    status="proposed",
                    confidence=params.confidence,
                    hyp_id=hyp_id,
                )
            return ToolOk(
                output=f"Hypothesis recorded: [{hyp_id}] {params.description} (confidence: {params.confidence})",
                brief=f"hypothesis: {hyp_id}",
            )

        elif action == "finding":
            # If promoting a hypothesis
            if params.hypothesis_id:
                finding = self._model.promote_hypothesis(
                    params.hypothesis_id,
                    agent="orchestrator",
                    details={"evidence": params.evidence},
                )
                if finding:
                    if self._wire:
                        self._wire.send_finding(
                            finding.description,
                            category=finding.category,
                            verified=True,
                        )
                        # Also emit hypothesis update (now confirmed)
                        self._wire.send_hypothesis(
                            finding.description,
                            status="confirmed",
                            confidence=1.0,
                            hyp_id=params.hypothesis_id,
                        )
                    return ToolOk(
                        output=f"Hypothesis {params.hypothesis_id} promoted to finding: [{finding.id}] {finding.description}",
                        brief=f"finding (promoted): {finding.id}",
                    )
                else:
                    return ToolError(
                        output=f"Hypothesis '{params.hypothesis_id}' not found."
                    )

            finding = Finding(
                description=params.description,
                category=params.category,
                addresses=[addr] if addr else [],
                evidence=[params.evidence] if params.evidence else [],
                verified=True,
                verified_by="orchestrator",
            )
            fid = self._model.add_finding(finding)
            if self._wire:
                self._wire.send_finding(
                    params.description,
                    category=params.category,
                    verified=True,
                )
            return ToolOk(
                output=f"Finding recorded: [{fid}] {params.description}",
                brief=f"finding: {fid}",
            )

        else:
            return ToolError(
                output=f"Unknown action '{params.action}' (parsed as '{action}'). Use 'observation', 'hypothesis', or 'finding'."
            )


# ---------------------------------------------------------------------------
# Subagent execution
# ---------------------------------------------------------------------------


async def _run_subagent(
    agent: Agent,
    task: str,
    context_text: str,
    provider: ChatProvider,
    tool_registry: ToolRegistry,
    binary_model: BinaryModel,
    binary_path: str,
    wire: Wire | None = None,
    on_subagent_text: Callable[[str, str], None] | None = None,
    agent_name: str = "",
) -> str:
    """Run a subagent with its own context.

    The subagent gets:
    - Its own system prompt (from the agent definition)
    - A subset of tools (from its config)
    - A fresh context seeded with the task + binary model summary
    - The BinaryModel summary injected into the prompt

    When a ``wire`` is provided, full subagent activity (steps, tool calls,
    tool results, thinking) is streamed to the wire in real-time.

    Args:
        wire: Optional Wire bus for streaming all subagent events.
        on_subagent_text: Legacy callback (agent_name, text) — used when
            there is no wire (plain CLI mode).
        agent_name: Name of the agent (for the callback).

    Returns the final text output from the subagent.
    """
    # Create a temporary context for the subagent
    tmp_dir = tempfile.mkdtemp(prefix="reagent-subagent-")
    context_path = Path(tmp_dir) / f"{agent.name}.jsonl"
    context = Context(path=context_path)

    # Build system prompt with binary model context
    model_summary = binary_model.summary(for_agent=agent.name)
    system_prompt = (
        f"{agent.system_prompt}\n\n"
        f"## Analysis Target\n"
        f"Binary: {binary_path}\n\n"
        f"## Current Knowledge\n"
        f"{model_summary if model_summary.strip() else 'No prior analysis data.'}\n"
    )

    # Create a tool registry subset for this agent
    subagent_tools = tool_registry.subset(agent.tools) if agent.tools else tool_registry

    # Seed the context with the task
    user_msg = f"## Task\n{task}"
    if context_text:
        user_msg += f"\n\n## Additional Context\n{context_text}"
    await context.append(Message.user(user_msg))

    # Build callbacks
    collected_text: list[str] = []
    name = agent_name or agent.name

    # Try to use the wire for full streaming visibility
    if wire is not None:
        from reagent.tui.bridge import make_subagent_callbacks

        cbs = make_subagent_callbacks(wire, name)
        cbs.on_begin()

        def _on_text_cb(text: str) -> None:
            collected_text.append(text)
            cbs.on_text(text)

        outcome = await agent_loop(
            agent=agent,
            context=context,
            provider=provider,
            tool_registry=subagent_tools,
            on_text=_on_text_cb,
            on_step=cbs.on_step,
            on_step_begin=cbs.on_step_begin,
            on_tool_call=cbs.on_tool_call,
            on_tool_result=cbs.on_tool_result,
            on_thinking=cbs.on_thinking,
            on_dmail=cbs.on_dmail,
        )

        cbs.on_end()
    else:
        # Fallback: legacy text-only callback (plain CLI without wire)
        def _on_text_cb_legacy(text: str) -> None:
            collected_text.append(text)
            if on_subagent_text:
                on_subagent_text(name, text)

        outcome = await agent_loop(
            agent=agent,
            context=context,
            provider=provider,
            tool_registry=subagent_tools,
            on_text=_on_text_cb_legacy,
        )

    # Extract the final assistant message(s)
    final_text = "".join(collected_text)
    if not final_text.strip():
        # Fall back to extracting from context messages
        for msg in reversed(context.messages):
            if msg.role == "assistant":
                from reagent.llm.message import TextPart

                text_parts = [p for p in msg.parts if isinstance(p, TextPart)]
                if text_parts:
                    final_text = "".join(p.text for p in text_parts)
                    break

    # Add metadata about the run
    result = (
        f"## Subagent: {agent.name}\n"
        f"## Task: {task}\n"
        f"## Outcome: {outcome.value}\n\n"
        f"{final_text}"
    )

    # Clean up temp context
    try:
        os.unlink(context_path)
        os.rmdir(tmp_dir)
    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# Orchestrator setup
# ---------------------------------------------------------------------------


@dataclass
class OrchestratorSetup:
    """All the pieces needed to run the orchestrator."""

    orchestrator_agent: Agent
    agent_registry: AgentRegistry
    tool_registry: ToolRegistry
    binary_model: BinaryModel
    provider: ChatProvider


def setup_orchestrator(
    binary_path: str,
    goal: str,
    provider: ChatProvider,
    tool_registry: ToolRegistry,
    binary_model: BinaryModel,
    agents_dir: str | None = None,
    on_subagent_text: Callable[[str, str], None] | None = None,
    wire: Wire | None = None,
) -> OrchestratorSetup:
    """Set up the orchestrator with all its components.

    Args:
        binary_path: Path to the binary to analyze.
        goal: Analysis goal.
        provider: LLM provider.
        tool_registry: Global tool registry (tools already registered).
        binary_model: Shared BinaryModel.
        agents_dir: Directory containing agent definitions.
        on_subagent_text: Callback (agent_name, text) for streaming subagent output.

    Returns:
        OrchestratorSetup with everything wired up.
    """
    # Discover agent definitions
    if agents_dir is None:
        # Look in the project's agents/ directory
        project_root = Path(__file__).parent.parent.parent.parent
        agents_dir = str(project_root / "agents")

    agent_registry = AgentRegistry()
    agent_registry.discover([agents_dir])

    # Register orchestrator-specific tools
    dispatch_tool = DispatchSubagentTool(
        agent_registry=agent_registry,
        tool_registry=tool_registry,
        provider=provider,
        binary_model=binary_model,
        binary_path=binary_path,
        wire=wire,
        on_subagent_text=on_subagent_text,
    )
    model_tool = UpdateModelTool(binary_model, wire=wire)

    tool_registry.register(dispatch_tool)
    tool_registry.register(model_tool)

    # Get or create the orchestrator agent
    orchestrator = agent_registry.get("orchestrator")
    if not orchestrator:
        # Fall back to a default orchestrator
        orchestrator = Agent.from_dict(
            {
                "name": "orchestrator",
                "description": "Analysis orchestrator",
                "mode": "primary",
                "tools": ["think", "dispatch_subagent", "update_model", "shell"],
                "max_steps": 30,
            },
            system_prompt=_default_orchestrator_prompt(binary_path, goal),
        )

    # Build the orchestrator system prompt with goal context
    if orchestrator.system_prompt:
        orchestrator.system_prompt = (
            f"{orchestrator.system_prompt}\n\n"
            f"## Current Goal\n{goal}\n\n"
            f"## Binary\n{binary_path}\n"
        )
    else:
        orchestrator.system_prompt = _default_orchestrator_prompt(binary_path, goal)

    return OrchestratorSetup(
        orchestrator_agent=orchestrator,
        agent_registry=agent_registry,
        tool_registry=tool_registry,
        binary_model=binary_model,
        provider=provider,
    )


def _default_orchestrator_prompt(binary_path: str, goal: str) -> str:
    return (
        f"You are the orchestrator of a binary analysis system. "
        f"Analyze the binary at `{binary_path}` and accomplish this goal: {goal}\n\n"
        f"You have full autonomy over how to approach this. "
        f"Available subagents: triage (recon), static (decompilation/xrefs), "
        f"dynamic (debugging/runtime), coding (Python scripts for computation).\n"
        f"Available tools: think, dispatch_subagent, update_model, shell.\n\n"
        f"Adapt your strategy based on what you discover. "
        f"Always start by running the binary to observe its behavior, then adapt freely. "
        f"Record observations, hypotheses, and verified findings with update_model. "
        f"Verify claims before reporting them as findings."
    )
