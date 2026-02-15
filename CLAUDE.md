# CLAUDE.md — Development Guide for reagent

## Protected Files

Do NOT delete or overwrite these files — they are intentionally maintained:
- `README.md` — User-facing project documentation
- `CLAUDE.md` — This development guide
- `PITCH.md` — YC-style business pitch

## Project Structure

```
src/reagent/
  llm/          LLM abstraction (litellm-based, streaming, message types)
  agent/        Agent system (definitions, loop, orchestrator, registry)
  tool/         Tool system (base classes, registry, truncation)
    builtin/    General tools (shell, read, write, think, task, skill, dmail)
  re/           RE-specific tools (rizin, debugger, LIEF file info)
  model/        BinaryModel (observations, hypotheses, findings)
  context/      Context management (JSONL store, compaction, pruning, D-Mail)
  pty/          PTY process management (sessions, rolling buffers, process tree guard)
  skill/        Progressive skill loading system (SkillRegistry)
  session/      Session persistence and wire protocol
  tui/          Textual TUI (app, wire bridge)
  config/       Configuration (Pydantic models)
  cli.py        CLI entry point (analyze + tui commands)
agents/         Agent definitions (markdown with YAML frontmatter)
skills/         Skill files (rizin, gdb, frida command references)
tests/          Test suite
```

## Build & Test

```bash
uv sync                    # Install dependencies
uv run pytest              # Run tests
uv run reagent --help      # Run CLI
uv run reagent analyze BINARY -g "goal"         # Plain CLI mode
uv run reagent analyze BINARY -g "goal" -M      # Masked binary name (avoids agent bias)
uv run reagent tui BINARY -g "goal"             # Interactive TUI mode
uv run reagent tui BINARY -g "goal" -M          # TUI with masked binary name
```

## Environment Variables

Configure via `.env` file (loaded automatically) or shell environment:

| Variable | Description | Default |
|----------|-------------|---------|
| `ANTHROPIC_API_KEY` | Anthropic API key | — |
| `OPENAI_API_KEY` | OpenAI API key | — |
| `GEMINI_API_KEY` | Gemini API key | — |
| `REAGENT_MODEL` | Main model (litellm format) | `anthropic/claude-sonnet-4-5-20250929` |
| `REAGENT_FAST_MODEL` | Fast model for compaction | `anthropic/claude-haiku-4-5-20251001` |
| `REAGENT_CONTEXT_WINDOW` | Context window size | `200000` |
| `REAGENT_REASONING_EFFORT` | Reasoning effort (low/medium/high) | — |
| `REAGENT_FAST_REASONING_EFFORT` | Fast model reasoning effort | — |

Model names use litellm's `provider/model` prefix format. litellm reads API keys from env vars automatically — no need to pass them explicitly.

Examples:
```
# Anthropic
REAGENT_MODEL=anthropic/claude-sonnet-4-5-20250929

# Gemini
REAGENT_MODEL=gemini/gemini-3-flash-preview

# OpenAI
REAGENT_MODEL=openai/gpt-4o
```

## LLM Provider Architecture

- **`LiteLLMProvider`** — single unified provider class using `litellm.acompletion()`. litellm handles provider detection from the model string prefix and all SDK-specific format conversion internally.
- **`ChatProvider`** — runtime-checkable `Protocol` that `LiteLLMProvider` implements. Has `config` property and `stream()` async iterator method.
- **`create_provider(model, temperature, max_tokens, context_window)`** — factory function. No `api_key`, `base_url`, or `provider_type` args needed.
- Streaming uses litellm's `CustomStreamWrapper` which emits `ModelResponseStream` objects (OpenAI-format). `_chunk_to_dict()` normalizes these to our internal chunk dict format consumed by `streaming.py`.
- **Fast model** (`compact_provider`) — separate provider instance with `temperature=0.2` for context compaction. Threaded through `agent_loop()` -> `compact_fn()` -> `compact_context()`.

## Agent System

Agents are defined as markdown files in `agents/` with YAML frontmatter:

```yaml
---
name: agent_name
description: What this agent does
mode: primary | subagent
tools: [tool1, tool2, ...]
max_steps: 40
model: optional/model-override     # optional
temperature: 0.7                   # optional
---

System prompt content here...
```

Built-in agents:
- **orchestrator** (primary, 40 steps) — coordinates analysis, dispatches subagents, records findings
- **triage** (subagent, 15 steps) — quick recon: file format, arch, security features, strings
- **static** (subagent, 30 steps) — deep code analysis: decompilation, xrefs, control flow
- **dynamic** (subagent, 30 steps) — runtime verification: debugging, breakpoints, memory inspection
- **coding** (subagent, 15 steps) — computational verification: writes/runs Python scripts to decode, hash, keygen, etc.

The orchestrator dispatches subagents via `DispatchSubagentTool`. Each subagent gets its own temp Context, a tool registry subset, and the BinaryModel summary injected into its system prompt.

## Tool System

All tools inherit from `BaseTool` with Pydantic parameter models. Output goes through truncation (2000 lines / 50KB).

### Builtin Tools (7)

| Tool | Class | Description |
|------|-------|-------------|
| `shell` | `ShellTool` | Execute shell commands with process group isolation |
| `read_file` | `ReadFileTool` | Read file contents with offset/limit |
| `write_file` | `WriteFileTool` | Write content to files |
| `think` | `ThinkTool` | Internal reasoning scratchpad (no side effects) |
| `task` | `TaskTool` | Dispatch tasks to sub-agents |
| `send_dmail` | `SendDMailTool` | Send knowledge back in time to a past checkpoint (D-Mail) |
| `activate_skill` | `ActivateSkillTool` | Load domain-specific reference material on demand |

### RE Tools — Rizin (8)

| Tool | Class | Description |
|------|-------|-------------|
| `disassemble` | `DisassembleTool` | Disassemble instructions at address/function (`pd`) |
| `decompile` | `DecompileTool` | Decompile function to pseudo-C (`pdg` -> `pdc` -> `pdsf` fallback) |
| `functions` | `FunctionsTool` | List functions found by rizin analysis (`aflj`) |
| `xrefs` | `XrefsTool` | Find cross-references to/from address (`axtj`/`axfj`) |
| `strings` | `StringsTool` | List strings in binary (`izj`) |
| `sections` | `SectionsTool` | List binary sections/segments (`iSj`) |
| `search` | `SearchTool` | Search for string/hex/ROP patterns |
| `file_info` | `FileInfoTool` | Extract structured metadata via LIEF (ELF/PE/Mach-O) |

All rizin tools share one `rzpipe.open()` session via `_RzSession` singleton.
Decompile fallback chain: `pdg` (rz-ghidra) -> `pdc` (rz-dec) -> `pdsf`+`pdf`.

### RE Tools — Debugger (9)

| Tool | Class | Description |
|------|-------|-------------|
| `debug_launch` | `DebugLaunchTool` | Launch GDB/LLDB session via PTY |
| `debug_breakpoint` | `DebugBreakpointTool` | Set/delete breakpoints |
| `debug_continue` | `DebugContinueTool` | Control execution (run/continue/step) |
| `debug_registers` | `DebugRegistersTool` | Read CPU registers |
| `debug_memory` | `DebugMemoryTool` | Read process memory |
| `debug_backtrace` | `DebugBacktraceTool` | Get stack backtrace |
| `debug_eval` | `DebugEvalTool` | Execute raw debugger commands |
| `debug_kill` | `DebugKillTool` | Terminate debug session |
| `debug_sessions` | `DebugSessionsTool` | List active debug sessions |

### Orchestrator Tools (2)

| Tool | Class | Description |
|------|-------|-------------|
| `dispatch_subagent` | `DispatchSubagentTool` | Dispatch task to specialist subagent |
| `update_model` | `UpdateModelTool` | Record observations/hypotheses/findings in BinaryModel |

## BinaryModel

Shared knowledge base that tracks analysis state:

```
TargetInfo: path, format, arch, endian, bits, stripped, pie, nx, canary, relro
BinaryModel:
  target: TargetInfo
  observations: list[Observation]   # Raw data (asm, hex, strings)
  hypotheses: list[Hypothesis]      # "Function X looks like CRC32"
  findings: list[Finding]           # Verified facts
  functions: dict[str, str]         # addr -> name mapping
  strings: list[dict]               # interesting strings

Observation: id, type, source, address, data, timestamp
Hypothesis: id, description, category, confidence, evidence,
            status (proposed|testing|confirmed|rejected), proposed_by, verified_by, address
Finding: id, description, category, addresses, evidence, verified, verified_by, details
```

## Context Management

- **Context** — JSONL-backed conversation history with checkpoint support for D-Mail.
- **Token estimation** — ~4 chars per token approximation.
- **Three-tier management**:
  1. **Pruning** — replaces tool results >500 chars with stubs, protects last 10 messages
  2. **Compaction** — LLM-summarizes old messages using fast_model, keeps last 6 verbatim
  3. **Truncation** — at tool level (2000 lines / 50KB)
- **`auto_manage_context()`** — prunes first, then compacts if still over 70% of context window.
- **D-Mail** — `SendDMailTool` raises `BackToTheFuture` exception. Agent loop catches it, reverts context to checkpoint, injects knowledge as system message. Allows the agent to "send knowledge back in time" to avoid dead ends.

## Wire Protocol

Decouples agent logic from UI via async event bus. Event types:

`TURN_BEGIN`, `TURN_END`, `STEP_BEGIN`, `TEXT`, `TOOL_CALL`, `TOOL_RESULT`,
`OBSERVATION`, `HYPOTHESIS`, `FINDING`, `COMPACTION`, `DMAIL`, `ERROR`, `STATUS`

Wire -> TUI subscription via bridge callbacks in `tui/bridge.py`.

## PTY System

- **`PTYSession`** — managed pseudo-terminal using `subprocess.Popen` with `start_new_session=True`. Process group isolation, ANSI stripping, prompt-based command/response (`send_and_match`).
- **`PTYManager`** — manages multiple sessions (max 10), auto-kills oldest on overflow.
- **`RollingBuffer`** — thread-safe deque-based line buffer (50K line cap) with read/search/tail.
- All processes run in process groups (`os.setpgrp`). Call `kill_tree()` to clean up.

## Skill System

Progressive loading — domain reference files in `skills/` loaded on demand:

```
skills/
  rizin/commands.md    # rizin command reference
  rizin/patterns.md    # Common analysis patterns
  gdb/commands.md      # GDB command reference
  gdb/workflows.md     # GDB debugging workflows
  frida/               # (placeholder)
```

`SkillRegistry` discovers skills at construction. `ActivateSkillTool` loads content — call with `skill='list'` to see available skills or `skill='rizin/commands'` to load a specific one.

## TUI

Built on Textual framework:
- Layout: Header + Horizontal(RichLog chat panel 3fr | Vertical sidebar 1fr with tabs for Findings/Hypotheses/Observations) + status bar + Footer
- `TUILogHandler` redirects Python logging to status bar (prevents log messages from corrupting TUI display)
- Status bar shows: `Step: N | Tokens: N | Agent: name | last log message`
- Agent loop runs as async Textual worker via `_run_agent()`
- Wire event subscription via `_listen_wire()` worker

## Key Patterns

- **Tools** inherit from `BaseTool` with Pydantic params. All output goes through truncation (2000 lines / 50KB).
- **Agents** are defined as markdown files in `agents/` with YAML frontmatter specifying tools, max_steps, model overrides.
- **Context** is JSONL-backed with checkpoints for D-Mail (context time-travel). Auto-managed via prune -> compact strategy.
- **Skills** are progressive — domain reference files in `skills/` loaded on demand via `ActivateSkillTool`.
- **PTY sessions** always run in process groups (`os.setpgrp`) — call `kill_tree()` to clean up.
- **BinaryModel** is the shared knowledge base: observations -> hypotheses -> findings.
- **Wire protocol** decouples agent logic from UI via async event bus (Wire -> TUI subscription).
- **TUI** uses Textual with wire bridge callbacks; agent loop runs as async worker on Textual's event loop.
- All tool output is sanitized (ANSI stripped, binary filtered) before reaching the LLM.

## Architecture Invariants

1. Tools are pure: structured input -> structured output. No implicit state.
2. Agents are stateless: all state lives in Context and BinaryModel.
3. PTY sessions are always managed: every process is in a group, killed on cleanup.
4. Output is always bounded: truncation at tool level, pruning at context level.
5. Wire protocol decouples agent logic from UI.

## Dependencies

Add deps with `uv add <package>`, dev deps with `uv add --dev <package>`.

Runtime: aiofiles, anthropic, lief, litellm, openai, pydantic, python-dotenv, pyyaml, rzpipe, tenacity, textual, typer.
Dev: pytest, pytest-asyncio.
