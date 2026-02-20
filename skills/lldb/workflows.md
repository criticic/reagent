# LLDB Debugging Workflows

Common debugging patterns for vulnerability research and binary analysis on macOS and Linux using LLDB.

## Crash Analysis Workflow

1. **Reproduce crash**: `run` with crash input (set args first or redirect stdin)
   ```
   settings set target.input-path crash_input
   run
   ```
2. **Examine crash state**:
   ```
   bt                                    # Backtrace
   register read                         # Register state
   disassemble --pc --count 1            # Faulting instruction
   memory read --size 8 --count 16 $rsp  # Stack contents
   ```
3. **Determine crash type**:
   - `EXC_BAD_ACCESS` (SIGSEGV): memory access violation
   - Write to bad addr: likely buffer overflow
   - Read from controlled addr: info leak or use-after-free
   - `SIGABRT`: heap corruption or assertion failure
4. **Check control**: `p/x $rip` — is it a controlled value?

## Heap Exploitation Analysis

1. **Track allocations**: set breakpoints on malloc/free
   ```
   breakpoint set --name malloc
   breakpoint set --name free
   breakpoint command add 1
   > p/x $rdi
   > bt 3
   > continue
   > DONE
   ```
2. **Examine heap state**: `memory read --size 8 --count 32 addr`
3. **Detect use-after-free**: break on free, note address, set watchpoint
   ```
   watchpoint set expression -- (long*)freed_addr
   ```
4. **Double-free**: track free() calls and check if same address freed twice

## Stack Buffer Overflow Exploitation

1. **Find overflow point**: breakpoint before and after vulnerable function
   ```
   breakpoint set --name vulnerable_func
   breakpoint set --address (vulnerable_func + ret_offset)
   ```
2. **Check saved return address** (x86-64):
   ```
   memory read --size 8 --count 1 ($rbp + 8)   # Saved RIP
   frame info                                    # Frame details
   ```
3. **Determine offset**: compare buffer start to saved return address
   ```
   p/d ($rbp + 8) - $rsp      # Distance from stack top to saved RIP
   ```
4. **Check protections**:
   ```
   image list                   # Check ASLR (randomized addresses?)
   target modules dump sections # Section permissions
   ```

## Format String Exploitation

1. **Verify format string**: send `%x.%x.%x.%x` as input
2. **Break at printf**: check arguments
   ```
   breakpoint set --name printf
   run
   # At breakpoint:
   memory read --format c-string $rdi     # Format string (x86-64)
   memory read --size 8 --count 8 $rsi    # Following args
   ```
3. **Find offset**: count %x outputs to locate your input on stack

## Input Tracing

1. **Break at input functions**:
   ```
   breakpoint set --name read
   breakpoint set --name recv
   breakpoint set --name fgets
   ```
2. **Track buffer through execution**:
   ```
   breakpoint command add 1
   > p/x $rdi
   > p/d $rdx
   > finish
   > memory read --format c-string $rax
   > continue
   > DONE
   ```

## Anti-Debug Bypass

1. **Common checks to bypass** (ptrace):
   ```
   breakpoint set --name ptrace
   breakpoint command add 1
   > thread return 0
   > continue
   > DONE
   ```
2. **sysctl-based detection** (macOS):
   ```
   breakpoint set --name sysctl
   breakpoint command add 1
   > thread return 0
   > continue
   > DONE
   ```
3. **Timing checks**: use `thread step-inst` sparingly near timing-sensitive code

## Mach-O / macOS Specific

1. **Code signing issues**: `codesign --remove-signature binary` before debugging
2. **Entitlements**: `codesign -d --entitlements :- binary`
3. **dyld info**:
   ```
   image list                           # All loaded dylibs
   image lookup --address 0x...         # Resolve address to symbol
   image dump symtab binary_name        # Full symbol table
   ```
4. **Objective-C runtime** (if applicable):
   ```
   expression -- (void)NSLog(@"debug: %@", obj)
   breakpoint set --selector viewDidLoad
   ```

## Tips

- **Process plugins**: `process launch --plugin posix` on macOS for better POSIX signal handling
- **Follow forks**: `settings set target.process.follow-fork-mode child`
- **Catch syscalls** (Linux): not natively supported — use `breakpoint set --name syscall_name` instead
- **Script automation**: `script lldb.debugger.HandleCommand("register read")`
- **Python scripting**: `command script import my_script.py` for custom commands
- **Save breakpoints**: `breakpoint write -f bp.json` / `breakpoint read -f bp.json`
