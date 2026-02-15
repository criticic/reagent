# Rizin Command Reference

Quick reference for rizin commands used through rzpipe. These commands are what rizin tools execute internally — use this to understand output formats and to craft custom analysis via the shell tool when the specialized tools are insufficient.

## Analysis Commands

```
aaa          # Full auto-analysis (run first)
afl          # List all functions
afll         # List functions with details (size, calls, etc.)
afl~name     # Filter functions by name
afi @addr    # Function info at address
afn name @addr  # Rename function
```

## Disassembly

```
pdf @addr    # Disassemble function at addr
pd N @addr   # Disassemble N instructions at addr
pds @addr    # Disassembly summary (calls + strings)
pdsf @addr   # Function summary (calls + strings + jumps)
pi N @addr   # Print N instructions (no address prefix)
```

## Decompilation

```
pdg @addr    # Ghidra decompiler (rz-ghidra plugin, best quality)
pdc @addr    # rz-dec decompiler (built-in, simpler)
```

## Strings

```
iz           # Strings in data sections
izz          # Strings in entire binary
iz~pattern   # Filter strings
```

## Cross-References

```
axt @addr    # Xrefs TO this address (who calls/references this)
axf @addr    # Xrefs FROM this address (what this calls/references)
axtj @addr   # Xrefs TO in JSON format
```

## Sections & Segments

```
iS           # List sections
iSS          # List segments
iE           # List exports
ii           # List imports
```

## Seeking & Navigation

```
s addr       # Seek to address
s sym.main   # Seek to symbol
s entry0     # Seek to entry point
```

## Flags & Symbols

```
fl           # List all flags
fl~name      # Filter flags
f name @addr # Set flag at address
```

## Search

```
/ pattern    # Search bytes (hex: \x41\x42)
/x 4142      # Search hex pattern
/r addr      # Find refs to address
```

## Types & Structures

```
t            # List types
ts           # List structs
td "type"    # Define type from C declaration
```

## Binary Info

```
i            # File info
ie           # Entrypoint
iM           # Binary main addr
ih           # Headers
il           # Libraries
ir           # Relocations
```

## Output Modifiers

```
cmd~filter   # Grep output (internal grep)
cmd~:N       # Select Nth column
cmdj         # JSON output (append j to most commands)
cmd | head   # Pipe to shell
```

## Address Formats

- `0x08048000` — absolute address
- `sym.main` — symbol name
- `entry0` — entry point
- `@` prefix for "at address" in commands: `pdf @ sym.main`

## Tips for Agent Use

1. **Always run `aaa` first** before any analysis commands
2. **Use `j` suffix** for JSON output when parsing results (e.g., `aflj`, `axtj`)
3. **Function names**: `sym.` prefix for named, `fcn.` for auto-detected
4. **Try `pdg` first** for decompilation, fall back to `pdc` if rz-ghidra unavailable
5. **Combine xrefs with decompilation**: find callers with `axt`, then decompile each
