"""Main Textual application for reagent TUI."""

from __future__ import annotations

import logging
import json
import os
from typing import TYPE_CHECKING, Callable

from rich.markup import escape
from rich.panel import Panel
from rich.text import Text

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.timer import Timer
from textual.widgets import (
    Footer,
    Header,
    Label,
    Markdown,
    Static,
    TabbedContent,
    TabPane,
)

from reagent.session.wire import EventType, Wire, WireEvent

if TYPE_CHECKING:
    from reagent.cli import AnalysisPipeline
    from reagent.llm.streaming import StepResult

logger = logging.getLogger(__name__)

# Braille spinner frames (matches OpenCode style)
_SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

# Tool display icons (like OpenCode)
_TOOL_ICONS: dict[str, str] = {
    "shell": "$",
    "read_file": "→",
    "write_file": "←",
    "disassemble": "→",
    "decompile": "→",
    "functions": "→",
    "xrefs": "→",
    "strings": "→",
    "sections": "→",
    "search": "✱",
    "file_info": "→",
    "dispatch_subagent": "#",
    "update_model": "◈",
    "think": "◇",
    "send_dmail": "⧗",
    "activate_skill": "→",
    "task": "#",
    "debug_launch": "$",
    "debug_breakpoint": "●",
    "debug_continue": "▶",
    "debug_registers": "→",
    "debug_memory": "→",
    "debug_backtrace": "→",
    "debug_eval": "$",
    "debug_kill": "✕",
    "debug_sessions": "→",
}

# Pending messages per tool
_TOOL_PENDING: dict[str, str] = {
    "shell": "Running command...",
    "read_file": "Reading file...",
    "write_file": "Writing file...",
    "disassemble": "Disassembling...",
    "decompile": "Decompiling...",
    "functions": "Listing functions...",
    "xrefs": "Finding xrefs...",
    "strings": "Listing strings...",
    "sections": "Listing sections...",
    "search": "Searching...",
    "file_info": "Reading file info...",
    "dispatch_subagent": "Dispatching subagent...",
    "update_model": "Updating model...",
    "think": "Thinking...",
    "send_dmail": "Sending D-Mail...",
    "activate_skill": "Loading skill...",
    "task": "Delegating task...",
    "debug_launch": "Launching debugger...",
    "debug_breakpoint": "Setting breakpoint...",
    "debug_continue": "Continuing execution...",
    "debug_registers": "Reading registers...",
    "debug_memory": "Reading memory...",
    "debug_backtrace": "Getting backtrace...",
    "debug_eval": "Evaluating...",
    "debug_kill": "Killing session...",
    "debug_sessions": "Listing sessions...",
}


class TUILogHandler(logging.Handler):
    """Logging handler that captures the last log message for the TUI status bar.

    Instead of writing to stderr (which corrupts the Textual display),
    this handler stores the most recent log record and triggers a
    status bar refresh on the app.
    """

    def __init__(self, app: ReagentApp) -> None:
        super().__init__()
        self._app = app
        self.last_message: str = ""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.last_message = self.format(record)
            # Schedule a status bar update on Textual's event loop.
            # call_from_thread is safe to call from any thread (including
            # the main thread) — it posts to Textual's message queue.
            self._app.call_from_thread(self._app._update_status)
        except Exception:
            pass  # Swallow errors — never let logging crash the TUI (intentional)


class ReagentApp(App):
    """Reagent TUI — autonomous binary analysis agent."""

    TITLE = "reagent"
    CSS = """
    #main-layout {
        layout: horizontal;
        height: 1fr;
    }

    #chat-scroll {
        width: 3fr;
        border: solid $primary;
    }

    #sidebar {
        width: 1fr;
        min-width: 36;
        max-width: 60;
    }

    #target-info {
        height: auto;
        max-height: 12;
        border: solid $secondary;
        padding: 0 1;
        overflow-y: auto;
    }

    #model-tabs {
        height: 1fr;
        border: solid $secondary;
    }

    #findings-pane, #hypotheses-pane, #observations-pane, #terminal-pane {
        overflow-y: auto;
        padding: 0 1;
    }

    #status-bar {
        dock: bottom;
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }

    .tool-line {
        margin: 0 0 0 2;
        height: auto;
    }

    .tool-running {
        color: $text-muted;
    }

    .tool-done {
        color: $text-muted;
    }

    .tool-error {
        color: $error;
    }

    .subagent-panel {
        margin: 1 0 0 0;
        padding: 0 1;
        border: solid $secondary;
    }

    .chat-status {
        margin: 1 0 0 1;
        color: $text-muted;
    }

    .finding-item {
        margin-bottom: 1;
        padding: 0 1;
        border: solid $success;
    }

    .hypothesis-item {
        margin-bottom: 1;
        padding: 0 1;
    }

    .hypothesis-proposed {
        border: solid $warning;
    }

    .hypothesis-confirmed {
        border: solid $success;
    }

    .hypothesis-rejected {
        border: solid $error;
    }

    .step-divider {
        margin: 1 0 0 0;
        color: $text-muted;
    }

    .subagent-begin {
        margin: 1 0 0 0;
        color: $accent;
    }

    .md-block {
        margin: 0 0 0 1;
    }

    .thinking-block {
        margin: 0 0 0 2;
        color: $text-muted;
        height: auto;
    }

    .thinking-label {
        margin: 0 0 0 1;
        color: $text-muted;
    }

    .terminal-session-header {
        color: $accent;
        margin-top: 1;
    }

    .terminal-output {
        color: $text-muted;
    }

    .terminal-exit-notice {
        color: $warning;
        margin: 0 0 1 0;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit"),
    ]

    def __init__(
        self,
        binary_path: str,
        goal: str,
        wire: Wire,
        pipeline: AnalysisPipeline | None = None,
        on_text_cb: Callable[[str], None] | None = None,
        on_step_cb: Callable[[int, StepResult], None] | None = None,
        on_step_begin_cb: Callable[[int, str], None] | None = None,
        on_tool_call_cb: Callable[[str, str, str], None] | None = None,
        on_tool_result_cb: Callable[[str, str, str, bool], None] | None = None,
        on_thinking_cb: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__()
        self.binary_path = binary_path
        self.goal = goal
        self.wire = wire
        self._pipeline = pipeline
        self._on_text_cb = on_text_cb
        self._on_step_cb = on_step_cb
        self._on_step_begin_cb = on_step_begin_cb
        self._on_tool_call_cb = on_tool_call_cb
        self._on_tool_result_cb = on_tool_result_cb
        self._on_thinking_cb = on_thinking_cb
        self._step_count = 0
        self._token_count = 0
        self._current_agent = "orchestrator"
        self._text_buffer = ""
        self._text_agent: str | None = None
        self._streaming_md: Markdown | None = None  # Live-updating Markdown widget
        self._thinking_buffer = ""
        self._streaming_thinking: Static | None = None  # Live-updating thinking widget
        self._log_handler: TUILogHandler | None = None
        self._flush_timer: Timer | None = None
        self._spinner_timer: Timer | None = None
        self._spinner_idx = 0
        self._generating = False  # True while waiting for LLM
        self._pending_tools: dict[
            str, Static | tuple[Static, str, str]
        ] = {}  # tc_id -> widget or (widget, name, args)
        self._widget_counter = 0
        self._terminal_refresh_timer: Timer | None = None

    def _next_id(self, prefix: str = "w") -> str:
        self._widget_counter += 1
        return f"{prefix}-{self._widget_counter}"

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main-layout"):
            yield VerticalScroll(id="chat-scroll")
            with Vertical(id="sidebar"):
                yield Static(id="target-info")
                with TabbedContent(id="model-tabs"):
                    with TabPane("Findings", id="findings-tab"):
                        yield VerticalScroll(id="findings-pane")
                    with TabPane("Hypotheses", id="hypotheses-tab"):
                        yield VerticalScroll(id="hypotheses-pane")
                    with TabPane("Observations", id="observations-tab"):
                        yield VerticalScroll(id="observations-pane")
                    with TabPane("Terminal", id="terminal-tab"):
                        yield VerticalScroll(id="terminal-pane")
        yield Static(id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        binary_name = os.path.basename(self.binary_path)
        self.title = f"reagent - {binary_name}"
        self.sub_title = self.goal[:60] if len(self.goal) > 60 else self.goal

        self._install_log_handler()

        target_info = self.query_one("#target-info", Static)
        target_info.update(
            f"[bold]Target:[/bold] {binary_name}\n[bold]Goal:[/bold] {self.goal}"
        )

        self._update_status()
        self._listen_wire()

        if self._pipeline is not None:
            self._run_agent()
            # Refresh terminal panel every 2 seconds
            self._terminal_refresh_timer = self.set_interval(
                2.0, self._refresh_terminal
            )

    def _install_log_handler(self) -> None:
        root = logging.getLogger()
        for handler in root.handlers[:]:
            root.removeHandler(handler)
        self._log_handler = TUILogHandler(self)
        self._log_handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
        root.addHandler(self._log_handler)
        logging.getLogger("litellm").setLevel(logging.WARNING)
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        logging.getLogger("openai").setLevel(logging.WARNING)

    # --- Status bar ---

    def _update_status(self) -> None:
        try:
            status = self.query_one("#status-bar", Static)
        except Exception:
            return
        last_log = ""
        if self._log_handler and self._log_handler.last_message:
            last_log = self._log_handler.last_message
            if len(last_log) > 80:
                last_log = last_log[:77] + "..."
        parts = [
            f"Step: {self._step_count}",
            f"Tokens: {self._token_count:,}",
            f"Agent: {self._current_agent}",
        ]
        if self._generating:
            frame = _SPINNER[self._spinner_idx % len(_SPINNER)]
            parts.append(f"[bold]{frame} generating[/bold]")
        if last_log:
            parts.append(f"[dim]{last_log}[/dim]")
        status.update(" | ".join(parts))

    def _start_spinner(self) -> None:
        self._generating = True
        self._spinner_idx = 0
        if self._spinner_timer is None:
            self._spinner_timer = self.set_interval(0.08, self._tick_spinner)
        self._update_status()

    def _stop_spinner(self) -> None:
        self._generating = False
        if self._spinner_timer is not None:
            self._spinner_timer.stop()
            self._spinner_timer = None
        self._update_status()

    def _tick_spinner(self) -> None:
        self._spinner_idx += 1
        self._update_status()

    # --- Chat helpers ---

    def _chat_scroll(self) -> VerticalScroll:
        return self.query_one("#chat-scroll", VerticalScroll)

    def _append_static(self, content: str, classes: str = "") -> Static:
        """Append a Static widget to chat and scroll to bottom."""
        chat = self._chat_scroll()
        widget = Static(content, id=self._next_id(), classes=classes)
        chat.mount(widget)
        chat.scroll_end(animate=False)
        return widget

    # --- Wire event loop ---

    @work(exclusive=True)
    async def _listen_wire(self) -> None:
        queue = self.wire.subscribe()
        try:
            while True:
                event = await queue.get()
                if event is None:
                    self._commit_text()
                    self._stop_spinner()
                    self._append_static(
                        "[bold green]--- Analysis Complete ---[/bold green]",
                        classes="chat-status",
                    )
                    self._update_status()
                    break
                self._handle_event(event)
        finally:
            self.wire.unsubscribe(queue)

    @work(exclusive=False)
    async def _run_agent(self) -> None:
        from reagent.agent.loop import agent_loop
        from reagent.context.management import auto_manage_context
        from reagent.llm.message import Message

        pipeline = self._pipeline
        assert pipeline is not None, "_run_agent called without a pipeline"
        try:
            await pipeline.context.append(
                Message.user(
                    f"Analyze the binary at `{self.binary_path}` and accomplish this goal: {self.goal}\n\n"
                    f"Start by examining the binary to understand what it is, then work towards the goal."
                )
            )

            self.wire.send_status(
                f"Agents: {', '.join(pipeline.orch_setup.agent_registry.names())} | "
                f"Tools: {', '.join(pipeline.orch_setup.tool_registry.names())}"
            )

            outcome = await agent_loop(
                agent=pipeline.orch_setup.orchestrator_agent,
                context=pipeline.context,
                provider=pipeline.provider,
                tool_registry=pipeline.orch_setup.tool_registry,
                on_text=self._on_text_cb,
                on_step=self._on_step_cb,
                on_step_begin=self._on_step_begin_cb,
                on_tool_call=self._on_tool_call_cb,
                on_tool_result=self._on_tool_result_cb,
                on_thinking=self._on_thinking_cb,
                on_dmail=self._make_on_dmail(),
                compact_fn=auto_manage_context,
                compact_provider=pipeline.compact_provider,
            )

            self.wire.send_status(f"Analysis complete: {outcome.value}")
        except Exception as e:
            logger.exception("Agent loop error")
            self.wire.send_error(str(e))
        finally:
            await pipeline.pty_manager.cleanup()
            self.wire.close()

    def _make_on_dmail(self) -> Callable[[int, str], None]:
        """Create an on_dmail callback that emits DMAIL events to the wire."""
        from reagent.tui.bridge import make_on_dmail

        return make_on_dmail(self.wire)

    # --- Event dispatch ---

    def _handle_event(self, event: WireEvent) -> None:
        # Commit any pending text before non-TEXT/non-THINKING events
        if event.type not in (EventType.TEXT, EventType.THINKING):
            self._commit_thinking()
            self._commit_text()

        handlers = {
            EventType.TEXT: self._on_text,
            EventType.THINKING: self._on_thinking_event,
            EventType.STEP_BEGIN: self._on_step_begin,
            EventType.TOOL_CALL: self._on_tool_call,
            EventType.TOOL_RESULT: self._on_tool_result,
            EventType.SUBAGENT_BEGIN: self._on_subagent_begin,
            EventType.SUBAGENT_END: self._on_subagent_end,
            EventType.HYPOTHESIS: self._on_hypothesis,
            EventType.FINDING: self._on_finding,
            EventType.OBSERVATION: self._on_observation,
            EventType.COMPACTION: self._on_compaction,
            EventType.TARGET_INFO: self._update_target_info,
            EventType.DMAIL: self._on_dmail,
            EventType.ERROR: self._on_error,
            EventType.STATUS: self._on_status,
            EventType.PTY_EXIT: self._on_pty_exit,
            EventType.TURN_BEGIN: self._on_turn_begin,
            EventType.TURN_END: self._on_turn_end,
        }
        handler = handlers.get(event.type)
        if handler:
            handler(event.data)

    # --- Streaming thinking ---

    def _on_thinking_event(self, data: dict) -> None:
        text = data.get("text", "")
        agent = data.get("agent")
        if not text:
            return

        self._thinking_buffer += text
        self._update_streaming_thinking(agent=agent)

    def _update_streaming_thinking(self, agent: str | None = None) -> None:
        """Create or update the live-streaming thinking widget."""
        text = self._thinking_buffer.rstrip("\n")
        if not text:
            return

        chat = self._chat_scroll()

        # Truncate for display — thinking can be very long
        display_text = text
        if len(display_text) > 2000:
            display_text = display_text[:2000] + "\n... (truncated)"

        label_prefix = f"{agent} " if agent else ""

        if self._streaming_thinking is None:
            # Add a label
            self._append_static(
                f"[dim]{label_prefix}◇ thinking...[/dim]", classes="thinking-label"
            )
            self._streaming_thinking = Static(
                f"[dim]{escape(display_text)}[/dim]",
                id=self._next_id(),
                classes="thinking-block",
            )
            chat.mount(self._streaming_thinking)
        else:
            self._streaming_thinking.update(f"[dim]{escape(display_text)}[/dim]")

        chat.scroll_end(animate=False)

    def _commit_thinking(self) -> None:
        """Finalize the thinking block."""
        if not self._thinking_buffer.strip():
            self._thinking_buffer = ""
            self._streaming_thinking = None
            return

        # The widget is already rendered; just detach
        self._thinking_buffer = ""
        self._streaming_thinking = None

    # --- Streaming text ---

    def _on_text(self, data: dict) -> None:
        text = data.get("text", "")
        agent = data.get("agent")

        # Thinking finishes before text starts
        if self._thinking_buffer:
            self._commit_thinking()

        # If agent changed, commit previous buffer first
        if agent != self._text_agent and self._text_buffer:
            self._commit_text()

        self._text_agent = agent
        self._text_buffer += text

        # Update the live Markdown widget in-place
        self._update_streaming_md()

        # Cancel any existing timer and schedule a scroll
        if self._flush_timer is not None:
            self._flush_timer.stop()
        self._flush_timer = self.set_timer(0.2, self._scroll_chat)

    def _update_streaming_md(self) -> None:
        """Create or update the live-streaming Markdown widget."""
        text = self._text_buffer.rstrip("\n")
        if not text:
            return

        chat = self._chat_scroll()

        if self._streaming_md is None:
            self._streaming_md = Markdown(text, id=self._next_id(), classes="md-block")
            chat.mount(self._streaming_md)
        else:
            # .update() re-renders the widget content in-place
            self._streaming_md.update(text)

        chat.scroll_end(animate=False)

    def _scroll_chat(self) -> None:
        self._flush_timer = None
        self._chat_scroll().scroll_end(animate=False)

    def _commit_text(self) -> None:
        """Finalize the current text block.

        The Markdown widget is already rendered in-place, so we just
        detach from it and clear the buffer.  For subagent text, wrap
        the final widget in a panel-like border.
        """
        if self._flush_timer is not None:
            self._flush_timer.stop()
            self._flush_timer = None

        if not self._text_buffer.strip():
            self._text_buffer = ""
            self._text_agent = None
            self._streaming_md = None
            return

        # If this was subagent text, add a label before the block
        if self._text_agent and self._text_agent != "orchestrator":
            if self._streaming_md is not None:
                self._streaming_md.add_class("subagent-panel")
                # Insert a label before the markdown block
                chat = self._chat_scroll()
                label = Static(
                    f"[dim bold]{self._text_agent}[/dim bold]",
                    id=self._next_id(),
                    classes="step-divider",
                )
                chat.mount(label, before=self._streaming_md)

        # Detach — next text block will create a new widget
        self._text_buffer = ""
        self._text_agent = None
        self._streaming_md = None

    # --- Subagent lifecycle ---

    def _on_subagent_begin(self, data: dict) -> None:
        agent = data.get("agent", "?")
        self._current_agent = agent
        self._append_static(
            f"[bold cyan]--- Subagent: {escape(agent)} ---[/bold cyan]",
            classes="step-divider",
        )
        self._update_status()

    def _on_subagent_end(self, data: dict) -> None:
        agent = data.get("agent", "?")
        self._stop_spinner()
        self._append_static(
            f"[dim cyan]--- {escape(agent)} done ---[/dim cyan]",
            classes="step-divider",
        )
        self._current_agent = "orchestrator"
        self._update_status()

    # --- Step events ---

    def _on_step_begin(self, data: dict) -> None:
        step_no = data.get("step", 0)
        agent = data.get("agent", self._current_agent)
        self._step_count = step_no
        self._current_agent = agent
        self._start_spinner()

    # --- Tool events ---

    def _on_tool_call(self, data: dict) -> None:
        self._stop_spinner()

        name = data.get("name", "?")
        tc_id = data.get("id", "")
        agent = data.get("agent")
        arguments = data.get("arguments", "")
        icon = _TOOL_ICONS.get(name, "⚙")
        pending_msg = _TOOL_PENDING.get(name, f"Running {name}...")

        # For shell/debug_eval, show the actual command being run
        if name in ("shell", "debug_eval") and arguments:
            try:
                args = json.loads(arguments)
                cmd = args.get("command", "")
                if cmd:
                    pending_msg = cmd
            except (json.JSONDecodeError, AttributeError):
                pass

        # Prefix with agent name for subagent tool calls
        prefix = f"[dim]{agent}[/dim] " if agent else ""

        # Show the pending line: ~ Running tool...
        widget = self._append_static(
            f"{prefix}[dim]~ {pending_msg}[/dim]",
            classes="tool-line tool-running",
        )

        if tc_id:
            self._pending_tools[tc_id] = (widget, name, arguments)

    def _on_tool_result(self, data: dict) -> None:
        name = data.get("name", "?")
        tc_id = data.get("id", "")
        is_error = data.get("is_error", False)
        content = data.get("content", "")
        agent = data.get("agent")
        icon = _TOOL_ICONS.get(name, "⚙")

        # Prefix with agent name for subagent tool results
        prefix = f"[dim]{agent}[/dim] " if agent else ""

        # Extract the command for shell/debug_eval from pending tools
        cmd_label = ""
        pending_entry = self._pending_tools.pop(tc_id, None)
        if pending_entry is not None:
            if isinstance(pending_entry, tuple):
                pending_widget, pending_name, pending_args = pending_entry
            else:
                # Backwards compat: plain widget
                pending_widget = pending_entry
                pending_name, pending_args = "", ""

            if pending_name in ("shell", "debug_eval") and pending_args:
                try:
                    args = json.loads(pending_args)
                    cmd_label = args.get("command", "")
                except (json.JSONDecodeError, AttributeError):
                    pass
        else:
            pending_widget = None
            # Fallback: try to extract command from content for shell results
            # that arrive without a matching pending widget
            if name in ("shell", "debug_eval") and not cmd_label:
                logger.debug(
                    "Tool result for %s (tc_id=%s) has no pending widget",
                    name,
                    tc_id,
                )

        # Build the result line
        if name in ("shell", "debug_eval") and cmd_label:
            # Extract meaningful output lines, skipping the "[Exit code: N]" prefix
            output_lines = []
            if content:
                for line in content.split("\n"):
                    stripped = line.strip()
                    if stripped and not stripped.startswith("[Exit code:"):
                        output_lines.append(stripped)

            color = "red" if is_error else "dim"
            header = f"{prefix}[{color}]{icon} {escape(cmd_label)}[/{color}]"

            if output_lines:
                # Show command on first line, output indented below
                output_text = "\n".join(f"  {escape(l)}" for l in output_lines[:20])
                result_text = f"{header}\n[{color}]{output_text}[/{color}]"
            else:
                result_text = header
            css_class = "tool-line tool-error" if is_error else "tool-line tool-done"
        elif name in ("shell", "debug_eval") and not cmd_label:
            # Shell/debug result without a pending widget — show output directly
            output_lines = []
            if content:
                for line in content.split("\n"):
                    stripped = line.strip()
                    if stripped and not stripped.startswith("[Exit code:"):
                        output_lines.append(stripped)

            color = "red" if is_error else "dim"
            header = f"{prefix}[{color}]{icon} {escape(name)}[/{color}]"
            if output_lines:
                output_text = "\n".join(f"  {escape(l)}" for l in output_lines[:20])
                result_text = f"{header}\n[{color}]{output_text}[/{color}]"
            else:
                result_text = header
            css_class = "tool-line tool-error" if is_error else "tool-line tool-done"
        elif is_error:
            first_line = content.split("\n")[0][:120] if content else "Error"
            result_text = (
                f"{prefix}[red]{icon} {escape(name)}: {escape(first_line)}[/red]"
            )
            css_class = "tool-line tool-error"
        else:
            first_line = content.split("\n")[0][:120] if content else "OK"
            result_text = (
                f"{prefix}[dim]{icon} {escape(name)}:[/dim] {escape(first_line)}"
            )
            css_class = "tool-line tool-done"

        # Replace the pending widget if we have one, otherwise append
        if pending_widget is not None:
            pending_widget.update(result_text)
            pending_widget.set_classes(css_class)
        else:
            self._append_static(result_text, classes=css_class)

        # After tool completes, spinner resumes for next generation
        self._start_spinner()

    # --- Model events (sidebar + chat) ---

    def _on_hypothesis(self, data: dict) -> None:
        desc = data.get("description", "")
        status = data.get("status", "proposed")
        confidence = data.get("confidence", 0.0)

        pane = self.query_one("#hypotheses-pane", VerticalScroll)
        status_class = f"hypothesis-{status}"
        label = Label(
            f"[{status.upper()}] {desc}\n  confidence: {confidence:.0%}",
            classes=f"hypothesis-item {status_class}",
        )
        pane.mount(label)
        pane.scroll_end()

        color = {"proposed": "yellow", "confirmed": "green", "rejected": "red"}.get(
            status, "white"
        )
        self._append_static(
            f"[bold {color}]Hypothesis [{status}]: {escape(desc)}[/bold {color}]",
            classes="chat-status",
        )

    def _on_finding(self, data: dict) -> None:
        desc = data.get("description", "")
        category = data.get("category", "")
        verified = data.get("verified", False)

        pane = self.query_one("#findings-pane", VerticalScroll)
        badge = "[verified]" if verified else "[unverified]"
        label = Label(
            f"{badge} {desc}\n  category: {category}",
            classes="finding-item",
        )
        pane.mount(label)
        pane.scroll_end()

        self._append_static(
            f"[bold green]FINDING: {escape(desc)}[/bold green]",
            classes="chat-status",
        )

    def _on_observation(self, data: dict) -> None:
        desc = data.get("description", "")
        category = data.get("category", "general")

        pane = self.query_one("#observations-pane", VerticalScroll)
        label = Label(
            f"[{category}] {desc}",
            classes="hypothesis-item",
        )
        pane.mount(label)
        pane.scroll_end()

    # --- Misc events ---

    def _on_pty_exit(self, data: dict) -> None:
        """Handle PTY_EXIT — a process died unexpectedly."""
        session_id = data.get("session_id", "?")
        title = data.get("title", "")
        exit_code = data.get("exit_code")
        last_output = data.get("last_output", "")

        label = title or session_id
        code_str = str(exit_code) if exit_code is not None else "?"

        # Show in chat
        self._append_static(
            f"[bold yellow]PTY exited: {escape(label)} (code={code_str})[/bold yellow]",
            classes="chat-status",
        )

        # Show in terminal pane
        try:
            pane = self.query_one("#terminal-pane", VerticalScroll)
            pane.mount(
                Label(
                    f"[{label}] exited (code={code_str})\n{last_output}",
                    classes="terminal-exit-notice",
                )
            )
            pane.scroll_end()
        except Exception:
            pass

    def _refresh_terminal(self) -> None:
        """Periodically refresh the Terminal tab with live PTY output."""
        if self._pipeline is None:
            return

        try:
            pane = self.query_one("#terminal-pane", VerticalScroll)
        except Exception:
            return

        sessions = self._pipeline.pty_manager.list_sessions()
        if not sessions:
            return

        # Clear and rebuild — simple approach for a sidebar panel
        pane.remove_children()

        for info in sessions:
            sid = info["id"]
            title = info.get("title", "")
            status = info.get("status", "?")
            label = title or sid

            session = self._pipeline.pty_manager.get(sid)
            if session is None:
                continue

            # Header with status colour
            status_color = "green" if status == "running" else "red"
            pane.mount(
                Static(
                    f"[bold]{escape(label)}[/bold]  [{status_color}]{status}[/{status_color}]",
                    classes="terminal-session-header",
                )
            )

            # Last N lines of output.
            # For shell sessions, filter out internal sentinel prompts so the
            # terminal tab shows clean command/output pairs.
            tail_lines = session.buffer.read_tail(30)
            if tail_lines:
                if title == "shell":
                    # Filter shell sentinel lines and heredoc noise
                    filtered: list[str] = []
                    for line in tail_lines:
                        stripped = line.strip()
                        if stripped == "___REAGENT_PROMPT___":
                            continue
                        if stripped == "_REAGENT_EOF_":
                            continue
                        # Bash continuation prompts for heredocs
                        if stripped in (">", "> "):
                            continue
                        filtered.append(line)
                    tail_lines = filtered[-20:]  # Keep last 20 after filtering

                output_text = "\n".join(escape(line) for line in tail_lines)
                pane.mount(
                    Static(
                        f"[dim]{output_text}[/dim]",
                        classes="terminal-output",
                    )
                )

        pane.scroll_end()

    def _on_compaction(self, data: dict) -> None:
        action = data.get("action", "compacted")
        self._append_static(
            f"[dim italic]Context {action}[/dim italic]",
            classes="chat-status",
        )

    def _on_dmail(self, data: dict) -> None:
        message = data.get("message", "Time-travel triggered")
        self._append_static(
            f"[bold magenta]D-MAIL: {escape(message)}[/bold magenta]",
            classes="chat-status",
        )

    def _on_error(self, data: dict) -> None:
        error = data.get("error", "Unknown error")
        self._stop_spinner()
        self._append_static(
            f"[bold red]ERROR: {escape(error)}[/bold red]",
            classes="chat-status",
        )

    def _on_status(self, data: dict) -> None:
        message = data.get("message", "")
        tokens = data.get("tokens")
        agent = data.get("agent")
        if tokens:
            self._token_count = tokens
        if agent:
            self._current_agent = agent
        if message:
            self._append_static(f"[dim]{escape(message)}[/dim]", classes="chat-status")
        self._update_status()

    def _on_turn_begin(self, data: dict) -> None:
        agent = data.get("agent", "orchestrator")
        self._current_agent = agent
        self._update_status()

    def _on_turn_end(self, data: dict) -> None:
        outcome = data.get("outcome", "")
        agent = data.get("agent", "")
        self._stop_spinner()
        if outcome:
            self._append_static(
                f"[dim]{escape(agent)} finished: {escape(outcome)}[/dim]",
                classes="chat-status",
            )

    def _update_target_info(self, target_data: dict) -> None:
        info = self.query_one("#target-info", Static)
        lines = [f"[bold]Target:[/bold] {os.path.basename(self.binary_path)}"]
        lines.append(f"[bold]Goal:[/bold] {self.goal}")

        fmt = target_data.get("format")
        if fmt:
            lines.append(f"[bold]Format:[/bold] {fmt}")
        arch = target_data.get("arch")
        if arch:
            bits = target_data.get("bits", "")
            lines.append(f"[bold]Arch:[/bold] {arch} ({bits}-bit)")
        features = []
        if target_data.get("nx"):
            features.append("NX")
        if target_data.get("pie"):
            features.append("PIE")
        if target_data.get("canary"):
            features.append("Canary")
        if target_data.get("relro"):
            features.append(f"RELRO:{target_data['relro']}")
        if features:
            lines.append(f"[bold]Security:[/bold] {', '.join(features)}")

        info.update("\n".join(lines))
