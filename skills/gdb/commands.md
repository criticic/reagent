# GDB Command Reference

Quick reference for GDB commands when debugging binaries through reagent's debugger tools. Use this to understand what the debug tools do and to plan debugging strategies.

## Starting & Attaching

```
gdb ./binary               # Start with binary
gdb -p PID                  # Attach to process
gdb -q ./binary             # Quiet mode (no banner)
gdb --args ./binary arg1    # Start with arguments
run [args]                  # Run/restart program
start                       # Run and stop at main()
```

## Breakpoints

```
break main                  # Break at function
break *0x08048000           # Break at address
break file.c:42             # Break at source line
break if x > 10             # Conditional breakpoint
info breakpoints            # List breakpoints
delete N                    # Delete breakpoint N
disable N                   # Disable breakpoint N
enable N                    # Enable breakpoint N
tbreak func                 # Temporary (one-shot) breakpoint
```

## Execution Control

```
continue (c)                # Continue execution
step (s)                    # Step into (source-level)
stepi (si)                  # Step one instruction
next (n)                    # Step over (source-level)
nexti (ni)                  # Step over one instruction
finish                      # Run until current function returns
until LOCATION              # Run until location reached
```

## Registers

```
info registers              # All general-purpose registers
info all-registers          # All registers including FP/SIMD
p $rax                      # Print specific register
set $rax = 0x42             # Modify register
```

## Memory

```
x/Nfx addr                  # Examine memory (N units, format f, size x)
x/16xb $rsp                 # 16 bytes in hex from stack pointer
x/4xg $rsp                  # 4 giant (8-byte) words in hex
x/s addr                    # Print as string
x/10i $rip                  # Disassemble 10 instructions
```

### Memory Format Codes
- Format: `x` hex, `d` decimal, `s` string, `i` instruction, `c` char
- Size: `b` byte, `h` halfword (2B), `w` word (4B), `g` giant (8B)

## Stack & Backtrace

```
backtrace (bt)              # Stack backtrace
bt full                     # Backtrace with locals
frame N                     # Select frame N
up / down                   # Navigate frames
info frame                  # Current frame details
info locals                 # Local variables
info args                   # Function arguments
```

## Expression Evaluation

```
print expr                  # Evaluate expression
p/x expr                    # Print in hex
p (char*)0x08048000         # Cast and print
set var = value             # Modify variable
call func(args)             # Call function in inferior
```

## Watchpoints

```
watch expr                  # Break when expr changes (write)
rwatch expr                 # Break on read
awatch expr                 # Break on read or write
info watchpoints            # List watchpoints
```

## Process Info

```
info proc mappings          # Memory mappings
info sharedlibrary          # Loaded libraries
info threads                # Thread list
thread N                    # Switch to thread N
```

## Signal Handling

```
info signals                # Signal handling table
handle SIGSEGV nostop        # Don't stop on SIGSEGV
handle SIGINT stop           # Stop on SIGINT
```

## Disassembly

```
disassemble func            # Disassemble function
disas $pc, $pc+50           # Disassemble range
set disassembly-flavor intel  # Intel syntax
set disassembly-flavor att    # AT&T syntax (default)
```

## Tips for Agent Use

1. **Set breakpoints before `run`** — plan your breakpoints based on static analysis first
2. **Use `stepi`/`nexti`** for instruction-level debugging (source-level `step`/`next` require debug info)
3. **Check return values**: after `finish`, the return value is in `$rax` (x86-64) or `$x0` (ARM64)
4. **Examine the stack** with `x/16xg $rsp` to see stack contents as 8-byte values
5. **Conditional breakpoints** are powerful: `break *0x401234 if $rax == 0` avoids manual checking
6. **Watchpoints** are slow but invaluable for tracking when/where a value changes
7. **`info proc mappings`** shows heap/stack/library addresses — useful for exploit development
8. **On macOS use LLDB instead** — reagent auto-detects and translates commands
