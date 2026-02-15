# Rizin Analysis Patterns

Common analysis workflows and patterns for binary reverse engineering with rizin.

## Vulnerability Hunting Workflow

1. **Triage**: `aaa` then `afl` — get function list, look for interesting names
2. **Find dangerous functions**: search for calls to `strcpy`, `sprintf`, `gets`, `system`
   ```
   axt @sym.imp.strcpy     # Find all callers of strcpy
   axt @sym.imp.system     # Find all callers of system
   axt @sym.imp.gets       # Find all callers of gets
   ```
3. **Decompile callers**: `pdg @caller_addr` for each caller
4. **Trace data flow**: follow xrefs backwards from dangerous call to understand input sources

## Format String Vulnerability Detection

1. Find calls to printf-family without format string:
   ```
   axt @sym.imp.printf
   axt @sym.imp.fprintf
   axt @sym.imp.sprintf
   ```
2. Decompile each caller — check if first arg is user-controlled
3. Look for patterns: `printf(user_input)` instead of `printf("%s", user_input)`

## Buffer Overflow Detection

1. Find fixed-size stack buffers in decompiled output
2. Check if input length is validated before copy
3. Key functions to trace: `read`, `recv`, `fgets`, `scanf`, `strcpy`, `strcat`, `memcpy`
4. Look for patterns:
   - `char buf[64]; strcpy(buf, input);` — classic overflow
   - `char buf[64]; read(fd, buf, 0x200);` — read overflow

## Binary Diffing (Before/After Patch)

1. Analyze both binaries with `aaa`
2. Compare function lists: `afl` on each
3. Look for new/removed functions
4. Decompile changed functions side by side

## Crypto Identification

1. Search for crypto constants:
   ```
   /x 6a09e667   # SHA-256 constant
   /x 67452301   # MD5 constant
   /x 01234567   # DES constant
   ```
2. Look for large tables (S-boxes): `pxw 256 @addr`
3. Find entropy hotspots in functions (lots of XOR/shift operations)

## String-Based Analysis

1. Extract all strings: `izz`
2. Look for error messages, format strings, file paths
3. Xref interesting strings to find the code that uses them:
   ```
   axt @str.error_message
   ```
4. Decompile functions that reference interesting strings

## Identifying Main When Stripped

1. Start at entry point: `pdf @entry0`
2. In ELF: look for `__libc_start_main` call — first argument is `main`
3. In PE: look for call after `GetCommandLine` / `GetModuleHandle`
4. Name it: `afn main @detected_addr`
