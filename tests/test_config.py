from __future__ import annotations

import re
from pathlib import Path

import pytest

from rendervet.config import ConfigError, load_contract


def write_contract(tmp_path: Path, extra: str = "") -> Path:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    path = tmp_path / "rendervet.toml"
    path.write_text(
        f"""version = 1

[project]
name = "test batch"
root = "outputs"
report_dir = ".rendervet"

[[batch]]
id = "frames"
glob = "frame_*"
kind = "image"
expected_count = 2
sequence_regex = 'frame_(\\d+)'
sequence_start = 1
sequence_end = 2
allowed_extensions = ["png"]
width = 64
height = 64
{extra}
""",
        encoding="utf-8",
    )
    return path


def test_load_contract_resolves_paths_and_extensions(tmp_path: Path) -> None:
    contract = load_contract(write_contract(tmp_path))
    assert contract.project.root == (tmp_path / "outputs").resolve()
    assert contract.project.report_dir == (tmp_path / ".rendervet").resolve()
    assert contract.batches[0].allowed_extensions == (".png",)
    assert contract.batches[0].compiled_sequence_regex is not None


def test_report_directory_preserves_lexical_symlink_path(tmp_path: Path) -> None:
    target = tmp_path / "actual-reports"
    target.mkdir()
    link = tmp_path / "report-link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")

    path = write_contract(tmp_path)
    text = path.read_text(encoding="utf-8").replace(
        'report_dir = ".rendervet"', 'report_dir = "report-link"'
    )
    path.write_text(text, encoding="utf-8")

    contract = load_contract(path)
    assert contract.project.report_dir == link
    assert contract.project.report_dir.is_symlink()
    assert contract.project.report_dir != target


@pytest.mark.parametrize(
    "extra, message",
    [
        ("mystery = 1", "unknown batch[0] key"),
        ('require_audio = "yes"', "require_audio must be true or false"),
        ("max_bytes = 0", "max_bytes must be >= 1"),
    ],
)
def test_rejects_invalid_batch_keys(tmp_path: Path, extra: str, message: str) -> None:
    with pytest.raises(ConfigError, match=re.escape(message)):
        load_contract(write_contract(tmp_path, extra))


def test_rejects_unsafe_glob(tmp_path: Path) -> None:
    path = write_contract(tmp_path)
    text = path.read_text(encoding="utf-8").replace('glob = "frame_*"', 'glob = "../*"')
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="must stay inside project.root"):
        load_contract(path)


def test_rejects_regex_without_capture_group(tmp_path: Path) -> None:
    path = write_contract(tmp_path)
    text = path.read_text(encoding="utf-8").replace(
        "sequence_regex = 'frame_(\\d+)'", "sequence_regex = 'frame_\\d+'"
    )
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="must contain a capture group"):
        load_contract(path)


def test_rejects_report_directory_equal_to_scan_root(tmp_path: Path) -> None:
    path = write_contract(tmp_path)
    text = path.read_text(encoding="utf-8").replace(
        'report_dir = ".rendervet"', 'report_dir = "outputs"'
    )
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="report_dir must not equal"):
        load_contract(path)
