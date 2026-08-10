from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from rendervet.demo import png_bytes
from rendervet.models import BatchResult, FileRecord, Finding, MediaInfo, ScanResult, Severity
from rendervet.report import render_html, write_reports


def scan_result(tmp_path: Path, batch: BatchResult | None = None) -> ScanResult:
    return ScanResult(
        project_name="report test",
        config_path=tmp_path / "rendervet.toml",
        root=tmp_path,
        generated_at=datetime.now(timezone.utc),
        batches=[batch or BatchResult(batch_id="images", matched_glob="*")],
    )


def test_html_escapes_untrusted_filenames(tmp_path: Path) -> None:
    malicious = tmp_path / "<img onerror=alert(1)>.png"
    malicious.write_bytes(png_bytes(2, 2, (1, 2, 3)))
    record = FileRecord(
        path=malicious,
        relative_path=malicious.name,
        size=malicious.stat().st_size,
        modified_at=datetime.now(timezone.utc),
        extension=".png",
        sha256="a" * 64,
        media=MediaInfo(kind="image", format="png", width=2, height=2, probe="native"),
    )
    result = scan_result(
        tmp_path,
        BatchResult(batch_id="images", matched_glob="*", records=[record]),
    )
    rendered = render_html(result, tmp_path / "report.html")
    assert "<img onerror=alert(1)>" not in rendered
    assert "&lt;img onerror=alert(1)&gt;.png" in rendered


def test_html_shows_path_finding_without_file_record(tmp_path: Path) -> None:
    batch = BatchResult(
        batch_id="images",
        matched_glob="*",
        findings=[
            Finding(
                code="symlink_not_allowed",
                severity=Severity.ERROR,
                message="symbolic links are not scanned",
                batch_id="images",
                path="linked/<unsafe>.png",
            )
        ],
    )

    rendered = render_html(scan_result(tmp_path, batch), tmp_path / "report.html")

    assert "symlink_not_allowed" in rendered
    assert "linked/&lt;unsafe&gt;.png" in rendered
    assert "symbolic links are not scanned" in rendered


def test_write_reports_rejects_symlink_report_directory(tmp_path: Path) -> None:
    target = tmp_path / "actual-reports"
    target.mkdir()
    link = tmp_path / "report-link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")

    with pytest.raises(OSError, match="symlink component"):
        write_reports(scan_result(tmp_path), link)

    assert list(target.iterdir()) == []


def test_write_reports_rejects_symlink_ancestor(tmp_path: Path) -> None:
    target = tmp_path / "actual-parent"
    target.mkdir()
    link = tmp_path / "parent-link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")

    with pytest.raises(OSError, match="symlink component"):
        write_reports(scan_result(tmp_path), link / "nested" / "reports")

    assert list(target.iterdir()) == []


def test_dangling_legacy_temp_symlink_is_never_followed(tmp_path: Path) -> None:
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    outside = tmp_path / "outside.html"
    hostile_temp = report_dir / ".report.html.tmp"
    try:
        hostile_temp.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable")

    html_path, _, _ = write_reports(scan_result(tmp_path), report_dir)

    assert outside.exists() is False
    assert html_path.is_file()
    assert html_path.is_symlink() is False
    assert hostile_temp.is_symlink()
