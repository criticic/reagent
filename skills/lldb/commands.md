# LLDB Command Reference

Quick reference for LLDB commands when debugging binaries through reagent's debugger tools. LLDB is the default debugger on macOS and is increasingly used on Linux.

## Starting & Attaching

```
lldb ./binary               # Start with binary
lldb -p PID                 # Attach to process
lldb --no-use-colors binary # No ANSI colors (used by reagent)
settings set target.run-args arg1 arg2  # Set arguments
run                         # Run/restart program
process launch --stop-at-entry  # Run and stop before main()
```

## Breakpoints

```
breakpoint set --name main           # Break at function (b main)
breakpoint set --address 0x08048000  # Break at address (b -a 0x...)
breakpoint set --file f.c --line 42  # Break at source line
breakpoint set --name func --condition 'x > 10'  # Conditional
breakpoint list                      # List breakpoints
breakpoint delete N                  # Delete breakpoint N
breakpoint disable N                 # Disable breakpoint N
breakpoint enable N                  # Enable breakpoint N
breakpoint set --one-shot --name func  # Temporary (one-shot)
```

### Shorthand

```
b main                      # Short for breakpoint set --name main
b 0x401000                  # Short for breakpoint set --address
br l                        # Short for breakpoint list
br del 1                    # Short for breakpoint delete 1
```

## Execution Control

```
continue (c)                # Continue execution
thread step-in (s)          # Step into (source-level)
thread step-inst (si)       # Step one instruction
thread step-over (n)        # Step over (source-level)
thread step-inst-over (ni)  # Step over one instruction
thread step-out (finish)    # Run until current function returns
thread until --address 0x.. # Run until address reached
```

## Registers

```
register read               # All general-purpose registers
register read --all         # All registers including FP/SIMD
register read rax           # Read specific register
register write rax 0x42     # Modify register
p $rax                      # Print register value
```

## Memory

```
memory read addr                              # Read memory (default format)
memory read addr --count 16 --format hex      # 16 units in hex
memory read --size 1 --count 32 $rsp          # 32 bytes from stack
memory read --format bytes $rsp $rsp+64       # Byte dump of range
x addr                                        # Shorthand for memory read
memory read --format instruction $pc $pc+40   # Disassemble from PC
```

### Memory Format Options
- `--format`: `hex`, `decimal`, `bytes`, `c-string`, `instruction`, `float`
- `--size`: `1` (byte), `2` (half), `4` (word), `8` (double word)
- `--count`: number of units to display

## Stack & Backtrace

```
bt                          # Stack backtrace
bt all                      # All threads' backtraces
frame select N              # Select frame N (frame N)
up / down                   # Navigate frames
frame info                  # Current frame details
frame variable              # Local variables + arguments
frame variable --no-args    # Locals only
frame variable --no-locals  # Arguments only
```

## Expression Evaluation

```
expression -- expr          # Evaluate expression (p expr)
p expr                      # Short for expression
p/x expr                    # Print in hex
p (char*)0x08048000         # Cast and print
expression -- var = value   # Modify variable
expression -- (void)func()  # Call function in inferior
```

## Watchpoints

```
watchpoint set variable var             # Break when var changes
watchpoint set expression -- &var       # Watch address
watchpoint set expression -w read -- &var  # Break on read
watchpoint list                         # List watchpoints
watchpoint delete N                     # Delete watchpoint N
```

## Process Info

```
image list                  # Loaded images (libraries)
process status              # Current process state
thread list                 # Thread list
thread select N             # Switch to thread N
target modules dump sections  # Section info
image lookup --address 0x.. # Find symbol at address
```

## Signal Handling

```
process handle SIGSEGV --stop false     # Don't stop on SIGSEGV
process handle SIGINT --stop true       # Stop on SIGINT
process handle                          # Show signal handling table
```

## Disassembly

```
disassemble --name func              # Disassemble function (di -n func)
disassemble --start-address 0x401000 --count 20  # From address
disassemble --frame                  # Current frame
disassemble --pc --count 10          # From current PC
settings set target.x86-disassembly-flavor intel  # Intel syntax
```

## Tips for Agent Use

1. **Set breakpoints before `run`** — plan breakpoints based on static analysis first
2. **Use `si`/`ni`** for instruction-level debugging (source-level `s`/`n` require debug symbols)
3. **Check return values**: after `finish`, the return value is in `$rax` (x86-64) or `$x0` (ARM64)
4. **Examine the stack** with `memory read --size 8 --count 16 $rsp` to see stack contents
5. **Conditional breakpoints** avoid manual checking: `b -a 0x401234 -c '$rax == 0'`
6. **Watchpoints** are slower but invaluable for tracking when/where a value changes
7. **`image list`** shows library load addresses — useful for computing ASLR offsets
8. **On macOS, LLDB is the native debugger** — no need to install GDB
9. **`image lookup -a $pc`** quickly tells you what function you're in
10. **`register read --format decimal`** shows registers in decimal instead of hex
