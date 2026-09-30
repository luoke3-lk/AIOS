#!/usr/bin/env python3
"""AIOS v0.1 reproducible eight-step build pipeline."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
from typing import Sequence

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
FLOPPY_BYTES = 1_474_560
HDD_BYTES = 10 * 1024 * 1024
SOURCE_DIRS = ("core", "drivers", "mm", "nn", "nlu", "shell", "hw")
# ziglang ships a console launcher script; Windows gets the .exe form.
ZIG_EXE = "python-zig.exe" if os.name == "nt" else "python-zig"


class BuildError(RuntimeError):
    """A build step failed with a user-facing explanation."""


def run(command: Sequence[str], step: str) -> None:
    """Run a subprocess and retain its real output for reproducibility."""
    print(f"[{step}] {' '.join(command)}")
    completed = subprocess.run(command, cwd=ROOT, text=True)
    if completed.returncode != 0:
        raise BuildError(f"步骤 {step} 失败，退出码 {completed.returncode}")


def find_zig() -> Path:
    """Locate the ziglang Python launcher without relying on PATH.

    Resolution order keeps the build portable across machines and CI:
    1. ``AIOS_ZIG`` environment variable (absolute path to python-zig/zig);
    2. launcher installed next to the running interpreter, i.e. inside the
       active virtualenv created by ``pip install -r requirements.txt``;
    3. any ``python-zig`` or ``zig`` executable visible on ``PATH``.
    """
    configured = os.environ.get("AIOS_ZIG", "")
    candidates = [
        Path(configured) if configured else Path("__missing__"),
        Path(sys.executable).with_name(ZIG_EXE),
    ]
    path_hit = shutil.which(ZIG_EXE) or shutil.which("zig")
    if path_hit:
        candidates.append(Path(path_hit))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise BuildError(f"找不到 {ZIG_EXE}；请安装 requirements.txt 或设置 AIOS_ZIG")


def collect_sources() -> list[str]:
    """Glob all C modules so concurrently generated nn/nlu files join automatically."""
    sources: list[Path] = []
    model_ready = (ROOT / "nn" / "config.h").exists() and (ROOT / "nn" / "model_weights.h").exists()
    for directory in SOURCE_DIRS:
        if directory in ("nn", "nlu") and not model_ready:
            continue
        sources.extend((ROOT / directory).glob("*.c"))
    if not sources:
        raise BuildError("未找到任何 C 源文件")
    return [str(path.relative_to(ROOT)) for path in sorted(sources)]


def maybe_generate_model(retrain: bool, skip_train: bool) -> list[str]:
    """Run optional AI generation only when its teammate-owned scripts exist."""
    completed: list[str] = []
    generator = ROOT / "tools" / "gen_corpus.py"
    trainer = ROOT / "tools" / "train.py"
    weights = ROOT / "nn" / "model_weights.h"
    config = ROOT / "nn" / "config.h"
    if skip_train:
        print("[model] 已按 --skip-train 跳过模型生成")
        return completed
    if generator.exists() and (retrain or not (ROOT / "tools" / "intent_corpus.json").exists()):
        run([sys.executable, str(generator)], "1/8 corpus")
        completed.append("gen_corpus")
    if trainer.exists():
        if retrain or not weights.exists() or not config.exists():
            run([sys.executable, str(trainer)], "2/8 train")
            completed.append("train")
        else:
            run([sys.executable, str(trainer), "--eval"], "2/8 train-eval")
            completed.append("train-eval")
    else:
        print("[model] nn/nlu 尚未落地，内核使用可编译的确定性降级路径")
    return completed


def compile_kernel(zig: Path, sources: list[str], kbd_mode: int,
                   prompt_style: int, two_sector: bool, slim: bool) -> None:
    defines = [
        f"-DKBD_MODE={kbd_mode}",
        f"-DPROMPT_STYLE={prompt_style}",
        f"-DTWO_SECTOR={1 if two_sector else 0}",
        f"-DBUILD_SLIM={1 if slim else 0}",
    ]
    command = [
        str(zig), "cc", "-target", "x86-freestanding", "-O2", "-nostdlib",
        "-ffreestanding", "-fno-builtin", "-fno-stack-protector", "-fno-pic",
        "-fno-unwind-tables", "-fno-asynchronous-unwind-tables", "-mno-sse",
        "-mno-sse2", "-mno-mmx", "-mno-80387", "-I", str(ROOT),
        "-Wl,--script=kernel.ld", "-Wl,--no-gc-sections", "-o",
        str(BUILD / "kernel.elf"), *defines, *sources,
    ]
    run(command, "4/8 cc")
    run([
        str(zig), "objcopy", "-O", "binary", str(BUILD / "kernel.elf"),
        str(BUILD / "kernel.bin"),
    ], "5/8 objcopy")


def assemble_boot(kernel_bytes: int, forced_two_sector: bool) -> bool:
    """Build one-sector boot, automatically degrading to two sectors if needed."""
    sectors = (kernel_bytes + 511) // 512
    base = [
        sys.executable, str(ROOT / "tools" / "asm_boot.py"),
        "--source", str(ROOT / "boot" / "boot.asm"),
        "--output", str(BUILD / "boot.bin"),
        "--stage2-output", str(BUILD / "boot-stage2.bin"),
        "--sectors", str(sectors), "--kernel-bytes", str(kernel_bytes),
    ]
    if forced_two_sector:
        run([*base, "--two-sector"], "3/8 boot")
        return True
    attempt = subprocess.run(base, cwd=ROOT, text=True, capture_output=True)
    if attempt.returncode == 0:
        if attempt.stdout:
            print(attempt.stdout, end="")
        return False
    print("[boot] 单扇区代码超过分区表安全边界，自动启用 TWO_SECTOR")
    run([*base, "--two-sector"], "3/8 boot-fallback")
    return True


def patch_partition_table(mbr: bytes, total_sectors: int) -> bytes:
    """Install one active type-0x7F partition entry without touching code/signature."""
    if len(mbr) != 512:
        raise BuildError("MBR 必须恰好 512 字节")
    patched = bytearray(mbr)
    entry = struct.pack(
        "<B3sB3sII", 0x80, bytes((0, 2, 0)), 0x7F,
        bytes((0xFE, 0xFF, 0xFF)), 1, total_sectors,
    )
    patched[0x1BE:0x1CE] = entry
    patched[0x1CE:0x1FE] = bytes(48)
    patched[510:512] = b"\x55\xAA"
    return bytes(patched)


def make_images(two_sector: bool) -> tuple[int, int]:
    boot = (BUILD / "boot.bin").read_bytes()
    stage2 = (BUILD / "boot-stage2.bin").read_bytes() if two_sector else b""
    kernel = (BUILD / "kernel.bin").read_bytes()
    kernel_padded = kernel + bytes((-len(kernel)) % 512)
    payload = boot + stage2 + kernel_padded
    if len(payload) > FLOPPY_BYTES:
        raise BuildError("内核与引导层超过 1.44MB 镜像容量")
    (ROOT / "aios.img").write_bytes(payload + bytes(FLOPPY_BYTES - len(payload)))
    partition_sectors = (len(stage2) + len(kernel_padded)) // 512
    hdd_boot = patch_partition_table(boot, partition_sectors)
    hdd_payload = hdd_boot + stage2 + kernel_padded
    (ROOT / "aios-hdd.img").write_bytes(hdd_payload + bytes(HDD_BYTES - len(hdd_payload)))
    return len(payload), partition_sectors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slim", action="store_true", help="裁剪可选引导功能")
    parser.add_argument("--two-sector", action="store_true", help="强制双扇区引导层")
    parser.add_argument("--kbd-mode", type=int, choices=(0, 1), default=1)
    parser.add_argument("--prompt-style", type=int, choices=(0, 1), default=1)
    parser.add_argument("--dump", action="store_true", help="启动 Unicorn 并导出显存 HTML")
    parser.add_argument("--retrain", action="store_true", help="强制重新生成语料和模型")
    parser.add_argument("--skip-train", action="store_true", help="跳过可选模型训练")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    BUILD.mkdir(parents=True, exist_ok=True)
    try:
        model_steps = maybe_generate_model(args.retrain, args.skip_train)
        zig = find_zig()
        sources = collect_sources()
        compile_kernel(zig, sources, args.kbd_mode, args.prompt_style,
                       args.two_sector, args.slim)
        kernel_bytes = (BUILD / "kernel.bin").stat().st_size
        if kernel_bytes > 448 * 1024:
            raise BuildError(f"kernel.bin={kernel_bytes} 超过 448KB 上限")
        if kernel_bytes > 128 * 1024:
            print(f"[警告] kernel.bin={kernel_bytes} 超过 128KB 目标")
        two_sector = assemble_boot(kernel_bytes, args.two_sector)
        run([
            sys.executable, str(ROOT / "tools" / "scan_instr.py"),
            "--elf", str(BUILD / "kernel.elf"), "--kernel",
            str(BUILD / "kernel.bin"), "--output",
            str(BUILD / "report-instr.txt"), "--boot-bytes", "512",
        ], "6/8 scan")
        payload_bytes, partition_sectors = make_images(two_sector)
        print(
            f"[7/8 image] kernel={kernel_bytes} bytes mbr=512 bytes "
            f"two_sector={int(two_sector)} floppy={FLOPPY_BYTES} bytes "
            f"hdd={HDD_BYTES} bytes partition_type=0x7F active=0x80"
        )
        if args.dump:
            run([
                sys.executable, str(ROOT / "tools" / "unicorn_bridge.py"),
                "--image", str(ROOT / "aios.img"), "--dump",
                str(BUILD / "screen.html"),
            ], "8/8 dump")
        else:
            print("[8/8 dump] 未请求 --dump")
        manifest = {
            "toolchain": str(zig),
            "sources": sources,
            "model_steps": model_steps,
            "kernel_bytes": kernel_bytes,
            "boot_bytes": 512,
            "two_sector": two_sector,
            "kernel_lba": 2 if two_sector else 1,
            "floppy_bytes": FLOPPY_BYTES,
            "hdd_bytes": HDD_BYTES,
            "partition_sectors": partition_sectors,
            "payload_bytes": payload_bytes,
            "kbd_mode": args.kbd_mode,
            "prompt_style": args.prompt_style,
        }
        (BUILD / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print("[完成] AIOS 双镜像与静态扫描报告已生成")
        return 0
    except (BuildError, OSError, ValueError) as error:
        print(f"[错误] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
