"""Render a raw 80x25 VGA text buffer as a self-contained HTML artifact."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import html
from pathlib import Path

VGA_BYTES = 80 * 25 * 2
VGA_16 = (
    "#000000", "#0000AA", "#00AA00", "#00AAAA",
    "#AA0000", "#AA00AA", "#AA5500", "#AAAAAA",
    "#555555", "#5555FF", "#55FF55", "#55FFFF",
    "#FF5555", "#FF55FF", "#FFFF55", "#FFFFFF",
)


def render_vga(memory: bytes, output: Path, title: str = "AIOS v0.1 screen dump") -> None:
    """Render exactly 4000 interleaved VGA character/attribute bytes."""
    if len(memory) != VGA_BYTES:
        raise ValueError(f"VGA dump 必须是 {VGA_BYTES} 字节，实际 {len(memory)}")
    rows: list[str] = []
    for row in range(25):
        spans: list[str] = []
        for column in range(80):
            offset = (row * 80 + column) * 2
            code = memory[offset]
            attribute = memory[offset + 1]
            character = chr(code) if 0x20 <= code <= 0x7E else " "
            escaped = html.escape(character, quote=False)
            spans.append(
                f'<span style="color:{VGA_16[attribute & 0x0F]};'
                f'background:{VGA_16[(attribute >> 4) & 0x0F]}">{escaped}</span>'
            )
        rows.append("".join(spans))
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    screen_rows = "\n".join(rows)
    document = (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        f"<title>{html.escape(title)}</title>"
        "<style>body{margin:0;padding:24px;background:#171717;color:#aaa}"
        ".frame{display:inline-block;padding:14px;background:#000;border:8px solid #444;"
        "box-shadow:0 8px 24px #000}pre{margin:0;font:16px/1 monospace;letter-spacing:0}"
        ".meta{font:12px sans-serif;margin-bottom:10px}</style></head><body>"
        f'<div class="meta">{html.escape(title)} @ {html.escape(timestamp)}</div>'
        f'<div class="frame"><pre>{screen_rows}</pre></div></body></html>\n'
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="4000-byte raw VGA memory dump")
    parser.add_argument("output", type=Path, nargs="?", default=Path("build/screen.html"))
    args = parser.parse_args()
    render_vga(args.input.read_bytes(), args.output)
    print(f"[dump] {args.output} (80x25, {VGA_BYTES} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
