"""CLI entry point for reagent."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

import typer

from reagent.config import ReagentConfig
from reagent.context.management import auto_manage_context

if TYPE_CHECKING:
    from reagent.agent.orchestrator import OrchestratorSetup
    from reagent.context import Context
    from reagent.llm.provider import ChatProvider
    from reagent.model import BinaryModel
    from reagent.pty.manager import PTYManager
    from reagent.session.wire import Wire
    from reagent.tool.registry import ToolRegistry

app = typer.Typer(
    name="reagent",
    help="The autonomous AI agent for binary analysis and vulnerability research.",
    no_args_is_help=True,
)


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _mask_binary(binary_path: str) -> tuple[str, Path]:
    """Copy the binary to a temp path with an anonymized name.

    Returns (masked_path, temp_dir) so the caller can clean up.
    The masked name is ``target_<hash>`` where hash is derived from the
    original filename (not the content — fast, deterministic).

    Uses a hard copy (not symlink) so that ``ls -la`` and ``readlink``
    cannot reveal the original filename to the agent.
    """
    name_hash = hashlib.sha256(os.path.basename(binary_path).encode()).hexdigest()[:8]
    tmp_dir = Path(tempfile.mkdtemp(prefix="reagent_mask_"))
    masked_name = f"target_{name_hash}"
    masked_path = tmp_dir / masked_name
    shutil.copy(binary_path, masked_path)
    return str(masked_path), tmp_dir


def _cleanup_mask(tmp_dir: Path | None) -> None:
    """Remove the temp directory created by _mask_binary."""
    if tmp_dir is None:
        return
    try:
        shutil.rmtree(tmp_dir)
    except Exception:
        pass


@dataclass
class AnalysisPipeline:
    """All components needed to run an analysis — shared between CLI and TUI."""

    provider: ChatProvider
    compact_provider: ChatProvider  # Fast/cheap provider for context compaction
    pty_manager: PTYManager
    tool_registry: ToolRegistry
    binary_model: BinaryModel
    orch_setup: OrchestratorSetup
    context: Context
    context_path: Path


def _build_pipeline(
    binary_path: str,
    goal: str,
    config: ReagentConfig,
    on_subagent_text: Callable[[str, str], None] | None = None,
    wire: Wire | None = None,
) -> AnalysisPipeline:
    """Set up all components for an analysis run.

    This is synchronous setup — no async needed.
    """
    from reagent.agent.orchestrator import setup_orchestrator
    from reagent.context import Context
    from reagent.llm.message import Message
    from reagent.llm.provider import create_provider
    from reagent.model import BinaryModel, TargetInfo
    from reagent.pty.manager import PTYManager
    from reagent.skill import SkillRegistry
    from reagent.tool.builtin.dmail import SendDMailTool
    from reagent.tool.builtin.read_file import ReadFileTool
    from reagent.tool.builtin.shell import ShellTool
    from reagent.tool.builtin.skill import ActivateSkillTool
    from reagent.tool.builtin.think import ThinkTool
    from reagent.tool.builtin.write_file import WriteFileTool
    from reagent.tool.registry import ToolRegistry

    # LLM provider
    provider = create_provider(
        model=config.llm.model,
        temperature=config.llm.temperature,
        max_tokens=config.llm.max_tokens,
        context_window=config.llm.context_window,
        reasoning_effort=config.llm.reasoning_effort,
    )

    # Fast/cheap provider for context compaction (uses fast_model)
    compact_provider = create_provider(
        model=config.llm.fast_model,
        temperature=0.2,  # Low temperature for deterministic summaries
        max_tokens=config.llm.max_tokens,
        context_window=config.llm.context_window,
        reasoning_effort=config.llm.fast_reasoning_effort,
    )

    # PTY manager
    pty_manager = PTYManager(wire=wire)

    # Tool registry
    cwd = os.path.dirname(binary_path)
    tool_registry = ToolRegistry()

    # Skill registry
    skills_dir = os.path.abspath(config.skills_dir) if config.skills_dir else None
    skill_registry = (
        SkillRegistry(Path(skills_dir))
        if skills_dir and os.path.isdir(skills_dir)
        else None
    )

    builtin_tools = [
        ShellTool(cwd=cwd, pty_manager=pty_manager),
        ReadFileTool(cwd=cwd),
        WriteFileTool(cwd=cwd),
        ThinkTool(),
        SendDMailTool(),
    ]
    if skill_registry and skill_registry.list_skills():
        builtin_tools.append(ActivateSkillTool(registry=skill_registry))

    tool_registry.register_many(builtin_tools)

    # Binary model
    binary_model = BinaryModel(target=TargetInfo(path=binary_path))

    # RE-specific tools (after binary_model so FileInfoTool can populate it)
    _register_re_tools(
        tool_registry, binary_path, pty_manager, binary_model=binary_model, wire=wire
    )

    # Agents directory
    agents_dir: str | None = None
    if config.agents_dir:
        candidate = os.path.abspath(config.agents_dir)
        if os.path.isdir(candidate):
            agents_dir = candidate

    # Default subagent text callback (legacy fallback when no wire)
    if on_subagent_text is None and wire is None:
        _default_cb = lambda agent_name, text: print(text, end="", flush=True)
        on_subagent_text = _default_cb

    # Orchestrator
    orch_setup = setup_orchestrator(
        binary_path=binary_path,
        goal=goal,
        provider=provider,
        tool_registry=tool_registry,
        binary_model=binary_model,
        agents_dir=agents_dir,
        on_subagent_text=on_subagent_text,
        wire=wire,
        compact_fn=auto_manage_context,
        compact_provider=compact_provider,
    )

    # Context / session
    session_dir = os.path.expanduser(config.session_dir)
    os.makedirs(session_dir, exist_ok=True)
    session_id = hashlib.sha256(f"{binary_path}:{goal}".encode()).hexdigest()[:12]
    context_path = Path(session_dir) / f"{session_id}.jsonl"
    context = Context(path=context_path)

    return AnalysisPipeline(
        provider=provider,
        compact_provider=compact_provider,
        pty_manager=pty_manager,
        tool_registry=tool_registry,
        binary_model=binary_model,
        orch_setup=orch_setup,
        context=context,
        context_path=context_path,
    )


@app.command()
def analyze(
    binary: str = typer.Argument(help="Path to the binary to analyze."),
    goal: str = typer.Option(
        ...,
        "--goal",
        "-g",
        help="What to look for (e.g., 'Find the license key validation logic').",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        "-m",
        help="LLM model to use (default: from env/config).",
    ),
    mask: bool = typer.Option(
        False,
        "--mask",
        "-M",
        help="Mask the binary name to avoid agent bias (copies to anonymized temp path).",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Enable debug logging."
    ),
    config_file: str | None = typer.Option(
        None, "--config", "-c", help="Config file path."
    ),
) -> None:
    """Analyze a binary with an autonomous RE agent (plain CLI output)."""
    setup_logging(verbose)

    binary_path = os.path.abspath(binary)
    if not os.path.isfile(binary_path):
        typer.echo(f"Error: Binary not found: {binary_path}", err=True)
        raise typer.Exit(1)

    config = ReagentConfig.load(config_file)
    if model:
        config.llm.model = model

    # Mask the binary name if requested
    mask_tmp_dir: Path | None = None
    analysis_path = binary_path
    if mask:
        analysis_path, mask_tmp_dir = _mask_binary(binary_path)

    typer.echo("reagent v0.1.0")
    typer.echo(f"Target: {binary_path}")
    if mask:
        typer.echo(f"Masked as: {analysis_path}")
    typer.echo(f"Goal: {goal}")
    typer.echo(f"Model: {config.llm.model}")
    typer.echo(f"Fast model: {config.llm.fast_model}")
    if config.llm.reasoning_effort:
        typer.echo(f"Reasoning effort: {config.llm.reasoning_effort}")
    if config.llm.fast_reasoning_effort:
        typer.echo(f"Fast reasoning effort: {config.llm.fast_reasoning_effort}")
    _show_api_key_status(config)
    typer.echo("---")

    try:
        asyncio.run(_run_analysis(analysis_path, goal, config))
    finally:
        _cleanup_mask(mask_tmp_dir)


def _show_api_key_status(config: ReagentConfig) -> None:
    """Print which API key is active so the user can verify the right one is loaded."""
    provider_prefix = config.llm.model.split("/")[0] if "/" in config.llm.model else ""
    key_env_map = {
        "anthropic": "ANTHROPIC_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "openai": "OPENAI_API_KEY",
    }
    env_var = key_env_map.get(provider_prefix, "")
    if env_var:
        key = os.environ.get(env_var, "")
        if key:
            masked = f"{key[:8]}...{key[-4:]}" if len(key) > 12 else "***"
            typer.echo(f"API key: {env_var} = {masked}")
        else:
            typer.echo(
                f"WARNING: {env_var} is not set! Set it in .env or your shell.",
                err=True,
            )
    else:
        typer.echo(f"Provider: {provider_prefix or 'unknown'} (check API key manually)")


async def _run_analysis(binary_path: str, goal: str, config: ReagentConfig) -> None:
    """Run the analysis pipeline with plain CLI output."""
    from reagent.agent.loop import agent_loop
    from reagent.llm.message import Message
    from reagent.session.wire import EventType, Wire, WireEvent

    wire = Wire()

    pipeline = _build_pipeline(binary_path, goal, config, wire=wire)

    # Track state for thinking formatting
    thinking_started = False
    in_subagent: str | None = None

    # --- Wire consumer (async background task) ---
    async def _consume_wire() -> None:
        nonlocal thinking_started, in_subagent
        queue = wire.subscribe()
        while True:
            event = await queue.get()
            if event is None:
                break

            d = event.data
            agent = d.get("agent")

            if event.type == EventType.SUBAGENT_BEGIN:
                in_subagent = d.get("agent", "?")
                print(f"\n--- Subagent: {in_subagent} ---", flush=True)

            elif event.type == EventType.SUBAGENT_END:
                sa = d.get("agent", "?")
                print(f"--- {sa} done ---", flush=True)
                in_subagent = None

            elif event.type == EventType.STEP_BEGIN:
                thinking_started = False
                step_no = d.get("step", 0)
                agent_label = d.get("agent", "")
                prefix = f"  [{agent_label}] " if agent else ""
                print(f"\n{prefix}[Step {step_no}] ({agent_label})", flush=True)

            elif event.type == EventType.THINKING:
                text = d.get("text", "")
                if not thinking_started:
                    prefix = f"  [{agent}] " if agent else "  "
                    print(f"{prefix}[thinking] ", end="", flush=True)
                    thinking_started = True
                print(text, end="", flush=True)

            elif event.type == EventType.TEXT:
                text = d.get("text", "")
                if thinking_started:
                    print(flush=True)  # newline after thinking block
                    thinking_started = False
                print(text, end="", flush=True)

            elif event.type == EventType.TOOL_CALL:
                name = d.get("name", "?")
                arguments = d.get("arguments", "")
                prefix = f"  [{agent}] " if agent else "  "
                # Show the actual command for shell/debug_eval
                detail = ""
                if name in ("shell", "debug_eval") and arguments:
                    try:
                        args = json.loads(arguments)
                        detail = f" {args.get('command', '')}"
                    except (json.JSONDecodeError, AttributeError):
                        pass
                print(f"{prefix}> {name}{detail}", flush=True)

            elif event.type == EventType.TOOL_RESULT:
                name = d.get("name", "?")
                content = d.get("content", "")
                is_error = d.get("is_error", False)
                status = "ERROR" if is_error else "OK"
                first_line = content.split("\n")[0][:100] if content else status
                prefix = f"  [{agent}] " if agent else "  "
                print(f"{prefix}< {name}: {first_line}", flush=True)

            elif event.type == EventType.OBSERVATION:
                desc = d.get("description", "")
                category = d.get("category", "general")
                prefix = f"  [{agent}] " if agent else "  "
                print(f"{prefix}[observation] ({category}) {desc}", flush=True)

            elif event.type == EventType.HYPOTHESIS:
                desc = d.get("description", "")
                status = d.get("status", "proposed")
                confidence = d.get("confidence", 0.0)
                prefix = f"  [{agent}] " if agent else "  "
                print(
                    f"{prefix}[hypothesis] [{status}] {desc} "
                    f"(confidence: {confidence:.0%})",
                    flush=True,
                )

            elif event.type == EventType.FINDING:
                desc = d.get("description", "")
                category = d.get("category", "")
                verified = d.get("verified", False)
                badge = "verified" if verified else "unverified"
                prefix = f"  [{agent}] " if agent else "  "
                print(
                    f"{prefix}[FINDING] [{badge}] {desc} ({category})",
                    flush=True,
                )

            elif event.type == EventType.DMAIL:
                message = d.get("message", "Time-travel triggered")
                print(f"\n[D-MAIL] {message}", flush=True)

            elif event.type == EventType.COMPACTION:
                action = d.get("action", "compacted")
                print(f"\n  [context {action}]", flush=True)

            elif event.type == EventType.STATUS:
                tokens = d.get("tokens")
                if tokens and tokens > 0:
                    prefix = f"  [{agent}] " if agent else "  "
                    print(f"{prefix}tokens: {tokens:,}", flush=True)

            elif event.type == EventType.ERROR:
                error = d.get("error", "Unknown error")
                print(f"\nERROR: {error}", flush=True)

            elif event.type == EventType.PTY_EXIT:
                session_id = d.get("session_id", "?")
                title = d.get("title", "")
                exit_code = d.get("exit_code")
                label = title or session_id
                code_str = str(exit_code) if exit_code is not None else "?"
                print(f"\n  [pty-exit] {label} (code={code_str})", flush=True)

        wire.unsubscribe(queue)

    # Start wire consumer
    consumer_task = asyncio.create_task(_consume_wire())

    # CLI callbacks — emit events onto the wire
    from reagent.tui.bridge import (
        make_on_dmail,
        make_on_step,
        make_on_step_begin,
        make_on_text,
        make_on_thinking,
        make_on_tool_call,
        make_on_tool_result,
    )

    typer.echo(f"Agents: {', '.join(pipeline.orch_setup.agent_registry.names())}")
    typer.echo(f"Tools: {', '.join(pipeline.orch_setup.tool_registry.names())}")
    typer.echo("---")

    # Seed context
    await pipeline.context.append(
        Message.user(
            f"Analyze the binary at `{binary_path}` and accomplish this goal: {goal}\n\n"
            f"Start by examining the binary to understand what it is, then work towards the goal."
        )
    )

    outcome = await agent_loop(
        agent=pipeline.orch_setup.orchestrator_agent,
        context=pipeline.context,
        provider=pipeline.provider,
        tool_registry=pipeline.orch_setup.tool_registry,
        on_text=make_on_text(wire),
        on_step=make_on_step(wire),
        on_step_begin=make_on_step_begin(wire),
        on_tool_call=make_on_tool_call(wire),
        on_tool_result=make_on_tool_result(wire),
        on_thinking=make_on_thinking(wire),
        on_dmail=make_on_dmail(wire),
        compact_fn=auto_manage_context,
        compact_provider=pipeline.compact_provider,
    )

    await pipeline.pty_manager.cleanup()

    # Signal wire close and wait for consumer to finish
    wire.close()
    await consumer_task

    # Summary
    print(f"\n---\nAnalysis complete. Outcome: {outcome.value}")
    print(f"Session saved to: {pipeline.context_path}")

    if pipeline.binary_model.findings:
        print(f"\n## Findings ({len(pipeline.binary_model.findings)})")
        for finding in pipeline.binary_model.findings:
            print(f"  [{finding.id}] {finding.description}")
    if pipeline.binary_model.hypotheses:
        unverified = [
            h for h in pipeline.binary_model.hypotheses if h.status == "proposed"
        ]
        if unverified:
            print(f"\n## Unverified Hypotheses ({len(unverified)})")
            for h in unverified:
                print(f"  - {h.description} (confidence: {h.confidence})")


@app.command()
def tui(
    binary: str = typer.Argument(help="Path to the binary to analyze."),
    goal: str = typer.Option(
        ...,
        "--goal",
        "-g",
        help="What to look for (e.g., 'Find the license key validation logic').",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        "-m",
        help="LLM model to use (default: from env/config).",
    ),
    mask: bool = typer.Option(
        False,
        "--mask",
        "-M",
        help="Mask the binary name to avoid agent bias (copies to anonymized temp path).",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Enable debug logging."
    ),
    config_file: str | None = typer.Option(
        None, "--config", "-c", help="Config file path."
    ),
) -> None:
    """Analyze a binary with the interactive TUI."""
    # Don't use setup_logging() here — it adds a stderr StreamHandler that
    # corrupts the Textual display.  Just set the log level; the TUI app
    # installs its own handler on mount that routes logs to the status bar.
    logging.getLogger().setLevel(logging.DEBUG if verbose else logging.INFO)
    # Remove any handlers that basicConfig may have added in a prior call
    for h in logging.getLogger().handlers[:]:
        logging.getLogger().removeHandler(h)

    binary_path = os.path.abspath(binary)
    if not os.path.isfile(binary_path):
        typer.echo(f"Error: Binary not found: {binary_path}", err=True)
        raise typer.Exit(1)

    config = ReagentConfig.load(config_file)
    if model:
        config.llm.model = model

    # Mask the binary name if requested
    mask_tmp_dir: Path | None = None
    analysis_path = binary_path
    if mask:
        analysis_path, mask_tmp_dir = _mask_binary(binary_path)

    from reagent.session.wire import Wire
    from reagent.tui.app import ReagentApp
    from reagent.tui.bridge import (
        make_on_step,
        make_on_step_begin,
        make_on_subagent_text,
        make_on_text,
        make_on_thinking,
        make_on_tool_call,
        make_on_tool_result,
    )

    wire = Wire()

    pipeline = _build_pipeline(
        analysis_path,
        goal,
        config,
        on_subagent_text=make_on_subagent_text(wire),
        wire=wire,
    )

    tui_app = ReagentApp(
        binary_path=analysis_path,
        goal=goal,
        wire=wire,
        pipeline=pipeline,
        on_text_cb=make_on_text(wire),
        on_step_cb=make_on_step(wire),
        on_step_begin_cb=make_on_step_begin(wire),
        on_tool_call_cb=make_on_tool_call(wire),
        on_tool_result_cb=make_on_tool_result(wire),
        on_thinking_cb=make_on_thinking(wire),
    )

    try:
        tui_app.run()
    finally:
        _cleanup_mask(mask_tmp_dir)


def _register_re_tools(
    registry: ToolRegistry,
    binary_path: str,
    pty_manager: PTYManager,
    binary_model: BinaryModel | None = None,
    wire: Wire | None = None,
) -> None:
    """Try to register RE-specific tools. Silently skip if dependencies missing."""

    try:
        from reagent.re.rizin import (
            DecompileTool,
            DisassembleTool,
            FunctionsTool,
            SearchTool,
            SectionsTool,
            StringsTool,
            XrefsTool,
        )

        registry.register_many(
            [
                DisassembleTool(binary_path),
                DecompileTool(binary_path),
                FunctionsTool(binary_path),
                XrefsTool(binary_path),
                StringsTool(binary_path),
                SectionsTool(binary_path),
                SearchTool(binary_path),
            ]
        )
    except ImportError:
        pass

    try:
        from reagent.re.file_info import FileInfoTool

        registry.register(
            FileInfoTool(
                binary_path=binary_path,
                binary_model=binary_model,
                wire=wire,
            )
        )
    except ImportError:
        pass

    try:
        from reagent.re.debugger import create_debugger_tools

        cwd = os.path.dirname(binary_path)
        _debug_registry, debug_tools = create_debugger_tools(pty_manager, cwd=cwd)
        registry.register_many(debug_tools)
    except ImportError:
        pass


def main() -> None:
    app()


if __name__ == "__main__":
    main()
