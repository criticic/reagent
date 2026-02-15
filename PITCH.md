# reagent — Claude Code for Reverse Engineering

## One-liner

The autonomous AI agent that reverses engineered binaries to find zero-day vulnerabilities.

## What does your company do?

We build autonomous AI agents for reverse engineering (RE). While tools like Cursor excel at writing code, they fail at analyzing compiled binaries, proprietary firmware, and malware. reagent combines deep LLM reasoning with a "squad" of sub-agents that operate industry-standard tools (GDB, Rizin) to autonomously reverse engineer software, verify hypotheses at runtime, and uncover vulnerabilities that human analysts miss.

## What is the problem?

**The world runs on black boxes.** From medical devices to automotive ECUs, critical infrastructure depends on compiled code that is opaque to its users.

1.  **The Talent Gap:** There are fewer than 10,000 capable reverse engineers globally. They cost $300k+ and are fully booked.
2.  **The Liability Shift:** New laws (EU Cyber Resilience Act, US EO 14028) make companies liable for the security of third-party binaries they use but cannot analyze.
3.  **The "Grunt Work" Trap:** Experts spend 80% of their time on manual triage—renaming variables and mapping control flow—rather than finding exploits.

## What is your solution?

reagent is an autonomous "digital employee" for RE. You give it a binary and a goal (e.g., "Find the backdoor in this firmware").

1.  **Orchestrator:** Plans the mission.
2.  **Triage Agent:** Maps the attack surface.
3.  **Static Agent:** Decompiles code and forms hypotheses (e.g., "This looks like a buffer overflow").
4.  **Dynamic Agent:** **Verifies** the hypothesis by running the binary in a secure PTY, setting breakpoints, and inspecting memory.

## Why now?

Three forces have converged to make this possible today:

1.  **LLM Reasoning:** Models can finally reason about abstract assembly logic and pointer arithmetic.
2.  **Agentic Infrastructure:** We can now reliably "sandbox" AI tools, giving them safe access to debuggers and shells without risking the host system.
3.  **Regulatory Panic:** Governments are forcing vendors to SBOM (Software Bill of Materials) and audit binary blobs. The market has shifted from "nice to have" to "go to jail if you don't."

## Secret Sauce

1.  **Autonomous Verification (The "Groundedness" Loop):**
    Most AI coding tools guess. reagent verifies. If the Static agent thinks a function validates a password, the Dynamic agent *runs it*, inputs a test password, and reads the CPU registers to confirm the logic. We don't output hallucinations; we output proven facts.

2.  **Context Time-Travel (D-Mail):**
    Agents often go down rabbit holes. We built a proprietary "save state" system called D-Mail. If an agent hits a dead end, it sends a message "back in time" to a previous checkpoint, warning its past self to take a different path. This solves the "drift" problem inherent in long-running agent tasks.

## Technical Architecture

```
User: binary + goal
  |
  v
Orchestrator (Strategy & Dispatch)
  |
  +-- Triage Agent     (Metadata & Attack Surface)
  +-- Static Agent     (Decompilation & Pattern Matching)
  +-- Dynamic Agent    (Runtime Verification via GDB/PTY)
  |
  v
BinaryModel (Structured Knowledge Graph)
  |
  v
Verified Vulnerability Report
```

## Market

The "Binary Analysis" market is rapidly expanding beyond traditional security firms:
1.  **Defense & Intelligence:** Automated analysis of captured malware/firmware.
2.  **Enterprise AppSec:** Validating third-party closed-source dependencies (supply chain security).
3.  **Automotive & IoT:** Compliance testing for ECUs and firmware blobs.

**Total Addressable Market:** The Application Security market is $12B, but the "Black Box" auditing market is a blue ocean created by new regulation.

## Competition

| Feature | reagent | IDA Pro / Ghidra | Claude / Cursor |
|---|---|---|---|
| **Primary User** | AI Agent | Human Expert | Software Developer |
| **Runtime Access** | **Native (GDB/PTY)** | Manual Setup | None (Text only) |
| **Verification** | **Autonomous** | Human Required | None (Hallucinates) |
| **Input** | Binary / Executable | Binary / Executable | Source Code |

**Why we win:** Generalist coding agents (Claude/Cursor) cannot run debuggers or interpret hex dumps. Legacy tools (IDA/Ghidra) are purely passive. We are the first *active* agentic solution for binaries.

### Why not Claude Code / OpenCode / Gemini CLI?

General-purpose coding agents fail at binary analysis for structural reasons:

1.  **Wrong Abstraction Layer:** They are built to manipulate *source code* (text files). They cannot attach to a running process, read CPU registers, or interpret raw memory dumps. They are "blind" to the runtime state of a binary.
2.  **Context Explosion:** A single step in a debugger can generate 10,000 lines of state change. General agents choke on this data. reagent uses specialized rolling buffers and PTY management to filter this noise into signal.
3.  **Safety Alignment:** Ask ChatGPT to "find a vulnerability in this binary," and it will likely refuse. reagent is scoped for authorized security research, with prompts designed to navigate the ethical boundaries of vulnerability disclosure.
4.  **No Feedback Loop:** Without a debugger, a general agent can only *guess* what a binary does based on static strings. It cannot verify its guess. reagent's dynamic agent proves its findings by executing them.

## Team

[Your team details here]

## Ask

[Your ask here]
