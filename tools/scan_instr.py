"""Reject floating-point, SIMD/MMX instructions, and libc dependencies."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from capstone import CS_ARCH_X86, CS_MODE_32, Cs

from elfinfo import executable_sections, undefined_symbols

FPU_PREFIXES = (
    "f2xm1", "fabs", "fadd", "fchs", "fcom", "fdiv", "fiadd", "ficom",
    "fidiv", "fild", "fimul", "fist", "fisub", "fld", "fmul", "fnstcw",
    "fpatan", "fprem", "fptan", "fsqrt", "fst", "fsub", "fxch",
)
SIMD_PREFIXES = (
    "addps", "addss", "cvt", "divps", "divss", "maxps", "minps", "movaps",
    "movdqu", "movss", "movups", "mulps", "mulss", "padd", "pmadd",
    "psadbw", "punpck", "vadd", "vcvt", "vmov", "vmul",
)
MMX_NAMES = {"emms", "movd", "movq", "pxor", "pmullw"}
LIBC_BLACKLIST = {
    "memcpy", "memset", "memmove", "memcmp", "strlen", "strcmp", "strncmp",
    "strcpy", "strncpy", "printf", "sprintf", "malloc", "calloc", "realloc",
    "free", "__udivdi3", "__divdi3", "__umoddi3", "__moddi3", "__ashldi3",
    "__ashrdi3", "__lshrdi3",
}


def analyze(elf_path: Path, kernel_path: Path) -> dict[str, object]:
    """Analyze executable sections and return stable report fields."""
    decoder = Cs(CS_ARCH_X86, CS_MODE_32)
    fpu_hits: list[str] = []
    simd_hits: list[str] = []
    mmx_hits: list[str] = []
    total = 0
    for address, code in executable_sections(elf_path):
        for instruction in decoder.disasm(code, address):
            total += 1
            mnemonic = instruction.mnemonic.lower()
            record = f"0x{instruction.address:08X}: {mnemonic} {instruction.op_str}".rstrip()
            if mnemonic.startswith(FPU_PREFIXES):
                fpu_hits.append(record)
            elif mnemonic in MMX_NAMES:
                mmx_hits.append(record)
            elif mnemonic.startswith(SIMD_PREFIXES):
                simd_hits.append(record)
    undefined = undefined_symbols(elf_path)
    libc = sorted(set(undefined).intersection(LIBC_BLACKLIST))
    return {
        "fpu_ops": len(fpu_hits),
        "sse_ops": len(simd_hits),
        "mmx_ops": len(mmx_hits),
        "libc_symbols": len(libc),
        "undefined_symbols": undefined,
        "total_insns": total,
        "kernel_bin_bytes": kernel_path.stat().st_size,
        "fpu_hits": fpu_hits,
        "sse_hits": simd_hits,
        "mmx_hits": mmx_hits,
        "libc_hits": libc,
    }


def write_report(result: dict[str, object], output: Path, boot_bytes: int) -> None:
    """Write the machine-readable first lines followed by optional evidence."""
    undefined = ",".join(result["undefined_symbols"])
    lines = [
        f"fpu_ops={result['fpu_ops']}",
        f"sse_ops={result['sse_ops']}",
        f"mmx_ops={result['mmx_ops']}",
        f"libc_symbols={result['libc_symbols']}",
        f"undefined_symbols={undefined}",
        f"total_insns={result['total_insns']}",
        f"kernel_bin_bytes={result['kernel_bin_bytes']}",
        f"boot_bin_bytes={boot_bytes}",
    ]
    for category in ("fpu_hits", "sse_hits", "mmx_hits", "libc_hits"):
        for hit in result[category]:
            lines.append(f"{category}: {hit}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elf", type=Path, required=True)
    parser.add_argument("--kernel", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--boot-bytes", type=int, default=512)
    args = parser.parse_args()
    try:
        result = analyze(args.elf, args.kernel)
        write_report(result, args.output, args.boot_bytes)
    except (OSError, ValueError) as error:
        print(f"[错误] 指令扫描失败: {error}", file=sys.stderr)
        return 1
    blocked = sum(int(result[name]) for name in (
        "fpu_ops", "sse_ops", "mmx_ops", "libc_symbols"
    ))
    print(
        f"[scan] fpu_ops={result['fpu_ops']} sse_ops={result['sse_ops']} "
        f"mmx_ops={result['mmx_ops']} libc_symbols={result['libc_symbols']}"
    )
    return 1 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
