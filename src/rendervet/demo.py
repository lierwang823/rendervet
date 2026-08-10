"""Create an original deterministic failure fixture for `rendervet demo`."""

from __future__ import annotations

import os
import shutil
import struct
import zlib
from pathlib import Path
from typing import Tuple

DEMO_MARKER = ".rendervet-demo-marker"


def png_bytes(width: int, height: int, color: Tuple[int, int, int]) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(kind)
        crc = zlib.crc32(payload, crc) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)

    row = bytes([0]) + bytes(color) * width
    pixels = row * height
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(pixels, 9))
        + chunk(b"IEND", b"")
    )


def create_demo(destination: Path, force: bool = False) -> Path:
    destination = destination.expanduser().resolve()
    if destination.exists():
        if not force:
            raise FileExistsError(f"demo destination already exists: {destination}")
        marker = destination / DEMO_MARKER
        if (
            not marker.is_file()
            or marker.read_text(encoding="utf-8").strip() != "rendervet-demo-v1"
        ):
            raise FileExistsError(f"refusing to replace an unmarked directory: {destination}")
        shutil.rmtree(destination)
    outputs = destination / "outputs"
    outputs.mkdir(parents=True)
    (destination / DEMO_MARKER).write_text("rendervet-demo-v1\n", encoding="utf-8")

    palette = [
        (52, 84, 209),
        (72, 187, 120),
        (226, 96, 110),
        (244, 180, 65),
        (133, 92, 205),
        (54, 179, 188),
        (232, 122, 66),
        (102, 115, 138),
        (194, 80, 151),
        (71, 147, 230),
        (110, 190, 92),
        (214, 75, 75),
    ]
    for number in range(1, 13):
        if number == 4:
            continue
        suffix = ".jpg" if number == 12 else ".png"
        path = outputs / f"shot_{number:03d}{suffix}"
        if number == 6:
            path.write_bytes(b"not a png")
        elif number == 8:
            path.write_bytes(png_bytes(96, 64, palette[number - 1]))
        elif number == 9:
            path.write_bytes((outputs / "shot_003.png").read_bytes())
        else:
            path.write_bytes(png_bytes(64, 64, palette[number - 1]))
    old_time = 946684800  # 2000-01-01 UTC
    os.utime(outputs / "shot_011.png", (old_time, old_time))

    contract = destination / "rendervet.toml"
    contract.write_text(
        """version = 1

[project]
name = "RenderVet demo: intentionally broken batch"
root = "outputs"
report_dir = ".rendervet"
fresh_after = "2020-01-01T00:00:00Z"

[[batch]]
id = "shots"
glob = "shot_*"
kind = "image"
expected_count = 12
sequence_regex = 'shot_(\\d+)'
sequence_start = 1
sequence_end = 12
allowed_extensions = [".png"]
min_bytes = 50
width = 64
height = 64
duplicates = "error"
""",
        encoding="utf-8",
    )
    return contract
