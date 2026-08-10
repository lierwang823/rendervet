from __future__ import annotations

import json
from pathlib import Path

import pytest

from rendervet.config import load_contract
from rendervet.demo import create_demo, png_bytes
from rendervet.report import build_retry_manifest, render_html, render_terminal, write_reports
from rendervet.scanner import scan_contract


def test_demo_detects_six_failure_categories(tmp_path: Path) -> None:
    contract_path = create_demo(tmp_path / "demo")
    contract = load_contract(contract_path)
    result = scan_contract(contract)
    codes = {finding.code for batch in result.batches for finding in batch.findings}
    assert result.passed is False
    assert {
        "count_mismatch",
        "media_probe_failed",
        "width_mismatch",
        "stale_file",
        "extension_not_allowed",
        "sequence_item_missing",
        "exact_duplicate",
    } <= codes
    retry = build_retry_manifest(result)
    failures = retry["batches"][0]["failures"]  # type: ignore[index]
    assert any(item["sequence_number"] == 4 for item in failures)  # type: ignore[index]
    retried_paths = {item["path"] for item in failures if item["path"]}  # type: ignore[index]
    assert {"shot_003.png", "shot_009.png"} <= retried_paths


def test_clean_image_batch_passes_and_reports_are_relative(tmp_path: Path) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "frame_001.png").write_bytes(png_bytes(16, 16, (10, 20, 30)))
    (outputs / "frame_002.png").write_bytes(png_bytes(16, 16, (40, 50, 60)))
    contract_path = tmp_path / "rendervet.toml"
    contract_path.write_text(
        """version = 1
[project]
name = "clean"
root = "outputs"
report_dir = ".rendervet"
[[batch]]
id = "frames"
glob = "frame_*.png"
kind = "image"
expected_count = 2
sequence_regex = 'frame_(\\d+)'
sequence_start = 1
sequence_end = 2
width = 16
height = 16
duplicates = "error"
""",
        encoding="utf-8",
    )
    contract = load_contract(contract_path)
    result = scan_contract(contract)
    assert result.passed is True
    _, json_path, retry_path = write_reports(result, contract.project.report_dir)
    report_text = json_path.read_text(encoding="utf-8")
    assert str(tmp_path) not in report_text
    assert json.loads(retry_path.read_text(encoding="utf-8"))["batches"] == []


def test_symlink_is_rejected_without_reading_target(tmp_path: Path) -> None:
    if not hasattr(Path, "symlink_to"):
        pytest.skip("symlinks unavailable")
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(png_bytes(8, 8, (1, 2, 3)))
    link = outputs / "frame_001.png"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable")
    contract_path = tmp_path / "rendervet.toml"
    contract_path.write_text(
        """version = 1
[project]
name = "links"
root = "outputs"
[[batch]]
id = "frames"
glob = "frame_*"
kind = "image"
""",
        encoding="utf-8",
    )
    result = scan_contract(load_contract(contract_path))
    assert result.passed is False
    assert result.batches[0].findings[0].code == "symlink_not_allowed"


def test_directory_symlink_is_not_followed(tmp_path: Path) -> None:
    outputs = tmp_path / "outputs"
    outside = tmp_path / "outside"
    outputs.mkdir()
    outside.mkdir()
    (outside / "frame_001.png").write_bytes(png_bytes(8, 8, (1, 2, 3)))
    link = outputs / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    contract_path = tmp_path / "rendervet.toml"
    contract_path.write_text(
        """version = 1
[project]
name = "directory link"
root = "outputs"
[[batch]]
id = "frames"
glob = "linked/*.png"
kind = "image"
""",
        encoding="utf-8",
    )

    result = scan_contract(load_contract(contract_path))

    assert result.files == 0
    assert [finding.code for finding in result.batches[0].findings] == ["symlink_not_allowed"]
    assert result.batches[0].findings[0].path == "linked"


def test_read_failures_never_expose_absolute_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "frame_001.png").write_bytes(png_bytes(8, 8, (1, 2, 3)))
    contract_path = tmp_path / "rendervet.toml"
    contract_path.write_text(
        """version = 1
[project]
name = "private paths"
root = "outputs"
[[batch]]
id = "frames"
glob = "*.png"
kind = "image"
""",
        encoding="utf-8",
    )

    def deny_hash(path: Path) -> str:
        raise PermissionError(f"permission denied: {path}")

    monkeypatch.setattr("rendervet.scanner._sha256", deny_hash)
    result = scan_contract(load_contract(contract_path))
    report_path = tmp_path / "reports" / "report.html"
    rendered_outputs = (
        json.dumps(result.to_dict(), ensure_ascii=False),
        json.dumps(build_retry_manifest(result), ensure_ascii=False),
        render_html(result, report_path),
        render_terminal(result, color=False),
    )

    assert result.batches[0].findings[0].code == "file_read_failed"
    for rendered in rendered_outputs:
        assert str(tmp_path) not in rendered
        assert "permission denied" not in rendered


def test_file_swapped_to_symlink_after_hash_is_not_probed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    candidate = outputs / "frame_001.png"
    candidate.write_bytes(png_bytes(8, 8, (1, 2, 3)))
    outside = tmp_path / "outside.png"
    outside.write_bytes(png_bytes(123, 77, (9, 8, 7)))
    contract_path = tmp_path / "rendervet.toml"
    contract_path.write_text(
        """version = 1
[project]
name = "swap defense"
root = "outputs"
[[batch]]
id = "frames"
glob = "*.png"
kind = "image"
""",
        encoding="utf-8",
    )

    def swap_after_hash(path: Path) -> str:
        path.unlink()
        path.symlink_to(outside)
        return "a" * 64

    monkeypatch.setattr("rendervet.scanner._sha256", swap_after_hash)
    result = scan_contract(load_contract(contract_path))

    record = result.batches[0].records[0]
    assert record.media.probe == "none"
    assert [finding.code for finding in result.batches[0].findings] == ["file_changed_during_scan"]
