#!/usr/bin/env python3
"""
Generate the PWA app icons (192px and 512px PNGs) with no third-party deps.

Draws a simple Position-Bingo motif: the app's purple background with a tidy
grid of cells and one highlighted "winning" cell in the accent colour. Pure
stdlib (zlib + struct) PNG writer, so it runs anywhere Python does.

    python3 collector/make_icons.py
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ICON_DIR = ROOT / "app" / "icons"

# Palette (matches style.css)
BG = (29, 23, 48)       # --bg
CELL = (52, 42, 76)     # --panel-2
LINE = (67, 56, 94)     # --line
ACCENT = (255, 176, 32) # --accent
ACCENT2 = (70, 201, 139)  # --good


def write_png(path: Path, pixels: list[list[tuple[int, int, int]]]) -> None:
    """Write an RGB PNG from a 2D list of (r,g,b) pixels."""
    height = len(pixels)
    width = len(pixels[0])
    raw = bytearray()
    for row in pixels:
        raw.append(0)  # filter type 0 (none) per scanline
        for (r, g, b) in row:
            raw += bytes((r, g, b))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    idat = zlib.compress(bytes(raw), 9)
    path.write_bytes(sig + chunk(b"IHDR", ihdr)
                     + chunk(b"IDAT", idat) + chunk(b"IEND", b""))


def render(size: int) -> list[list[tuple[int, int, int]]]:
    px = [[BG for _ in range(size)] for _ in range(size)]

    # 4x4 grid of rounded-ish cells within a centred square area.
    n = 4
    margin = round(size * 0.14)
    area = size - margin * 2
    gap = max(2, round(size * 0.03))
    cell = (area - gap * (n - 1)) // n
    # The highlighted "winning" cell (row, col).
    win = (1, 2)

    for r in range(n):
        for c in range(n):
            x0 = margin + c * (cell + gap)
            y0 = margin + r * (cell + gap)
            is_win = (r, c) == win
            fill = ACCENT if is_win else CELL
            border = ACCENT if is_win else LINE
            for y in range(y0, y0 + cell):
                for x in range(x0, x0 + cell):
                    if 0 <= x < size and 0 <= y < size:
                        edge = (x - x0 < 2 or x0 + cell - x <= 2
                                or y - y0 < 2 or y0 + cell - y <= 2)
                        px[y][x] = border if edge else fill

    # A small accent dot in the winning cell centre for a "stamp" feel.
    cx = margin + win[1] * (cell + gap) + cell // 2
    cy = margin + win[0] * (cell + gap) + cell // 2
    rad = max(2, cell // 6)
    for y in range(cy - rad, cy + rad):
        for x in range(cx - rad, cx + rad):
            if (x - cx) ** 2 + (y - cy) ** 2 <= rad * rad:
                if 0 <= x < size and 0 <= y < size:
                    px[y][x] = ACCENT2
    return px


def main() -> int:
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        out = ICON_DIR / f"icon-{size}.png"
        write_png(out, render(size))
        print(f"Wrote {out.relative_to(ROOT)} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
