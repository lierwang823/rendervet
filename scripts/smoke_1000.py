"""Run a local 1,000-image smoke scan using only synthetic fixtures."""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rendervet.config import load_contract  # noqa: E402
from rendervet.demo import png_bytes  # noqa: E402
from rendervet.scanner import scan_contract  # noqa: E402

if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as temporary:
        job = Path(temporary)
        outputs = job / "outputs"
        outputs.mkdir()
        for number in range(1, 1001):
            color = (number & 255, (number >> 8) & 255, (number * 17) & 255)
            (outputs / f"frame_{number:04d}.png").write_bytes(png_bytes(8, 8, color))
        contract_path = job / "rendervet.toml"
        contract_path.write_text(
            """version = 1
[project]
name = "1,000-image smoke test"
root = "outputs"
report_dir = ".rendervet"
[[batch]]
id = "frames"
glob = "frame_*.png"
kind = "image"
expected_count = 1000
sequence_regex = 'frame_(\\d+)'
sequence_start = 1
sequence_end = 1000
width = 8
height = 8
duplicates = "error"
""",
            encoding="utf-8",
        )
        started = time.perf_counter()
        result = scan_contract(load_contract(contract_path))
        elapsed = time.perf_counter() - started
        if not result.passed:
            raise SystemExit("smoke scan failed")
        print(f"PASS  {result.files} synthetic images in {elapsed:.3f}s")
