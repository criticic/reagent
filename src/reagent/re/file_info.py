"""File info tool using LIEF for structured binary metadata extraction."""

from __future__ import annotations

import logging
import os
from typing import Any, ClassVar

import lief
from pydantic import BaseModel, Field

from reagent.tool.base import BaseTool, ToolError, ToolOk, ToolResult

logger = logging.getLogger(__name__)


class FileInfoParams(BaseModel):
    path: str = Field(
        default="",
        description="Path to the binary file to inspect. Leave empty to use the analysis target.",
    )


class FileInfoTool(BaseTool[FileInfoParams]):
    """Extract structured metadata from a binary file using LIEF.

    Returns format, architecture, entry point, sections, imports, exports,
    security features, and other relevant metadata.
    """

    name: ClassVar[str] = "file_info"
    description: ClassVar[str] = (
        "Extract detailed metadata from a binary: format (ELF/PE/Mach-O), "
        "architecture, entry point, sections, imported/exported symbols, "
        "linked libraries, and security features (NX, PIE, canary, RELRO, etc.). "
        "This is typically the first tool to run on a new binary."
    )
    param_model: ClassVar[type[BaseModel]] = FileInfoParams

    def __init__(
        self,
        binary_path: str = "",
        binary_model: Any = None,
        wire: Any = None,
    ) -> None:
        self._binary_path = binary_path
        self._binary_model = binary_model
        self._wire = wire

    async def execute(self, params: FileInfoParams) -> ToolResult:
        path = params.path or self._binary_path
        if not path:
            return ToolError(
                output="No path provided and no default binary path configured."
            )
        if not os.path.isfile(path):
            # If the agent gave a bad path but we have a default, try that
            if params.path and self._binary_path and os.path.isfile(self._binary_path):
                path = self._binary_path
            else:
                return ToolError(output=f"File not found: {path}")

        try:
            binary = lief.parse(path)
        except Exception as e:
            return ToolError(output=f"LIEF could not parse '{path}': {e}")

        if binary is None:
            return ToolError(
                output=f"LIEF could not parse '{path}'. It may not be a recognized binary format."
            )

        lines: list[str] = []

        # Detect format and dispatch
        if lief.is_elf(path):
            self._format_elf(binary, lines)
        elif lief.is_pe(path):
            self._format_pe(binary, lines)
        elif lief.is_macho(path):
            self._format_macho(binary, lines)
        else:
            lines.append(f"Format: Unknown")
            self._format_generic(binary, lines)

        # Populate BinaryModel target info and emit wire event
        self._update_target(binary, path)

        return ToolOk(
            output="\n".join(lines),
            brief=f"file_info: {os.path.basename(path)}",
        )

    # ----- ELF -----

    def _format_elf(self, binary: Any, lines: list[str]) -> None:
        lines.append("Format: ELF")
        header = binary.header

        # Basic info
        machine = str(header.machine_type).split(".")[-1]
        elf_class = str(header.identity_class).split(".")[-1]
        elf_type = str(header.file_type).split(".")[-1]
        endian = str(header.identity_data).split(".")[-1]
        lines.append(f"Class: {elf_class}")
        lines.append(f"Type: {elf_type}")
        lines.append(f"Machine: {machine}")
        lines.append(f"Endian: {endian}")
        lines.append(f"Entry point: 0x{header.entrypoint:x}")

        # Security features
        lines.append("")
        lines.append("== Security Features ==")

        # PIE
        is_pie = binary.is_pie
        lines.append(f"PIE: {'Yes' if is_pie else 'No'}")

        # NX (check PT_GNU_STACK)
        has_nx = False
        for seg in binary.segments:
            seg_type = str(seg.type).split(".")[-1]
            if seg_type == "GNU_STACK":
                # If the segment is not executable, NX is enabled
                has_nx = not bool(seg.flags & 1)  # PF_X = 1
                break
        lines.append(f"NX: {'Yes' if has_nx else 'No'}")

        # RELRO
        has_relro = False
        full_relro = False
        for seg in binary.segments:
            seg_type = str(seg.type).split(".")[-1]
            if seg_type == "GNU_RELRO":
                has_relro = True
                break
        if has_relro:
            # Full RELRO also requires BIND_NOW
            try:
                for entry in binary.dynamic_entries:
                    entry_tag = str(entry.tag).split(".")[-1]
                    if entry_tag in ("BIND_NOW", "FLAGS") and "NOW" in str(entry):
                        full_relro = True
                        break
            except Exception:
                pass
        relro_str = "Full" if full_relro else ("Partial" if has_relro else "No")
        lines.append(f"RELRO: {relro_str}")

        # Stack canary (check for __stack_chk_fail import)
        has_canary = any(
            "stack_chk" in str(sym.name).lower() for sym in binary.imported_symbols
        )
        lines.append(f"Stack Canary: {'Yes' if has_canary else 'No'}")

        # FORTIFY (check for _chk suffix in imports)
        fortified = [
            str(sym.name)
            for sym in binary.imported_symbols
            if "_chk" in str(sym.name) and "stack" not in str(sym.name).lower()
        ]
        lines.append(f"FORTIFY: {'Yes' if fortified else 'No'}")

        # Sections summary
        lines.append("")
        lines.append("== Sections ==")
        lines.append(f"{'Name':<20} {'VAddr':<14} {'Size':>8}  {'Entropy':>7}")
        lines.append("-" * 55)
        for section in binary.sections:
            name = section.name or "(null)"
            vaddr = f"0x{section.virtual_address:08x}"
            size = section.size
            entropy = section.entropy
            lines.append(f"{name:<20} {vaddr:<14} {size:>8}  {entropy:>7.4f}")

        # Imports
        imported = list(binary.imported_symbols)
        if imported:
            lines.append("")
            lines.append(f"== Imported Symbols ({len(imported)}) ==")
            for sym in imported[:50]:  # Cap at 50 for readability
                lines.append(f"  {sym.name}")
            if len(imported) > 50:
                lines.append(f"  ... and {len(imported) - 50} more")

        # Exports
        exported = list(binary.exported_symbols)
        if exported:
            lines.append("")
            lines.append(f"== Exported Symbols ({len(exported)}) ==")
            for sym in exported[:50]:
                lines.append(f"  {sym.name}")
            if len(exported) > 50:
                lines.append(f"  ... and {len(exported) - 50} more")

        # Libraries
        libs = list(binary.libraries)
        if libs:
            lines.append("")
            lines.append(f"== Libraries ({len(libs)}) ==")
            for lib in libs:
                lines.append(f"  {lib}")

    # ----- PE -----

    def _format_pe(self, binary: Any, lines: list[str]) -> None:
        lines.append("Format: PE")
        header = binary.header

        machine = str(header.machine).split(".")[-1]
        lines.append(f"Machine: {machine}")

        opt = binary.optional_header
        lines.append(f"Subsystem: {str(opt.subsystem).split('.')[-1]}")
        lines.append(f"Entry point: 0x{opt.addressof_entrypoint:x}")
        lines.append(f"Image base: 0x{opt.imagebase:x}")

        # Security features
        lines.append("")
        lines.append("== Security Features ==")

        # ASLR / DYNAMIC_BASE
        dll_chars = opt.dll_characteristics_lists
        dll_chars_names = [str(c).split(".")[-1] for c in dll_chars]
        lines.append(f"ASLR: {'Yes' if 'DYNAMIC_BASE' in dll_chars_names else 'No'}")
        lines.append(f"DEP/NX: {'Yes' if 'NX_COMPAT' in dll_chars_names else 'No'}")
        lines.append(
            f"High Entropy ASLR: {'Yes' if 'HIGH_ENTROPY_VA' in dll_chars_names else 'No'}"
        )
        lines.append(f"CFG: {'Yes' if 'GUARD_CF' in dll_chars_names else 'No'}")

        # Sections
        lines.append("")
        lines.append("== Sections ==")
        lines.append(
            f"{'Name':<10} {'VAddr':<14} {'VSize':>8} {'RawSize':>8}  {'Entropy':>7}  {'Chars'}"
        )
        lines.append("-" * 70)
        for section in binary.sections:
            name = section.name.rstrip("\x00")
            vaddr = f"0x{section.virtual_address:08x}"
            vsize = section.virtual_size
            rsize = section.sizeof_raw_data
            entropy = section.entropy
            chars = ", ".join(
                str(c).split(".")[-1] for c in section.characteristics_lists
            )
            lines.append(
                f"{name:<10} {vaddr:<14} {vsize:>8} {rsize:>8}  {entropy:>7.4f}  {chars}"
            )

        # Imports
        if binary.imports:
            lines.append("")
            lines.append("== Imports ==")
            for imp in binary.imports:
                lines.append(f"  {imp.name}:")
                entries = list(imp.entries)[:20]
                for entry in entries:
                    if entry.name:
                        lines.append(f"    {entry.name}")
                remaining = len(list(imp.entries)) - 20
                if remaining > 0:
                    lines.append(f"    ... and {remaining} more")

        # Exports
        if binary.has_exports:
            export_entries = list(binary.get_export().entries)
            if export_entries:
                lines.append("")
                lines.append(f"== Exports ({len(export_entries)}) ==")
                for entry in export_entries[:50]:
                    lines.append(f"  {entry.name}")
                if len(export_entries) > 50:
                    lines.append(f"  ... and {len(export_entries) - 50} more")

    # ----- Mach-O -----

    def _format_macho(self, binary: Any, lines: list[str]) -> None:
        lines.append("Format: Mach-O")
        header = binary.header

        cpu = str(header.cpu_type).split(".")[-1]
        file_type = str(header.file_type).split(".")[-1]
        lines.append(f"CPU: {cpu}")
        lines.append(f"Type: {file_type}")
        lines.append(f"Entry point: 0x{binary.entrypoint:x}")

        # Flags
        flags = [str(f).split(".")[-1] for f in header.flags_list]
        if flags:
            lines.append(f"Flags: {', '.join(flags)}")

        # Security
        lines.append("")
        lines.append("== Security Features ==")
        lines.append(f"PIE: {'Yes' if 'PIE' in flags else 'No'}")

        # NX
        has_nx = getattr(binary, "has_nx", False)
        lines.append(f"NX: {'Yes' if has_nx else 'No'}")

        # Code signing — use direct attribute, not command iteration
        has_codesign = getattr(binary, "has_code_signature", False)
        lines.append(f"Code Signed: {'Yes' if has_codesign else 'No'}")

        # Sections
        lines.append("")
        lines.append("== Sections ==")
        lines.append(f"{'Segment/Section':<30} {'VAddr':<14} {'Size':>8}")
        lines.append("-" * 55)
        for section in binary.sections:
            seg_name = section.segment_name if hasattr(section, "segment_name") else ""
            name = f"{seg_name}/{section.name}" if seg_name else section.name
            vaddr = f"0x{section.virtual_address:08x}"
            size = section.size
            lines.append(f"{name:<30} {vaddr:<14} {size:>8}")

        # Libraries
        libs = list(binary.libraries)
        if libs:
            lines.append("")
            lines.append(f"== Libraries ({len(libs)}) ==")
            for lib in libs:
                lines.append(f"  {lib.name}")

        # Imports
        imported = list(binary.imported_symbols)
        if imported:
            lines.append("")
            lines.append(f"== Imported Symbols ({len(imported)}) ==")
            for sym in imported[:50]:
                lines.append(f"  {sym.name}")
            if len(imported) > 50:
                lines.append(f"  ... and {len(imported) - 50} more")

        # Exports
        exported = list(binary.exported_symbols)
        if exported:
            lines.append("")
            lines.append(f"== Exported Symbols ({len(exported)}) ==")
            for sym in exported[:50]:
                lines.append(f"  {sym.name}")
            if len(exported) > 50:
                lines.append(f"  ... and {len(exported) - 50} more")

    # ----- Generic fallback -----

    def _format_generic(self, binary: Any, lines: list[str]) -> None:
        if hasattr(binary, "entrypoint"):
            lines.append(f"Entry point: 0x{binary.entrypoint:x}")
        sections = list(binary.sections) if hasattr(binary, "sections") else []
        if sections:
            lines.append(f"Sections: {len(sections)}")
            for s in sections:
                lines.append(f"  {s.name}")

    # ----- Target info update -----

    def _update_target(self, binary: Any, path: str) -> None:
        """Populate BinaryModel.target and emit a TARGET_INFO wire event."""
        if self._binary_model is None:
            return

        target = self._binary_model.target
        target.path = path

        target_data: dict[str, Any] = {}

        try:
            if lief.is_elf(path):
                header = binary.header
                target.format = "ELF"
                target.arch = str(header.machine_type).split(".")[-1]
                target.endian = (
                    "little" if "LSB" in str(header.identity_data) else "big"
                )
                target.bits = 64 if "CLASS64" in str(header.identity_class) else 32
                target.pie = binary.is_pie
                target.stripped = not any(
                    str(s.type).split(".")[-1] == "SYMTAB" for s in binary.sections
                )
                # NX
                for seg in binary.segments:
                    if "GNU_STACK" in str(seg.type):
                        target.nx = not bool(seg.flags & 1)
                        break
                # Canary
                target.canary = any(
                    "stack_chk" in str(sym.name).lower()
                    for sym in binary.imported_symbols
                )
                # RELRO
                has_relro = any("GNU_RELRO" in str(seg.type) for seg in binary.segments)
                if has_relro:
                    target.relro = "partial"
                    try:
                        for entry in binary.dynamic_entries:
                            if "BIND_NOW" in str(entry.tag) or (
                                "FLAGS" in str(entry.tag) and "NOW" in str(entry)
                            ):
                                target.relro = "full"
                                break
                    except Exception:
                        pass
                else:
                    target.relro = "none"

            elif lief.is_pe(path):
                target.format = "PE"
                target.arch = str(binary.header.machine).split(".")[-1]
                target.endian = "little"
                target.bits = 64 if "AMD64" in target.arch else 32
                dll_chars = [
                    str(c).split(".")[-1]
                    for c in binary.optional_header.dll_characteristics_lists
                ]
                target.pie = "DYNAMIC_BASE" in dll_chars
                target.nx = "NX_COMPAT" in dll_chars

            elif lief.is_macho(path):
                header = binary.header
                target.format = "Mach-O"
                target.arch = str(header.cpu_type).split(".")[-1]
                target.endian = "little"
                target.bits = 64 if "64" in target.arch else 32
                flags = [str(f).split(".")[-1] for f in header.flags_list]
                target.pie = "PIE" in flags
                target.nx = getattr(binary, "has_nx", False)

            # Build target data dict for wire event
            target_data = {
                "format": target.format,
                "arch": target.arch,
                "bits": target.bits,
                "endian": target.endian,
                "stripped": target.stripped,
                "pie": target.pie,
                "nx": target.nx,
                "canary": target.canary,
                "relro": target.relro,
            }

        except Exception as e:
            logger.warning("Failed to populate target info: %s", e)
            return

        if self._wire is not None:
            try:
                self._wire.send_target_info(target_data)
            except Exception as e:
                logger.warning("Failed to send target info wire event: %s", e)
