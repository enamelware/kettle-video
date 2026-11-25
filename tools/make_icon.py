# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mario Carabotta

"""Draw the app's icon, ui/kettle-video.png (the installer work).

Developer only. A placeholder until the brand has an icon of its own: a
rounded square in Enamel's raised surface grey with a play mark in Enamel's
accent (coral), the only colours the brand uses besides the wordmark's
mustard. Standard library only: shapes are drawn with 4x4 samples per pixel
for smooth edges and written as a plain PNG.

    python3 tools/make_icon.py [OUT]
"""

import struct
import sys
import zlib
from pathlib import Path

SIZE = 256
SAMPLES = 4
SURFACE = (0x23, 0x26, 0x2E)  # --en-surface-raised (--en-grey-6)
ACCENT = (0xEE, 0x8A, 0x72)   # --en-accent-coral
RADIUS = 56
# The play mark: a triangle pointing right, nudged right of centre so it
# looks centred.
TRIANGLE = ((96, 72), (96, 184), (188, 128))
OUT = Path(__file__).resolve().parent.parent / "ui" / "kettle-video.png"


def in_rounded_square(x, y):
    cx = min(max(x, RADIUS), SIZE - RADIUS)
    cy = min(max(y, RADIUS), SIZE - RADIUS)
    return (x - cx) ** 2 + (y - cy) ** 2 <= RADIUS ** 2


def in_triangle(x, y):
    (ax, ay), (bx, by), (cx, cy) = TRIANGLE

    def side(px, py, qx, qy):
        return (qx - px) * (y - py) - (qy - py) * (x - px)

    d1, d2, d3 = side(ax, ay, bx, by), side(bx, by, cx, cy), side(cx, cy, ax, ay)
    return (d1 >= 0 and d2 >= 0 and d3 >= 0) or (d1 <= 0 and d2 <= 0 and d3 <= 0)


def pixel(px, py):
    """(r, g, b, a) for one pixel, averaged over its samples."""
    totals = [0, 0, 0, 0]
    for sy in range(SAMPLES):
        for sx in range(SAMPLES):
            x = px + (sx + 0.5) / SAMPLES
            y = py + (sy + 0.5) / SAMPLES
            if not in_rounded_square(x, y):
                continue
            colour = ACCENT if in_triangle(x, y) else SURFACE
            totals[0] += colour[0]
            totals[1] += colour[1]
            totals[2] += colour[2]
            totals[3] += 255
    count = SAMPLES * SAMPLES
    covered = totals[3] // 255
    if not covered:
        return (0, 0, 0, 0)
    return (totals[0] // covered, totals[1] // covered, totals[2] // covered,
            totals[3] // count)


def png(width, height, rows):
    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    raw = b"".join(b"\x00" + bytes(v for p in row for v in p) for row in rows)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def main(argv):
    out = Path(argv[0]) if argv else OUT
    rows = [[pixel(x, y) for x in range(SIZE)] for y in range(SIZE)]
    out.write_bytes(png(SIZE, SIZE, rows))
    print(f"Wrote {out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
