"""Minimal dependency-free ELF32 section and symbol table reader."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import struct
from typing import Iterable


@dataclass(frozen=True)
class ElfSection:
    """One ELF32 section header plus its decoded name."""

    name: str
    section_type: int
    flags: int
    address: int
    offset: int
    size: int
    link: int
    entry_size: int


def read_sections(path: Path) -> tuple[bytes, list[ElfSection]]:
    """Return raw bytes and decoded ELF32 little-endian section headers."""
    data = path.read_bytes()
    if len(data) < 52 or data[:4] != b"\x7fELF":
        raise ValueError(f"{path} 不是 ELF 文件")
    if data[4] != 1 or data[5] != 1:
        raise ValueError("只支持 little-endian ELF32")
    section_offset = struct.unpack_from("<I", data, 32)[0]
    entry_size = struct.unpack_from("<H", data, 46)[0]
    section_count = struct.unpack_from("<H", data, 48)[0]
    names_index = struct.unpack_from("<H", data, 50)[0]
    if entry_size < 40 or names_index >= section_count:
        raise ValueError("ELF section header 损坏")
    raw_headers = []
    for index in range(section_count):
        position = section_offset + index * entry_size
        if position + 40 > len(data):
            raise ValueError("ELF section header 越界")
        raw_headers.append(struct.unpack_from("<IIIIIIIIII", data, position))
    names_header = raw_headers[names_index]
    names = data[names_header[4]:names_header[4] + names_header[5]]

    def get_name(offset: int) -> str:
        end = names.find(b"\0", offset)
        if end < 0:
            end = len(names)
        return names[offset:end].decode("ascii", errors="replace")

    sections = [
        ElfSection(
            name=get_name(header[0]),
            section_type=header[1],
            flags=header[2],
            address=header[3],
            offset=header[4],
            size=header[5],
            link=header[6],
            entry_size=header[9],
        )
        for header in raw_headers
    ]
    return data, sections


def undefined_symbols(path: Path) -> list[str]:
    """List named SHN_UNDEF symbols from every ELF32 symbol table."""
    data, sections = read_sections(path)
    found: set[str] = set()
    for section in sections:
        if section.section_type != 2 or section.entry_size < 16:
            continue
        if section.link >= len(sections):
            raise ValueError("ELF symbol string table 索引越界")
        strings_section = sections[section.link]
        strings = data[
            strings_section.offset:strings_section.offset + strings_section.size
        ]
        for offset in range(section.offset, section.offset + section.size, section.entry_size):
            if offset + 16 > len(data):
                raise ValueError("ELF symbol entry 越界")
            name_offset, _, _, _, _, section_index = struct.unpack_from(
                "<IIIBBH", data, offset
            )
            if section_index != 0 or name_offset == 0 or name_offset >= len(strings):
                continue
            end = strings.find(b"\0", name_offset)
            if end < 0:
                end = len(strings)
            found.add(strings[name_offset:end].decode("ascii", errors="replace"))
    return sorted(found)


def executable_sections(path: Path) -> Iterable[tuple[int, bytes]]:
    """Yield (virtual address, bytes) for ELF sections with SHF_EXECINSTR."""
    data, sections = read_sections(path)
    for section in sections:
        if section.flags & 0x4 and section.size > 0:
            yield section.address, data[section.offset:section.offset + section.size]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("elf", type=Path)
    args = parser.parse_args()
    for symbol in undefined_symbols(args.elf):
        print(symbol)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
