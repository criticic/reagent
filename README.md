# reagent

The autonomous AI agent for binary analysis and vulnerability research.

[Watch the demo](demo.mp4)

reagent combines LLM reasoning with specialist sub-agents that operate industry-standard reverse engineering tools in real-time. You give it a binary and a goal — it triages, decompiles, debugs, and delivers structured findings.

## How It Works

```
User: binary + goal
  |
  v
Orchestrator (plans mission, dispatches specialists)
  |
  +-- Triage Agent     (LIEF metadata, strings, sections, functions)
  +-- Static Agent     (rizin disassembly/decompilation, xrefs, search)
  +-- Dynamic Agent    (GDB/LLDB debugging, breakpoints, memory inspection)
  |
  v
BinaryModel (observations -> hypotheses -> verified findings)
  |
  v
Structured Report
```

The key differentiator is **Autonomous Verification**. If the Static agent hypothesizes a function is a decryption routine, the Dynamic agent sets breakpoints, dumps registers, and confirms or rejects the hypothesis with runtime evidence. This mimics how a human expert works — but autonomously.

## Quickstart

```bash
# Install
uv sync

# Set your API key (pick one provider)
export ANTHROPIC_API_KEY=sk-ant-api03-...
# or: export GEMINI_API_KEY=...
# or: export OPENAI_API_KEY=sk-...

# Analyze a binary (plain CLI output)
reagent analyze ./target_binary -g "Find the license key validation logic"

# Analyze with interactive TUI
reagent tui ./target_binary -g "Identify the C2 protocol"
```

## Test Drive (Crackmes)

reagent comes with a set of `crackme` challenges to demonstrate its capabilities. To build and run them:

1.  **Build the crackmes:**
    ```bash
    cd crackme
    make
    cd ..
    ```

2.  **Run reagent against them:**

    | Challenge | Difficulty | Goal | Command |
    |-----------|------------|------|---------|
    | `crackme01_password` | Easy | Find the hardcoded password | `reagent analyze crackme/.bin/crackme01_password -g "Find the password"` |
    | `crackme02_xor` | Easy | Recover XOR-encoded flag | `reagent analyze crackme/.bin/crackme02_xor -g "Recover the flag"` |
    | `crackme03_keygen` | Medium | Generate a valid license key | `reagent analyze crackme/.bin/crackme03_keygen -g "Generate a valid license key"` |
    | `crackme04_bof` | Medium | Exploit buffer overflow | `reagent analyze crackme/.bin/crackme04_bof -g "Find the buffer overflow and how to call the hidden win() function"` |
    | `crackme05_multistage` | Hard | Pass multi-stage validation | `reagent analyze crackme/.bin/crackme05_multistage -g "Find the input that passes all validation stages"` |

## Configuration

Configure via `.env` file or shell environment. Copy `.env.example` to `.env` to get started.

### Model Selection

Model names use [litellm](https://docs.litellm.ai/)'s `provider/model` prefix format. litellm reads API keys from environment variables automatically.

```bash
# Anthropic (default)
REAGENT_MODEL=anthropic/claude-sonnet-4-5-20250929
REAGENT_FAST_MODEL=anthropic/claude-haiku-4-5-20251001
REAGENT_CONTEXT_WINDOW=200000

# Gemini
REAGENT_MODEL=gemini/gemini-3-flash-preview
REAGENT_FAST_MODEL=gemini/gemini-2.5-flash-preview
REAGENT_CONTEXT_WINDOW=1000000

# OpenAI
REAGENT_MODEL=openai/gpt-4o
REAGENT_FAST_MODEL=openai/gpt-4o-mini
REAGENT_CONTEXT_WINDOW=128000
# Reasoning effort for supported models (e.g. o1/o3/sonnet-3.7)
REAGENT_REASONING_EFFORT=medium
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ANTHROPIC_API_KEY` | Anthropic API key | — |
| `OPENAI_API_KEY` | OpenAI API key | — |
| `GEMINI_API_KEY` | Gemini API key | — |
| `REAGENT_MODEL` | Main model | `anthropic/claude-sonnet-4-5-20250929` |
| `REAGENT_FAST_MODEL` | Fast model for context compaction | `anthropic/claude-haiku-4-5-20251001` |
| `REAGENT_CONTEXT_WINDOW` | Context window size | `200000` |
| `REAGENT_REASONING_EFFORT` | Reasoning effort (low/medium/high) | — |
| `REAGENT_FAST_REASONING_EFFORT` | Fast model reasoning effort | — |

## Architecture

### Multi-Agent System

reagent uses a hierarchical multi-agent architecture. The **Orchestrator** breaks down the user's goal into subtasks and dispatches them to specialist agents:

| Agent | Role | Tools | Max Steps |
|-------|------|-------|-----------|
| **Orchestrator** | Coordinates analysis, manages task flow, records findings | think, dispatch_subagent, update_model, shell, send_dmail | 40 |
| **Triage** | Quick recon: file format, arch, security features, strings | shell, file_info, strings, sections, functions, think | 15 |
| **Static** | Deep code analysis: decompilation, xrefs, control flow | disassemble, decompile, functions, xrefs, strings, sections, search, think, activate_skill | 30 |
| **Dynamic** | Runtime verification: debugging, breakpoints, memory | debug_launch, debug_breakpoint, debug_continue, debug_registers, debug_memory, debug_backtrace, debug_eval, debug_kill, debug_sessions, shell, think, activate_skill | 30 |

Agents are defined as markdown files in `agents/` with YAML frontmatter. You can add custom agents by creating new `.md` files.

### Tool System (26 tools)

**General Tools:**
- `shell` — Execute shell commands with process group isolation
- `read_file` — Read file contents with offset/limit
- `write_file` — Write content to files
- `think` — Internal reasoning scratchpad (no side effects)
- `task` — Dispatch tasks to sub-agents
- `send_dmail` — Send knowledge back in time to a past checkpoint (D-Mail)
- `activate_skill` — Load domain-specific reference material on demand

**Rizin Static Analysis (8 tools):**
- `disassemble` — Disassemble instructions at address/function
- `decompile` — Decompile function to pseudo-C (rz-ghidra -> rz-dec -> pdsf fallback)
- `functions` — List all functions found by analysis
- `xrefs` — Find cross-references to/from an address
- `strings` — List strings in binary
- `sections` — List binary sections/segments
- `search` — Search for string/hex/ROP patterns
- `file_info` — Extract structured metadata via LIEF (ELF/PE/Mach-O)

**Debugger (9 tools):**
- `debug_launch` — Launch GDB/LLDB session via managed PTY
- `debug_breakpoint` — Set/delete breakpoints
- `debug_continue` — Control execution (run/continue/step/next)
- `debug_registers` — Read CPU registers
- `debug_memory` — Read process memory
- `debug_backtrace` — Get stack backtrace
- `debug_eval` — Execute raw debugger commands
- `debug_kill` — Terminate debug session
- `debug_sessions` — List active debug sessions

**Orchestrator Tools:**
- `dispatch_subagent` — Dispatch task to a specialist subagent
- `update_model` — Record observations, hypotheses, or findings

### BinaryModel — Structured Knowledge Base

Analysis state is tracked in a structured knowledge base that progresses from raw data to verified conclusions:

- **Observations** — Raw data: disassembly, hex dumps, strings, register values
- **Hypotheses** — Testable claims: "Function at 0x401230 is a CRC32 check" (with confidence and status tracking: proposed -> testing -> confirmed/rejected)
- **Findings** — Verified facts with evidence chains and addresses

The orchestrator and all subagents share access to this model. Static analysis proposes hypotheses; dynamic analysis confirms or rejects them.

### Context Management

reagent manages LLM context automatically with a three-tier strategy:

1. **Truncation** — Tool output is bounded at 2000 lines / 50KB
2. **Pruning** — Old tool results >500 chars are replaced with stubs (last 10 messages protected)
3. **Compaction** — LLM-summarizes old messages using the fast model, keeping the last 6 verbatim

**D-Mail** (context time-travel): If the agent reaches a dead end, it can "send knowledge back in time" — the context reverts to a previous checkpoint with the learned knowledge injected as a system message. This lets the agent restart with the benefit of hindsight.

### Progressive Skill Loading

Instead of cramming tool manuals into the prompt, reagent uses on-demand skill loading. The agent sees a high-level summary and calls `activate_skill` when it needs detailed command references:

```
skills/
  rizin/commands.md    # rizin command reference
  rizin/patterns.md    # Common analysis patterns
  gdb/commands.md      # GDB command reference
  gdb/workflows.md     # GDB debugging workflows
  frida/               # (placeholder)
```

### PTY System

All interactive tools (debuggers, shells) run in managed pseudo-terminals with:
- Process group isolation (`os.setpgrp`) — no orphan processes
- ANSI stripping — clean output for LLM consumption
- Rolling buffers (50K lines) — handles large output without memory issues
- Prompt-based command/response matching
- Auto-cleanup on session overflow (max 10 concurrent sessions)

### Wire Protocol

A typed async event bus decouples agent logic from UI, enabling both CLI and TUI frontends:

```
TURN_BEGIN, TURN_END, STEP_BEGIN, TEXT, TOOL_CALL, TOOL_RESULT,
OBSERVATION, HYPOTHESIS, FINDING, COMPACTION, DMAIL, ERROR, STATUS
```

### TUI

The interactive terminal UI (built on [Textual](https://github.com/Textualize/textual)) provides:
- Real-time streaming of agent reasoning and tool calls
- Sidebar with tabs for Findings, Hypotheses, and Observations
- Status bar showing step count, token usage, current agent, and log messages
- All Python logging redirected to the status bar (no display corruption)

## Requirements

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) (package manager)
- [rizin](https://rizin.re/) with rz-ghidra plugin (for static analysis)
- GDB or LLDB (for dynamic analysis)
- One LLM API key (Anthropic, OpenAI, or Gemini)

### Optional

- [LIEF](https://lief.re/) (bundled — for binary metadata extraction)
- [Frida](https://frida.re/) (planned — dynamic instrumentation)

## Tech Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.12+ |
| LLM | litellm (Anthropic, OpenAI, Gemini — any litellm-supported provider) |
| Static Analysis | rizin + rz-ghidra |
| Dynamic Analysis | GDB/LLDB via managed PTY |
| Binary Metadata | LIEF |
| TUI | Textual |
| CLI | Typer |
| Process Mgmt | PTY with process group isolation |
| Build System | Hatchling + uv |

## Development

```bash
uv sync                    # Install all dependencies
uv run pytest              # Run tests
uv run reagent --help      # CLI help
```

Add dependencies with `uv add <package>`, dev dependencies with `uv add --dev <package>`.

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
  cli.py        CLI entry point
agents/         Agent definitions (markdown with YAML frontmatter)
skills/         Skill files (rizin, gdb, frida references)
tests/          Test suite
```

## License

TBD
