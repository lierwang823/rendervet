"""Regenerate the committed, synthetic RenderVet demo fixture."""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rendervet.demo import DEMO_MARKER, create_demo  # noqa: E402

if __name__ == "__main__":
    destination = ROOT / "examples" / "image-batch"
    with tempfile.TemporaryDirectory() as temporary:
        generated = Path(temporary) / "image-batch"
        contract = create_demo(generated)
        output_destination = destination / "outputs"
        if output_destination.exists():
            shutil.rmtree(output_destination)
        shutil.copytree(generated / "outputs", output_destination)
        shutil.copy2(contract, destination / "rendervet.toml")
        shutil.copy2(generated / DEMO_MARKER, destination / DEMO_MARKER)
