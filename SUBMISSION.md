# REagent — Devfolio Submission

## Project Name

REagent — The Autonomous AI Agent for Binary Analysis

## Tagline

Claude Code for Reverse Engineering — give it a binary and a goal, it triages, decompiles, debugs, and delivers verified findings.

---

## Problem Solved

### AI Can Build — But It Can't Break

In 2025, every developer has Claude Code, Codex CLI, and Gemini CLI for *writing* software. But the flip side — *finding vulnerabilities* in compiled binaries — remains entirely manual. As AI-assisted development ships more programs faster, the attack surface grows exponentially. We need agentic AI on the defense side too — for **breaking**, not just building.

**The talent gap is real.** Fewer than 10,000 capable reverse engineers exist globally. They cost $300K+/year and are fully booked. India is rapidly digitizing critical infrastructure — UPI (processing 14B+ transactions/month), Aadhaar, DigiLocker, CoWIN — but lacks the reverse engineering workforce to audit the compiled binaries that power this infrastructure. CERT-In handles thousands of vulnerability disclosures annually, but the pipeline of people who can find zero-days in compiled code is vanishingly small.

**Existing tools are passive and expensive.** IDA Pro costs $2,000+/year. Ghidra is free but purely passive — it shows you decompiled code and waits for a human to reason about it. Neither can run a binary, set breakpoints, inspect memory, or verify a hypothesis autonomously. The state of the art is still "human stares at assembly for hours."

### What REagent Does

You give it a binary and a goal (e.g., "Find the password validation logic" or "Identify the buffer overflow"). It autonomously:

1. **Runs the binary** to observe its behavior — prompts, output, error messages
2. **Triages** — extracts metadata, security features (NX, PIE, canary, RELRO), strings, function lists
3. **Statically analyzes** — decompiles functions, traces cross-references, maps control flow
4. **Dynamically verifies** — launches a debugger (GDB/LLDB), sets breakpoints, reads CPU registers, inspects memory, and *proves* its hypotheses with runtime evidence
5. **Reports verified findings** — not hallucinations, but facts backed by evidence chains

The key innovation is the **Autonomous Verification Loop**: static analysis *proposes* hypotheses ("this function checks a password via strcmp"), and dynamic analysis *confirms or rejects* them by actually executing the code and reading the result. This mimics how a human expert works — but autonomously, in minutes instead of hours.

### Why We Built This

This comes from years of doing CTF competitions and cybersecurity work at IIT (BHU) — spending hours on manual binary analysis that should take minutes. As more software gets shipped (especially with AI-assisted development), the gap between "code being written" and "code being audited" keeps widening. REagent exists because the security side needs the same AI tooling that the development side already has.

---

## Technical Architecture

### Multi-Agent System (6,500+ lines of Python, 26 tools)

```
User: binary + goal
  |
  v
Orchestrator (plans mission, dispatches specialists, records findings)
  |
  +-- Triage Agent     (LIEF metadata, strings, sections, security features)
  +-- Static Agent     (rizin decompilation, xrefs, control flow, search)
  +-- Dynamic Agent    (GDB/LLDB debugging, breakpoints, registers, memory)
  +-- Coding Agent     (Python scripts for XOR decode, keygen math, hash bruteforce)
  |
  v
BinaryModel (observations → hypotheses → verified findings)
  |
  v
Structured Report with Evidence Chains
```

Agents are defined as **markdown files with YAML frontmatter** — fully declarative, user-extensible. Each agent gets its own tool subset, context, and step limit.

### Core Components

**BinaryModel — Structured Knowledge Base**
Three-tier knowledge progression: Observations (raw facts like "function at 0x401000 calls strcmp") → Hypotheses (testable claims with confidence scores and status tracking: proposed → testing → confirmed/rejected) → Findings (verified facts with evidence chains and addresses). All agents share this model. Updates appear in the TUI sidebar in real-time via the Wire protocol.

**26 Specialized Tools**
- 7 builtins: shell, read_file, write_file, think, task, send_dmail, activate_skill
- 8 rizin static analysis tools: disassemble, decompile (3-tier fallback: rz-ghidra → rz-dec → pdsf), functions, xrefs, strings, sections, search, file_info
- 9 debugger tools: debug_launch, debug_breakpoint, debug_continue, debug_registers, debug_memory, debug_backtrace, debug_eval, debug_kill, debug_sessions
- 2 orchestrator tools: dispatch_subagent, update_model

**Managed PTY System**
All interactive tools (debuggers, shells) run in managed pseudo-terminals with process group isolation (`os.setpgrp`), ANSI stripping for clean LLM consumption, 50K-line rolling buffers (thread-safe deque), prompt-based command/response matching, and auto-cleanup on session overflow.

**Debugger Abstraction Layer**
Auto-detects GDB vs LLDB and translates abstract operations to debugger-specific syntax transparently. "Set breakpoint at 0x401000" becomes `break *0x401000` (GDB) or `breakpoint set --address 0x401000` (LLDB). The agent never needs to know which debugger is running.

**Three-Tier Context Management**
1. **Truncation** — tool output capped at 2000 lines / 50KB
2. **Pruning** — old tool results >500 chars replaced with stubs, last 10 messages protected
3. **Compaction** — Claude Haiku summarizes old conversation history, last 6 messages kept verbatim

This keeps the agent coherent across 40+ step analysis sessions without blowing the context window.

**Wire Protocol**
A typed async event bus with 15 event types (TEXT, THINKING, TOOL_CALL, TOOL_RESULT, OBSERVATION, HYPOTHESIS, FINDING, TARGET_INFO, SUBAGENT_BEGIN/END, COMPACTION, DMAIL, ERROR, STATUS) decouples agent execution from presentation. Both CLI and TUI subscribe to the same wire. Adding a web UI or API would just be another subscriber.

**TUI (Textual)**
Real-time streaming of agent reasoning and tool calls. Sidebar with tabs for Findings, Hypotheses, and Observations that update live. Status bar with step count, token usage, current agent, braille spinner. All Python logging redirected to status bar via custom handler.

### Novel Features

**D-Mail — Context Time-Travel**
Inspired by Steins;Gate. If the agent goes down a fundamentally wrong path (spent 20 steps on the wrong function), it can "send knowledge back in time" to a previous checkpoint. The context reverts and the learned knowledge is injected as a system message. The agent restarts with hindsight but without the polluted context. Implemented via a `BackToTheFuture` exception caught by the agent loop, which reverts the JSONL-backed context store.

**Progressive Skill Loading**
Instead of stuffing tool manuals into prompts (wasting context), agents call `activate_skill` on demand to load domain-specific references — rizin command cheat sheets, GDB workflows, common analysis patterns. Skills are discovered from a `skills/` directory organized by domain.

**Binary Name Masking**
The `--mask` flag copies the binary to an anonymized temp path (`target_<hash>`) so the agent can't cheat by inferring the binary's purpose from its filename. Essential for honest benchmarking.

**Autonomous Verification Loop**
The only AI system that doesn't just *guess* what a binary does — it *proves* it. Static analysis proposes a hypothesis with a confidence score. The orchestrator dispatches the dynamic agent to verify it at runtime. If confirmed, it becomes a finding with evidence. If rejected, it's recorded as rejected and the agent tries a different angle. No unverified claims are reported as findings.

---

## Claude Usage

Claude is the primary reasoning engine:

- **Claude Sonnet** powers the orchestrator's mission planning, the static agent's code comprehension (reasoning about decompiled C and assembly), and the coding agent's Python script generation
- **Claude Haiku** handles context compaction — summarizing old conversation history cheaply to keep the main model's context clean
- Both accessed via **litellm** for provider flexibility, but Claude is the default and recommended model
- Extended thinking support: Anthropic's thinking blocks are preserved and round-tripped through the streaming pipeline, enabling deeper reasoning on complex RE problems

---

## Challenges Surmounted

### Context Explosion
A single GDB session dumps thousands of lines of registers and memory. We built three-tier context management: tool-level truncation (2000 lines/50KB), pruning of old results into compact stubs, and LLM-based compaction using Claude Haiku that summarizes history while preserving recent messages verbatim.

### Agent Drift
Long-running agents accumulate context biased toward dead-end hypotheses. After 20 steps investigating the wrong function, the agent can't pivot — its context is polluted. We built D-Mail (Context Time-Travel): the agent sends knowledge back to a past checkpoint, the context reverts, and it restarts with hindsight. Implemented via a `BackToTheFuture` exception that reverts the JSONL context store.

### Making Debuggers Agent-Compatible
GDB/LLDB expect human interaction — terminal input, ANSI-colored output, prompt-based workflows. We built a managed PTY system: `subprocess.Popen` with `start_new_session=True` for process group isolation, ANSI stripping, 50K-line thread-safe rolling buffers, and prompt-based command/response matching (`send_and_match`). This makes debuggers reliably drivable by an LLM.

### GDB vs LLDB Abstraction
macOS ships LLDB, Linux ships GDB. Their syntax differs significantly. We built a command translation map that auto-detects the available debugger and transparently converts abstract operations to the correct syntax. The agent never knows which debugger is running.

### Decompiler Availability
Not every system has rz-ghidra. Our decompile tool tries `pdg` (rz-ghidra, best quality) → `pdc` (rz-dec, built-in) → `pdsf+pdf` (simplified summary + disassembly). The agent always gets something useful.

### Decoupling Agent from UI
A typed Wire Protocol with 15 event types lets both CLI and TUI subscribe to the same agent execution stream, enabling real-time rendering without code duplication.

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.12+ |
| LLM | Claude (Sonnet + Haiku) via litellm |
| Static Analysis | rizin + rz-ghidra |
| Binary Metadata | LIEF (ELF/PE/Mach-O) |
| Dynamic Analysis | GDB/LLDB via managed PTY |
| TUI | Textual |
| CLI | Typer |
| Validation | Pydantic |
| Build | Hatchling + uv |

**Hashtags:** python, claude, anthropic, cybersecurity, reverse-engineering, ai-agent, binary-analysis, litellm, textual, rizin

**Platforms:** macOS, Linux

---

## Track Application (Hackathon Prizes)

**Technical Depth:** 6,500+ lines across 43 source files, 26 specialized tools, hierarchical multi-agent orchestration, structured knowledge base with three-tier progression, context time-travel, managed pseudo-terminals with process group isolation, debugger abstraction layer, and a real-time TUI — every component purpose-built for the problem domain.

**Claude at the Core:** Two-model architecture — Claude Sonnet for reasoning (orchestration, code comprehension, hypothesis formation, script generation) + Claude Haiku for context compaction. Extended thinking support with signature round-tripping. Demonstrates sophisticated, production-grade use of Anthropic's model lineup.

**India Relevance:** India is digitizing critical infrastructure at unprecedented scale — UPI, Aadhaar, DigiLocker, CoWIN. The compiled binaries powering this infrastructure need security auditing, but the RE talent pool is tiny and expensive. REagent democratizes capability that was previously locked behind $2K+/year tools (IDA Pro) and rare human expertise. India's growing CTF community and cybersecurity workforce (CERT-In, defense, enterprise AppSec) gets a force multiplier.

**Novel Innovation:**
- The only AI system that *proves* findings via runtime debugger verification, not just guessing from static analysis
- D-Mail: context time-travel to escape agent drift — a novel solution to a fundamental problem in long-running agent tasks
- Progressive skill loading: on-demand domain reference loading instead of prompt stuffing
- Wire protocol: clean architectural separation enabling CLI + TUI + future web UI from the same agent core

**Why This Exists:** Born from years of competitive CTF reverse engineering and cybersecurity work at IIT (BHU). The security side of software needs the same AI tooling that the development side already has.
