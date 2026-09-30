"""Assemble the mixed 16/32-bit AIOS boot layer with Keystone."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys
from typing import Tuple

from keystone import KS_ARCH_X86, KS_MODE_16, KS_MODE_32, Ks, KsError

MBR_CODE_LIMIT = 446
MBR_SIZE = 512


def _region(source: str, start: str, end: str | None) -> str:
    begin = source.index(start) + len(start)
    finish = source.index(end, begin) if end is not None else len(source)
    return source[begin:finish]


def _replace_constants(source: str, sectors: int, kernel_bytes: int,
                       kernel_lba: int, pm_entry: int) -> str:
    replacements = {
        "KERNEL_SECTORS": str(sectors),
        "KERNEL_BYTES": str(kernel_bytes),
        "KERNEL_LBA": str(kernel_lba),
        "PM_ENTRY": hex(pm_entry),
    }
    rendered = source
    for name, value in replacements.items():
        rendered = re.sub(rf"\b{name}\b", value, rendered)
    return rendered


def _assemble(text: str, mode: int, address: int) -> bytes:
    assembler = Ks(KS_ARCH_X86, mode)
    cleaned_lines = []
    for raw_line in text.splitlines():
        instruction = raw_line.split(";", 1)[0].strip()
        if instruction:
            cleaned_lines.append(instruction)
    try:
        encoding, _ = assembler.asm("\n".join(cleaned_lines), addr=address, as_bytes=True)
    except KsError as error:
        statement = error.get_asm_count() if hasattr(error, "get_asm_count") else -1
        raise RuntimeError(
            f"Keystone 汇编失败（statement={statement}）: {error}"
        ) from error
    return bytes(encoding)


def assemble_payload(source_path: Path, sectors: int, kernel_bytes: int,
                     kernel_lba: int, load_address: int) -> bytes:
    """Assemble the common boot payload at its real-mode load address."""
    if sectors <= 0 or sectors > 127:
        raise ValueError("kernel 扇区数必须在 1..127（EDD 单次读取限制）")
    source = source_path.read_text(encoding="utf-8")
    source16 = _region(source, "[BITS16]", "[BITS32]")
    source32 = _region(source, "[BITS32]", None)
    pm_address = 0
    code16 = b""
    for _ in range(4):
        code16 = _assemble(
            _replace_constants(source16, sectors, kernel_bytes, kernel_lba, pm_address),
            KS_MODE_16,
            load_address,
        )
        measured = load_address + len(code16)
        if measured == pm_address:
            break
        pm_address = measured
    code16 = _assemble(
        _replace_constants(source16, sectors, kernel_bytes, kernel_lba, pm_address),
        KS_MODE_16,
        load_address,
    )
    pm_address = load_address + len(code16)
    code32 = _assemble(
        _replace_constants(source32, sectors, kernel_bytes, kernel_lba, pm_address),
        KS_MODE_32,
        pm_address,
    )
    return code16 + code32


def _signed_sector(code: bytes, code_limit: int = MBR_CODE_LIMIT) -> bytes:
    if len(code) > code_limit:
        raise RuntimeError(f"引导代码超限 {len(code) - code_limit} 字节")
    return code + bytes(code_limit - len(code)) + bytes(510 - code_limit) + b"\x55\xAA"


def assemble_boot(source_path: Path, output_path: Path, sectors: int,
                  kernel_bytes: int, kernel_lba: int = 1) -> Tuple[int, int]:
    """Assemble and write one partition-table-safe 512-byte MBR."""
    code = assemble_payload(source_path, sectors, kernel_bytes, kernel_lba, 0x7C00)
    if len(code) > MBR_CODE_LIMIT:
        over = len(code) - MBR_CODE_LIMIT
        raise RuntimeError(
            f"MBR 代码区超限 {over} 字节（{len(code)}/{MBR_CODE_LIMIT}）；"
            "请使用 --two-sector 降级"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(_signed_sector(code))
    return len(code), MBR_CODE_LIMIT - len(code)


def assemble_two_sector(source_path: Path, output_path: Path, stage2_path: Path,
                        sectors: int, kernel_bytes: int) -> Tuple[int, int]:
    """Build a tiny MBR loader plus a full second-stage boot-layer sector."""
    stage0_source = """
        cli
        xor ax, ax
        mov ds, ax
        mov es, ax
        mov ss, ax
        mov sp, 0x7C00
        sti
        mov word ptr [0x0600], 0x0010
        mov word ptr [0x0602], 1
        mov word ptr [0x0604], 0x7E00
        mov word ptr [0x0606], 0
        mov dword ptr [0x0608], 1
        mov dword ptr [0x060C], 0
        mov si, 0x0600
        mov ah, 0x42
        int 0x13
        jnc loaded
        mov ax, 0x0201
        xor bx, bx
        mov es, bx
        mov bx, 0x7E00
        mov cx, 2
        xor dh, dh
        int 0x13
        jc hang
    loaded:
        push 0
        push 0x7E00
        retf
    hang:
        cli
        hlt
        jmp hang
    """
    stage0_code = _assemble(stage0_source, KS_MODE_16, 0x7C00)
    stage2_code = assemble_payload(source_path, sectors, kernel_bytes, 2, 0x7E00)
    if len(stage2_code) > 510:
        raise RuntimeError(
            f"TWO_SECTOR 第二扇区超限 {len(stage2_code) - 510} 字节"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(_signed_sector(stage0_code))
    stage2_path.write_bytes(stage2_code + bytes(512 - len(stage2_code)))
    return len(stage0_code), len(stage2_code)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("boot/boot.asm"))
    parser.add_argument("--output", type=Path, default=Path("build/boot.bin"))
    parser.add_argument("--stage2-output", type=Path, default=Path("build/boot-stage2.bin"))
    parser.add_argument("--sectors", type=int, required=True)
    parser.add_argument("--kernel-bytes", type=int, required=True)
    parser.add_argument("--kernel-lba", type=int, default=1)
    parser.add_argument("--two-sector", action="store_true")
    args = parser.parse_args()
    try:
        if args.two_sector:
            used, second = assemble_two_sector(
                args.source, args.output, args.stage2_output,
                args.sectors, args.kernel_bytes,
            )
            print(
                f"[boot] TWO_SECTOR stage0_bytes={used} stage2_bytes={second} "
                "mbr_bytes=512 signature=55aa"
            )
        else:
            used, free = assemble_boot(
                args.source, args.output, args.sectors,
                args.kernel_bytes, args.kernel_lba,
            )
            print(
                f"[boot] code_bytes={used} free_bytes={free} "
                "total_bytes=512 signature=55aa"
            )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"[错误] {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
