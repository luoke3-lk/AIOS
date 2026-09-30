"""Unicorn BIOS/port bridge for boot, hardware, and VGA regression tests."""
from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
import struct
from typing import Deque

from unicorn import (
    Uc, UcError, UC_ARCH_X86, UC_HOOK_CODE, UC_HOOK_INTR, UC_HOOK_INSN,
    UC_MODE_16, UC_MODE_32,
)
from unicorn.x86_const import (
    UC_X86_INS_CPUID, UC_X86_INS_IN, UC_X86_INS_OUT, UC_X86_REG_AH, UC_X86_REG_AL,
    UC_X86_REG_AX, UC_X86_REG_BH, UC_X86_REG_BL, UC_X86_REG_BX,
    UC_X86_REG_CH, UC_X86_REG_CL, UC_X86_REG_CR0, UC_X86_REG_CS,
    UC_X86_REG_DH, UC_X86_REG_DL, UC_X86_REG_DS, UC_X86_REG_EAX,
    UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX,
    UC_X86_REG_EBP, UC_X86_REG_ESI, UC_X86_REG_EFLAGS, UC_X86_REG_EIP,
    UC_X86_REG_ES, UC_X86_REG_ESP,
    UC_X86_REG_IP, UC_X86_REG_SI, UC_X86_REG_SP, UC_X86_REG_SS,
)

from dump_vga import render_vga

MEMORY_BYTES = 16 * 1024 * 1024
VGA_ADDRESS = 0xB8000
E820_DEFAULT = (
    struct.pack("<QQII", 0x00000000, 0x0009FC00, 1, 1),
    struct.pack("<QQII", 0x0009FC00, 0x00060400, 2, 1),
    struct.pack("<QQII", 0x00100000, 0x03F00000, 1, 1),
)


@dataclass
class BridgeConfig:
    """Inputs exposed by the synthetic BIOS."""

    e820_entries: tuple[bytes, ...] = E820_DEFAULT
    a20_bios_ok: bool = True
    no_lba: bool = False
    drive: int = 0x80
    scancodes: list[int] = field(default_factory=list)
    pci_devices: dict[tuple[int, int, int], tuple[int, int, int]] = field(default_factory=dict)
    ata_identify: bytes | None = None
    max_instructions: int = 2_000_000


@dataclass
class BridgeTrace:
    """Observable side effects for layer-specific assertions."""

    instruction_count: int = 0
    a20_bios: bool = False
    a20_fast: bool = False
    a20_8042: bool = False
    lba_reads: int = 0
    chs_reads: int = 0
    reboot: bool = False
    acpi_shutdown: bool = False
    crtc_indices: list[int] = field(default_factory=list)
    crtc_values: list[int] = field(default_factory=list)
    interrupts: list[int] = field(default_factory=list)
    exception: str = ""


@dataclass
class BootResult:
    """Final emulator, trace, and key register snapshot."""

    uc: Uc
    trace: BridgeTrace
    registers: dict[str, int]

    def vga_bytes(self) -> bytes:
        return bytes(self.uc.mem_read(VGA_ADDRESS, 4000))

    def vga_text(self) -> str:
        raw = self.vga_bytes()
        return "\n".join(
            "".join(chr(raw[(row * 80 + column) * 2]) for column in range(80)).rstrip()
            for row in range(25)
        ).rstrip()


class UnicornBridge:
    """Emulate legacy BIOS services and hardware I/O required by AIOS."""

    def __init__(self, image: bytes, config: BridgeConfig | None = None) -> None:
        self.image = image
        self.config = config or BridgeConfig()
        self.trace = BridgeTrace()
        self.keys: Deque[int] = deque(self.config.scancodes)
        self.crtc_index = 0
        self.last_pci_address = 0
        self.ata_words: Deque[int] = deque()
        self.ata_active = False
        self.mode32 = False
        self.uc = Uc(UC_ARCH_X86, UC_MODE_16)
        self.uc.mem_map(0, MEMORY_BYTES)
        self.uc.mem_write(0x7C00, image[:512])
        self._install_hooks()

    @staticmethod
    def _set_cf(uc: Uc, enabled: bool) -> None:
        flags = uc.reg_read(UC_X86_REG_EFLAGS)
        uc.reg_write(UC_X86_REG_EFLAGS, flags | 1 if enabled else flags & ~1)

    def _install_hooks(self) -> None:
        self.uc.hook_add(UC_HOOK_INTR, self._interrupt)
        self.uc.hook_add(UC_HOOK_CODE, self._code)
        self.uc.hook_add(UC_HOOK_INSN, self._cpuid, None, 1, 0, UC_X86_INS_CPUID)
        self.uc.hook_add(UC_HOOK_INSN, self._port_in, None, 1, 0, UC_X86_INS_IN)
        self.uc.hook_add(UC_HOOK_INSN, self._port_out, None, 1, 0, UC_X86_INS_OUT)

    def _code(self, uc: Uc, address: int, size: int, user_data: object) -> None:
        del size, user_data
        self.trace.instruction_count += 1
        # Stop immediately before an idle HLT so a later test can resume. If
        # input has arrived, skip that one-byte HLT and continue into the loop.
        if bytes(uc.mem_read(address, 1)) == b"\xF4":
            if self.keys:
                uc.reg_write(UC_X86_REG_EIP, address + 1)
            else:
                uc.emu_stop()

    def _interrupt(self, uc: Uc, number: int, user_data: object) -> None:
        del user_data
        self.trace.interrupts.append(number)
        if number == 0x15:
            self._int15(uc)
        elif number == 0x13:
            self._int13(uc)
        elif number == 0x10:
            self._set_cf(uc, False)
        elif number == 3:
            self.trace.reboot = True
            uc.emu_stop()
        else:
            self._set_cf(uc, True)

    def _int15(self, uc: Uc) -> None:
        eax = uc.reg_read(UC_X86_REG_EAX) & 0xFFFFFFFF
        if eax == 0xE820:
            index = uc.reg_read(UC_X86_REG_EBX) & 0xFFFFFFFF
            if index >= len(self.config.e820_entries):
                self._set_cf(uc, True)
                return
            es = uc.reg_read(UC_X86_REG_ES) & 0xFFFF
            di = uc.reg_read(UC_X86_REG_EDI) & 0xFFFF
            uc.mem_write((es << 4) + di, self.config.e820_entries[index])
            uc.reg_write(UC_X86_REG_EAX, 0x534D4150)
            uc.reg_write(UC_X86_REG_ECX, 24)
            uc.reg_write(UC_X86_REG_EBX, index + 1 if index + 1 < len(self.config.e820_entries) else 0)
            self._set_cf(uc, False)
        elif (eax & 0xFFFF) == 0x2401:
            self.trace.a20_bios = True
            self._set_cf(uc, not self.config.a20_bios_ok)
        else:
            self._set_cf(uc, True)

    def _copy_disk(self, lba: int, count: int, destination: int) -> bool:
        start = lba * 512
        end = start + count * 512
        if start < 0 or end > len(self.image) or destination + count * 512 > MEMORY_BYTES:
            return False
        self.uc.mem_write(destination, self.image[start:end])
        return True

    def _int13(self, uc: Uc) -> None:
        ah = uc.reg_read(UC_X86_REG_AH) & 0xFF
        if ah == 0x41:
            if self.config.no_lba:
                self._set_cf(uc, True)
            else:
                uc.reg_write(UC_X86_REG_BX, 0xAA55)
                uc.reg_write(UC_X86_REG_AH, 1)
                self._set_cf(uc, False)
        elif ah == 0x42:
            ds = uc.reg_read(UC_X86_REG_DS) & 0xFFFF
            si = uc.reg_read(UC_X86_REG_SI) & 0xFFFF
            dap = bytes(uc.mem_read((ds << 4) + si, 16))
            _, _, count, offset, segment, lba = struct.unpack("<BBHHHQ", dap)
            ok = self._copy_disk(lba, count, (segment << 4) + offset)
            self.trace.lba_reads += 1
            uc.reg_write(UC_X86_REG_AH, 0 if ok else 1)
            self._set_cf(uc, not ok)
        elif ah == 0x02:
            count = uc.reg_read(UC_X86_REG_AL) & 0xFF
            sector = uc.reg_read(UC_X86_REG_CL) & 0x3F
            cylinder = (uc.reg_read(UC_X86_REG_CH) & 0xFF) | ((uc.reg_read(UC_X86_REG_CL) & 0xC0) << 2)
            head = uc.reg_read(UC_X86_REG_DH) & 0xFF
            es = uc.reg_read(UC_X86_REG_ES) & 0xFFFF
            bx = uc.reg_read(UC_X86_REG_BX) & 0xFFFF
            lba = (cylinder * 2 + head) * 18 + sector - 1
            ok = sector > 0 and self._copy_disk(lba, count, (es << 4) + bx)
            self.trace.chs_reads += 1
            uc.reg_write(UC_X86_REG_AH, 0 if ok else 1)
            self._set_cf(uc, not ok)
        else:
            self._set_cf(uc, True)

    def _cpuid(self, uc: Uc, user_data: object) -> None:
        del user_data
        leaf = uc.reg_read(UC_X86_REG_EAX) & 0xFFFFFFFF
        eax = ebx = ecx = edx = 0
        if leaf == 0:
            eax = 1
            ebx, edx, ecx = struct.unpack("<III", b"AuthenticAMD")
        elif leaf == 1:
            eax = 0x00000F42
            edx = (1 << 0) | (1 << 5) | (1 << 9)
        elif leaf == 0x80000000:
            eax = 0x80000004
        elif 0x80000002 <= leaf <= 0x80000004:
            brand = b"AMD-K8 AIOS Virtual Processor".ljust(48, b" ")
            offset = (leaf - 0x80000002) * 16
            eax, ebx, ecx, edx = struct.unpack("<IIII", brand[offset:offset + 16])
        uc.reg_write(UC_X86_REG_EAX, eax)
        uc.reg_write(UC_X86_REG_EBX, ebx)
        uc.reg_write(UC_X86_REG_ECX, ecx)
        uc.reg_write(UC_X86_REG_EDX, edx)

    def _port_in(self, uc: Uc, port: int, size: int, user_data: object) -> int:
        del uc, user_data
        if port == 0x64:
            return 0x01 if self.keys else 0x00
        if port == 0x60:
            return self.keys.popleft() if self.keys else 0
        if port in (0x1F7, 0x177):
            return 0x58 if self.ata_active else 0
        if port in (0x1F0, 0x170) and size == 2:
            return self.ata_words.popleft() if self.ata_words else 0
        if port == 0xCFC:
            address = self.last_pci_address
            bus = (address >> 16) & 0xFF
            device = (address >> 11) & 0x1F
            function = (address >> 8) & 0x07
            offset = address & 0xFC
            record = self.config.pci_devices.get((bus, device, function))
            if record is None:
                return 0xFFFFFFFF
            vendor, product, class_code = record
            if offset == 0:
                return (product << 16) | vendor
            if offset == 8:
                return class_code << 8
            return 0
        if port in (0xCFD, 0xCFE, 0xCFF):
            return (1 << (size * 8)) - 1
        if port == 0x71:
            return 0x12
        return 0

    def _port_out(self, uc: Uc, port: int, size: int, value: int,
                  user_data: object) -> None:
        del uc, size, user_data
        if port == 0x92:
            self.trace.a20_fast = True
        elif port == 0x64:
            if value == 0xD1:
                self.trace.a20_8042 = True
            elif value == 0xFE:
                self.trace.reboot = True
        elif port == 0xCF8:
            self.last_pci_address = value & 0xFFFFFFFF
        elif port in (0x1F7, 0x177) and (value & 0xFF) == 0xEC:
            identify = self.config.ata_identify
            if identify is not None and len(identify) == 512:
                self.ata_words = deque(struct.unpack("<256H", identify))
                self.ata_active = True
        elif port == 0x3D4:
            self.crtc_index = value & 0xFF
            self.trace.crtc_indices.append(self.crtc_index)
        elif port == 0x3D5:
            self.trace.crtc_values.append(value & 0xFF)
        elif port in (0x604, 0xB004) and (value & 0xFFFF) == 0x2000:
            self.trace.acpi_shutdown = True

    def run(self) -> BootResult:
        """Run from BIOS entry until HLT, error, or instruction budget."""
        uc = self.uc
        uc.reg_write(UC_X86_REG_CS, 0)
        uc.reg_write(UC_X86_REG_IP, 0x7C00)
        uc.reg_write(UC_X86_REG_DS, 0)
        uc.reg_write(UC_X86_REG_ES, 0)
        uc.reg_write(UC_X86_REG_SS, 0)
        uc.reg_write(UC_X86_REG_SP, 0x7C00)
        uc.reg_write(UC_X86_REG_DL, self.config.drive)
        self._emulate_from(0x7C00, self.config.max_instructions)
        return self.result()

    def _emulate_from(self, address: int, instruction_limit: int) -> None:
        try:
            self.uc.emu_start(address, 0, count=instruction_limit)
        except UcError as error:
            self.trace.exception = str(error)

    def _promote_to_32(self) -> None:
        """Move a halted protected-mode snapshot into a native UC_MODE_32 VM."""
        if self.mode32:
            return
        old = self.uc
        snapshot = bytes(old.mem_read(0, MEMORY_BYTES))
        register_ids = (
            UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX,
            UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP, UC_X86_REG_ESP,
            UC_X86_REG_EIP, UC_X86_REG_EFLAGS,
        )
        values = {register: old.reg_read(register) for register in register_ids}
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        self.uc.mem_map(0, MEMORY_BYTES)
        self.uc.mem_write(0, snapshot)
        for register, value in values.items():
            self.uc.reg_write(register, value)
        self.mode32 = True
        self._install_hooks()

    def inject_scancodes(self, scan_codes: list[int],
                         instruction_limit: int = 1_000_000) -> BootResult:
        """Resume a halted kernel after making PS/2 scan codes available."""
        self.keys.extend(scan_codes)
        self.trace.exception = ""
        self._promote_to_32()
        self._emulate_from(self.uc.reg_read(UC_X86_REG_EIP), instruction_limit)
        return self.result()

    def result(self) -> BootResult:
        """Capture the current state without restarting the machine."""
        uc = self.uc
        registers = {
            "cs": uc.reg_read(UC_X86_REG_CS),
            "ds": uc.reg_read(UC_X86_REG_DS),
            "es": uc.reg_read(UC_X86_REG_ES),
            "ss": uc.reg_read(UC_X86_REG_SS),
            "sp": uc.reg_read(UC_X86_REG_ESP),
            "eip": uc.reg_read(UC_X86_REG_EIP),
            "cr0": uc.reg_read(UC_X86_REG_CR0),
        }
        return BootResult(uc, self.trace, registers)


SET1_ASCII = {
    "1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05, "5": 0x06,
    "6": 0x07, "7": 0x08, "8": 0x09, "9": 0x0A, "0": 0x0B,
    "q": 0x10, "w": 0x11, "e": 0x12, "r": 0x13, "t": 0x14,
    "y": 0x15, "u": 0x16, "i": 0x17, "o": 0x18, "p": 0x19,
    "a": 0x1E, "s": 0x1F, "d": 0x20, "f": 0x21, "g": 0x22,
    "h": 0x23, "j": 0x24, "k": 0x25, "l": 0x26,
    "z": 0x2C, "x": 0x2D, "c": 0x2E, "v": 0x2F, "b": 0x30,
    "n": 0x31, "m": 0x32, " ": 0x39, "\n": 0x1C,
    "-": 0x0C, "=": 0x0D, "/": 0x35,
}


def ascii_to_scancodes(text: str) -> list[int]:
    """Translate the lowercase ASCII subset used by tests into Set-1 makes."""
    codes: list[int] = []
    for character in text:
        key = character.lower()
        if key not in SET1_ASCII:
            raise ValueError(f"unsupported test character: {character!r}")
        codes.append(SET1_ASCII[key])
    return codes


def boot_image(path: Path, config: BridgeConfig | None = None) -> BootResult:
    """Convenience entry used by tests and screen dumping."""
    return UnicornBridge(path.read_bytes(), config).run()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--dump", type=Path)
    parser.add_argument("--max-instructions", type=int, default=2_000_000)
    args = parser.parse_args()
    result = boot_image(args.image, BridgeConfig(max_instructions=args.max_instructions))
    if args.dump is not None:
        render_vga(result.vga_bytes(), args.dump)
    print(
        f"[unicorn] instructions={result.trace.instruction_count} "
        f"cs=0x{result.registers['cs']:04X} eip=0x{result.registers['eip']:08X} "
        f"cr0=0x{result.registers['cr0']:08X} error={result.trace.exception or 'none'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
