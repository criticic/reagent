# GDB Debugging Workflows

Common debugging patterns for vulnerability research and binary analysis.

## Crash Analysis Workflow

1. **Reproduce crash**: `run < crash_input`
2. **Examine crash state**:
   ```
   bt                        # Backtrace
   info registers            # Register state
   x/i $pc                   # Faulting instruction
   x/16xg $rsp               # Stack contents
   ```
3. **Determine crash type**:
   - `SIGSEGV` at write: likely buffer overflow
   - `SIGSEGV` at read from controlled addr: info leak or use-after-free
   - `SIGABRT`: heap corruption detected by allocator
4. **Check control**: `p/x $rip` — is it a controlled value?

## Heap Exploitation Analysis

1. **Track allocations**: set breakpoints on malloc/free
   ```
   break malloc
   break free
   commands 1
     p/x $rdi
     bt 3
     continue
   end
   ```
2. **Examine heap state**: `x/32xg addr` around heap pointers
3. **Detect use-after-free**: break on free, note address, set watchpoint
   ```
   watch *(long*)freed_addr   # Break when freed memory is accessed
   ```
4. **Double-free**: track free() calls and check if same address freed twice

## Stack Buffer Overflow Exploitation

1. **Find overflow point**: breakpoint before and after vulnerable function
   ```
   break vulnerable_func
   break *(vulnerable_func + ret_offset)
   ```
2. **Check saved return address**:
   ```
   x/xg $rbp+8               # Saved RIP (x86-64)
   info frame                 # Frame details
   ```
3. **Determine offset**: compare buffer start to saved return address
   ```
   p/d ($rbp + 8) - $rsp     # Distance from stack top to saved RIP
   ```
4. **Check protections**:
   ```
   info proc mappings         # ASLR (randomized addresses?)
   checksec                   # If pwndbg/gef installed
   ```

## Format String Exploitation

1. **Verify format string**: send `%x.%x.%x.%x` as input
2. **Break at printf**: check arguments
   ```
   break printf
   x/s $rdi                   # Format string (first arg, x86-64)
   x/8xg $rsi                 # Following args
   ```
3. **Find offset**: count %x outputs to locate your input on stack

## Input Tracing

1. **Break at input functions**:
   ```
   break read
   break recv
   break fgets
   ```
2. **Track buffer through execution**:
   ```
   commands
     p/x $rdi                 # Buffer address (read/recv)
     p/d $rdx                 # Size
     finish
     x/s $rax                 # What was read (after return)
     continue
   end
   ```

## Anti-Debug Bypass

1. **Common checks to bypass**:
   ```
   break ptrace               # ptrace(PTRACE_TRACEME) check
   commands
     set $rax = 0             # Fake success
     continue
   end
   ```
2. **Timing checks**: set hardware breakpoints to avoid detection
   ```
   hbreak *0x401234           # Hardware breakpoint (invisible to some checks)
   ```

## Tips

- **Save/restore state**: `checkpoint` / `restart N` (Linux only)
- **Follow forks**: `set follow-fork-mode child` or `set detach-on-fork off`
- **Catch syscalls**: `catch syscall write` — break on specific syscalls
- **Log output**: `set logging on` then `set logging file gdb.log`
- **Python scripting**: `python gdb.execute("info registers")` for automation
