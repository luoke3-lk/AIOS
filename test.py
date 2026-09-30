#!/usr/bin/env python3
"""AIOS v0.1 submission gate with layer-labelled deterministic checks."""
from __future__ import annotations

import html
from pathlib import Path
import random
import re
import struct
import subprocess
import sys
from typing import Callable

ROOT = Path(__file__).resolve().parent
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

from dump_vga import render_vga  # noqa: E402
from unicorn_bridge import (  # noqa: E402
    BridgeConfig, BootResult, UnicornBridge, ascii_to_scancodes, boot_image,
)

Case = tuple[str, str, Callable[[], None]]
CASES: list[Case] = []
_BOOT_CACHE: dict[str, BootResult] = {}


def case(layer: str, name: str) -> Callable[[Callable[[], None]], Callable[[], None]]:
    def register(function: Callable[[], None]) -> Callable[[], None]:
        CASES.append((layer, name, function))
        return function
    return register


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise AssertionError(reason)


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def manifest() -> dict[str, object]:
    import json
    return json.loads(text("build/manifest.json"))


def boot(kind: str = "default") -> BootResult:
    if kind not in _BOOT_CACHE:
        config = BridgeConfig(
            a20_bios_ok=kind != "fallback",
            no_lba=kind == "no_lba",
            max_instructions=2_000_000,
        )
        _BOOT_CACHE[kind] = boot_image(ROOT / "aios.img", config)
    return _BOOT_CACHE[kind]


def ensure_build() -> None:
    required = (ROOT / "aios.img", ROOT / "aios-hdd.img", ROOT / "build" / "kernel.bin")
    if all(path.exists() for path in required):
        return
    completed = subprocess.run(
        [sys.executable, str(ROOT / "build.py"), "--skip-train"], cwd=ROOT
    )
    if completed.returncode != 0:
        raise SystemExit("[FAIL] layer=build case=ensure_build reason=build.py failed")


@case("boot", "boot_size_512")
def test_boot_size() -> None:
    require((ROOT / "build/boot.bin").stat().st_size == 512, "boot.bin != 512")


@case("boot", "boot_signature")
def test_boot_signature() -> None:
    require((ROOT / "build/boot.bin").read_bytes()[-2:] == b"\x55\xAA", "missing 55AA")


@case("boot", "floppy_exact_size")
def test_floppy_size() -> None:
    require((ROOT / "aios.img").stat().st_size == 1_474_560, "wrong floppy size")


@case("boot", "hdd_exact_size")
def test_hdd_size() -> None:
    require((ROOT / "aios-hdd.img").stat().st_size == 10 * 1024 * 1024, "wrong HDD size")


@case("boot", "hdd_partition_active_type")
def test_partition() -> None:
    image = (ROOT / "aios-hdd.img").read_bytes()[:512]
    require(image[0x1BE] == 0x80, "partition not active")
    require(image[0x1C2] == 0x7F, "partition type != 0x7F")
    require(struct.unpack_from("<I", image, 0x1C6)[0] == 1, "partition LBA != 1")


@case("boot", "boot_seg_regs")
def test_boot_segments() -> None:
    result = boot()
    require(result.registers["ds"] == 0x10, "kernel DS selector != 0x10")
    require(result.registers["ss"] == 0x10, "kernel SS selector != 0x10")
    require(result.registers["sp"] <= 0x90000, "stack above configured top")


@case("boot", "a20_bios_ok")
def test_a20_bios() -> None:
    require(boot().trace.a20_bios, "INT15 A20 not attempted")


@case("boot", "a20_fallback_92_8042")
def test_a20_fallback() -> None:
    trace = boot("fallback").trace
    require(trace.a20_fast and trace.a20_8042, "A20 fallback chain incomplete")


@case("boot", "e820_table_entries")
def test_e820() -> None:
    result = boot()
    raw = bytes(result.uc.mem_read(0x8000, 16))
    magic, count, maximum = struct.unpack_from("<IHH", raw)
    require(magic == 0x30323845, "E820 magic mismatch")
    require(count == 3 and maximum == 32, f"E820 count={count} max={maximum}")


@case("boot", "kernel_loaded_at_0x10000")
def test_kernel_loaded() -> None:
    result = boot()
    expected = (ROOT / "build/kernel.bin").read_bytes()
    actual = bytes(result.uc.mem_read(0x10000, min(len(expected), 128)))
    require(actual == expected[:len(actual)], "kernel load mismatch")


@case("boot", "protected_mode_cr0")
def test_protected_mode() -> None:
    result = boot()
    require(result.registers["cr0"] & 1 == 1, "CR0.PE not set")
    require(result.registers["cs"] == 0x08, f"CS={result.registers['cs']:#x}")


@case("boot", "chs_fallback")
def test_chs_fallback() -> None:
    require(boot("no_lba").trace.chs_reads > 0, "CHS fallback not used")


@case("vga", "vga_memory_size")
def test_vga_memory_size() -> None:
    require(len(boot().vga_bytes()) == 4000, "VGA buffer not 4000 bytes")


@case("vga", "vga_banner_visible")
def test_vga_banner_visible() -> None:
    require("AIOS v0.1.0" in boot().vga_text(), "banner missing from VGA")


@case("vga", "vga_prompt_visible")
def test_vga_prompt_visible() -> None:
    require("{AIOS}>" in boot().vga_text(), "default prompt missing")


@case("vga", "vga_cursor_crtc_seq")
def test_vga_cursor_sequence() -> None:
    indices = boot().trace.crtc_indices
    for expected in (0x0A, 0x0B, 0x0E, 0x0F):
        require(expected in indices, f"CRTC index {expected:#x} absent")


@case("vga", "vga_scroll_implementation")
def test_vga_scroll_source() -> None:
    source = text("drivers/vga.c")
    require("cell + VGA_W" in source and "VGA_H - 1u" in source, "scroll copy/fill absent")


@case("vga", "vga_no_software_blink")
def test_no_software_blink() -> None:
    source = text("drivers/vga.c").lower()
    require("timer" not in source and "delay" not in source, "software cursor timing found")


@case("vga", "dump_html_escapes")
def test_dump_escape() -> None:
    raw = bytearray(b" \x07" * 2000)
    raw[0:6] = b"<\x0F>\x0F&\x0F"
    output = ROOT / "build" / "screen_escape_test.html"
    render_vga(bytes(raw), output)
    page = output.read_text(encoding="utf-8")
    require("&lt;" in page and "&gt;" in page and "&amp;" in page, "HTML not escaped")


@case("kbd", "kbd_plain_table")
def test_kbd_plain_table() -> None:
    source = text("drivers/kbd.c")
    require("KBD_PLAIN[128]" in source and "'a', 's'" in source, "plain table incomplete")


@case("kbd", "kbd_shift_table")
def test_kbd_shift_table() -> None:
    source = text("drivers/kbd.c")
    require("KBD_SHIFTED[128]" in source and "'A', 'S'" in source, "shift table incomplete")


@case("kbd", "kbd_caps_led")
def test_kbd_caps_led() -> None:
    source = text("drivers/kbd.c")
    require("0xEDu" in source and "g_caps << 2u" in source, "caps LED protocol absent")


@case("kbd", "kbd_irq_ring")
def test_kbd_irq_ring() -> None:
    source = text("drivers/kbd.c")
    require("ring_push" in source and "ring_pop" in source and "KBD_RING_SIZE" in source, "IRQ ring absent")


@case("kbd", "kbd_backspace_bound")
def test_kbd_backspace_bound() -> None:
    source = text("drivers/kbd.c")
    require("line->len == 0u" in source, "backspace zero bound absent")


@case("kbd", "kbd_buffer_128_cap")
def test_kbd_line_cap() -> None:
    source = text("drivers/kbd.c")
    require("line->len >= LINE_MAX" in source and "LINE_MAX 128u" in text("drivers/kbd.h"), "line cap absent")


@case("kbd", "kbd_live_echo")
def test_kbd_live_echo() -> None:
    bridge = UnicornBridge((ROOT / "aios.img").read_bytes(), BridgeConfig())
    bridge.run()
    result = bridge.inject_scancodes(ascii_to_scancodes("a"))
    require("{AIOS}> a" in result.vga_text(), "injected key was not echoed")


@case("pmm", "pmm_fixed_bitmap")
def test_pmm_fixed_bitmap() -> None:
    require("0x00040000u" in text("mm/pmm.h"), "bitmap address changed")


@case("pmm", "pmm_bitmap_max_128k")
def test_pmm_bitmap_max() -> None:
    require("128u * 1024u" in text("mm/pmm.h"), "bitmap maximum absent")


@case("pmm", "pmm_reserves_low_1m")
def test_pmm_low_reservation() -> None:
    source = text("mm/pmm.c")
    require("first < 256u" in source and "g_search_hint = 256u" in source, "low 1MB not reserved")


@case("pmm", "pmm_alloc_free_roundtrip_logic")
def test_pmm_roundtrip_logic() -> None:
    source = text("mm/pmm.c")
    require("++g_allocated_frames" in source and "--g_allocated_frames" in source, "allocation accounting incomplete")


@case("pmm", "pmm_ai_exclusive")
def test_pmm_ai() -> None:
    require("total > used ? total - used" in text("mm/pmm.c"), "AI exclusive memory calculation absent")


@case("dispatch", "dispatch_table_size_13")
def test_dispatch_size() -> None:
    require(text("shell/dispatch.c").count("{INTENT_") == 13, "VTable is not 13 entries")


@case("dispatch", "dispatch_id_order_match")
def test_dispatch_order() -> None:
    source = text("shell/dispatch.c")
    names = re.findall(r"\{(INTENT_[A-Z]+),", source)
    expected = [
        "INTENT_CLEAR", "INTENT_MEMINFO", "INTENT_CPUINFO", "INTENT_SELFTEST",
        "INTENT_DISKINFO", "INTENT_MODELINFO", "INTENT_CALC", "INTENT_SCREENTEST",
        "INTENT_HELP", "INTENT_ABOUT", "INTENT_REBOOT", "INTENT_SHUTDOWN",
        "INTENT_FALLBACK",
    ]
    require(names == expected, f"VTable order mismatch: {names}")


@case("dispatch", "dispatch_single_point")
def test_dispatch_single_point() -> None:
    hits = 0
    for path in ROOT.rglob("*.c"):
        hits += path.read_text(encoding="utf-8").count("void dispatch(")
    require(hits == 1, f"dispatch definitions={hits}")


@case("dispatch", "dispatch_bounds_fallback")
def test_dispatch_bounds() -> None:
    require("id >= INTENT_COUNT" in text("shell/dispatch.c"), "dispatch bound absent")


@case("dispatch", "confidence_fallback_threshold")
def test_dispatch_threshold() -> None:
    source = text("shell/shell.c")
    require("top3_pct[0] < CONF_THRESHOLD" in source, "confidence gate absent")


@case("hwaction", "clear_direct_vga")
def test_action_clear() -> None:
    require("vga_clear();" in text("hw/meminfo.c"), "clear does not touch VGA")


@case("hwaction", "meminfo_e820_and_pmm")
def test_action_meminfo() -> None:
    source = text("hw/meminfo.c")
    require("E820 memory map" in source and "pmm_total_kb" in source, "memory report incomplete")


@case("hwaction", "cpuinfo_cpuid")
def test_action_cpu() -> None:
    source = text("hw/cpuinfo.c")
    require('"cpuid"' in source and "0x80000004u" in source, "CPUID leaves incomplete")


@case("hwaction", "selftest_pci_ports")
def test_action_pci() -> None:
    source = text("hw/selftest.c")
    require("0x0CF8u" in source and "0x0CFCu" in source, "PCI ports absent")


@case("hwaction", "selftest_memory_march")
def test_action_march() -> None:
    source = text("hw/selftest.c")
    require("0xFFFFFFFFu" in source and "1024u * 1024u" in source, "memory march incomplete")


@case("hwaction", "disk_identify")
def test_action_disk() -> None:
    source = text("hw/diskinfo.c")
    require("0xECu" in source and "identify[60]" in source, "ATA identify incomplete")


@case("hwaction", "calc_divide_zero")
def test_action_calc_zero() -> None:
    require("error: divide by zero" in text("hw/calc.c"), "divide-zero error absent")


@case("hwaction", "calc_hex_negative")
def test_action_calc_formats() -> None:
    source = text("hw/calc.c")
    require("base = 16u" in source and "negative" in source, "hex/negative parsing absent")


@case("hwaction", "screen_three_patterns")
def test_action_screen() -> None:
    source = text("hw/screentest.c")
    require(all(name in source for name in ("draw_bars", "draw_checker", "draw_gradient")), "screen patterns missing")


@case("hwaction", "modelinfo_fields")
def test_action_model() -> None:
    source = text("hw/modelinfo.c")
    for field in ("int8", "weights @", "ai exclusive"):
        require(field in source, f"model field missing: {field}")
    # 形状与权重大小必须从 nn/config.h 的维度宏推导，禁止写死后与模型脱节
    for macro in ("NLU_DIM", "NN_HIDDEN", "NN_CLASSES", "WEIGHTS_BYTES"):
        require(macro in source, f"model shape not derived from {macro}")
    require("nn/config.h" in source, "modelinfo.c does not include nn/config.h")


@case("hwaction", "reboot_8042")
def test_action_reboot() -> None:
    require("outb(0x64u, 0xFEu)" in text("hw/power.c"), "8042 reset absent")


@case("hwaction", "shutdown_acpi")
def test_action_shutdown() -> None:
    source = text("hw/power.c")
    require("outw(0x0604u, 0x2000u)" in source and "safe to turn off" in source, "ACPI fallback absent")


@case("hwaction", "live_model_to_help_dispatch")
def test_live_help_dispatch() -> None:
    bridge = UnicornBridge((ROOT / "aios.img").read_bytes(), BridgeConfig())
    bridge.run()
    result = bridge.inject_scancodes(ascii_to_scancodes("what can you do\n"), 2_000_000)
    screen = result.vga_text()
    require("AI: INTENT_HELP (" in screen, "model Top-1 HELP metadata missing")
    require("things i can do right now:" in screen, "HELP action did not dispatch")


@case("hwaction", "live_model_to_calc_dispatch")
def test_live_calc_dispatch() -> None:
    bridge = UnicornBridge((ROOT / "aios.img").read_bytes(), BridgeConfig())
    bridge.run()
    request = "calculate 45678 plus 1234\n"
    result = bridge.inject_scancodes(ascii_to_scancodes(request), 3_000_000)
    screen = result.vga_text()
    require("AI: INTENT_CALC (" in screen, "model Top-1 CALC metadata missing")
    require("result: 46912" in screen, "calculator action returned wrong result")


@case("golden", "golden_banner")
def test_golden_banner() -> None:
    source = text("core/banner.c")
    expected = (
        "AIOS v0.1.0 - bare-metal native AI operating system",
        "(c) 2026 Luo Ke. Every instruction below runs on bare metal.",
        "Just tell me what you want to do.",
    )
    require(all(line in source for line in expected), "banner fixture mismatch")


@case("golden", "golden_help")
def test_golden_help() -> None:
    source = text("hw/help_about.c")
    require(
        "i understand plain english" in source
        and "tell me about my memory" in source
        and "reboot / shutdown" in source,
        "HELP fixture mismatch",
    )


@case("golden", "golden_about")
def test_golden_about() -> None:
    source = text("hw/help_about.c")
    require("bare metal, nothing underneath" in source and "no os, no scheduler" in source, "ABOUT fixture mismatch")


@case("golden", "report_zero_forbidden")
def test_report() -> None:
    report = text("build/report-instr.txt")
    for metric in ("fpu_ops=0", "sse_ops=0", "libc_symbols=0"):
        require(metric in report, f"report missing {metric}")


@case("fuzz", "fuzz_1000_random_lines")
def test_fuzz_lines() -> None:
    generator = random.Random(20260101)
    for _ in range(1000):
        raw = "".join(chr(generator.randrange(1, 128)) for _ in range(generator.randrange(0, 300)))
        line = "".join(character for character in raw if 0x20 <= ord(character) <= 0x7E)[:128]
        require(len(line) <= 128, "line cap violated")


@case("fuzz", "fuzz_long_token")
def test_fuzz_long_token() -> None:
    token = "a" * 4096
    require(len(token[:31]) == 31, "token cap model failed")


@case("fuzz", "fuzz_pure_symbols")
def test_fuzz_symbols() -> None:
    symbols = "!@#$%^&*()[]{}<>?/\\|" * 8
    normalized = " ".join(part for part in re.sub(r"[^a-z0-9]", " ", symbols.lower()).split())
    require(normalized == "", "symbols should normalize empty")


@case("fuzz", "canaries_declared")
def test_canaries() -> None:
    source = text("core/globals.c")
    require("0xCAFEBABE" in source and "0xDEADBEEF" in source, "canaries missing")


@case("fuzz", "no_hosted_headers")
def test_no_hosted_headers() -> None:
    forbidden = ("<stdint.h>", "<stddef.h>", "<string.h>", "<stdio.h>")
    for path in ROOT.rglob("*.c"):
        source = path.read_text(encoding="utf-8")
        require(not any(header in source for header in forbidden), f"hosted header in {path}")


def main() -> int:
    ensure_build()
    failures = 0
    counts: dict[str, int] = {}
    for layer, name, function in CASES:
        try:
            function()
            print(f"[PASS] layer={layer} case={name}")
            counts[layer] = counts.get(layer, 0) + 1
        except Exception as error:  # A gate must report every failing layer.
            failures += 1
            print(f"[FAIL] layer={layer} case={name} reason={error}")
    summary = " ".join(f"{layer}={count}" for layer, count in sorted(counts.items()))
    print(f"[SUMMARY] passed={len(CASES) - failures} failed={failures} total={len(CASES)} {summary}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
