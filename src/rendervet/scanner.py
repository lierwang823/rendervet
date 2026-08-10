"""Contract-driven batch scanner."""

from __future__ import annotations

import hashlib
import os
import stat
from collections import defaultdict
from datetime import datetime, timezone
from fnmatch import fnmatchcase
from pathlib import Path
from typing import DefaultDict, List, Optional, Sequence, Set, Tuple

from rendervet.config import BatchConfig, Contract
from rendervet.media import MediaProbeError, classify_extension, probe_media
from rendervet.models import (
    BatchResult,
    FileRecord,
    Finding,
    ScanResult,
    Severity,
)


class ScanError(RuntimeError):
    """Raised when a scan cannot run at all."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_glob(root: Path, pattern: str) -> Tuple[List[Path], List[Path]]:
    """Expand a glob without ever descending through a symbolic link."""

    parts = Path(pattern).parts
    matched: Set[Path] = set()
    blocked_symlinks: Set[Path] = set()

    def entries(directory: Path) -> List[Path]:
        try:
            return sorted(directory.iterdir(), key=lambda item: item.name)
        except OSError as exc:
            raise ScanError("cannot read a directory while expanding the batch glob") from exc

    def walk(directory: Path, index: int) -> None:
        if index >= len(parts):
            return
        component = parts[index]
        final = index == len(parts) - 1

        if component == "**":
            walk(directory, index + 1)
            for child in entries(directory):
                try:
                    child_stat = child.lstat()
                except OSError as exc:
                    raise ScanError("cannot inspect a path while expanding the batch glob") from exc
                if stat.S_ISLNK(child_stat.st_mode):
                    if final or index + 1 < len(parts):
                        blocked_symlinks.add(child)
                    continue
                if stat.S_ISDIR(child_stat.st_mode):
                    walk(child, index)
                elif final and stat.S_ISREG(child_stat.st_mode):
                    matched.add(child)
            return

        for child in entries(directory):
            if not fnmatchcase(child.name, component):
                continue
            try:
                child_stat = child.lstat()
            except OSError as exc:
                raise ScanError("cannot inspect a path while expanding the batch glob") from exc
            if stat.S_ISLNK(child_stat.st_mode):
                blocked_symlinks.add(child)
            elif final:
                if stat.S_ISREG(child_stat.st_mode):
                    matched.add(child)
            elif stat.S_ISDIR(child_stat.st_mode):
                walk(child, index + 1)

    walk(root, 0)
    return sorted(matched, key=str), sorted(blocked_symlinks, key=str)


def _validate_candidate(root: Path, path: Path) -> str:
    """Return a safe relative path or raise before a candidate is opened."""

    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise OSError("candidate is outside the scan root") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if stat.S_ISLNK(current.lstat().st_mode):
            raise OSError("candidate contains a symbolic-link component")
    try:
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise OSError("candidate resolves outside the scan root") from exc
    if not stat.S_ISREG(path.lstat().st_mode):
        raise OSError("candidate is not a regular file")
    return relative.as_posix()


def _finding(
    batch: BatchConfig,
    code: str,
    severity: Severity,
    message: str,
    path: Optional[str] = None,
    **details: object,
) -> Finding:
    return Finding(
        code=code,
        severity=severity,
        message=message,
        batch_id=batch.id,
        path=path,
        details=dict(details),
    )


def _record_file(root: Path, path: Path, batch: BatchConfig) -> FileRecord:
    file_stat = path.stat()
    relative_path = path.relative_to(root).as_posix()
    sequence_number: Optional[int] = None
    sequence_regex = batch.compiled_sequence_regex
    if sequence_regex is not None:
        match = sequence_regex.search(path.name)
        if match is not None:
            try:
                sequence_number = int(match.group(1))
            except (TypeError, ValueError):
                sequence_number = None
    return FileRecord(
        path=path,
        relative_path=relative_path,
        size=file_stat.st_size,
        modified_at=datetime.fromtimestamp(file_stat.st_mtime, tz=timezone.utc),
        extension=path.suffix.lower(),
        sha256=_sha256(path),
        sequence_number=sequence_number,
    )


def _check_record(root: Path, record: FileRecord, batch: BatchConfig) -> List[Finding]:
    findings: List[Finding] = []
    relative_path = record.relative_path
    if batch.allowed_extensions and record.extension not in batch.allowed_extensions:
        findings.append(
            _finding(
                batch,
                "extension_not_allowed",
                Severity.ERROR,
                f"extension {record.extension or '(none)'} is not allowed",
                relative_path,
                actual=record.extension,
                expected=list(batch.allowed_extensions),
            )
        )
    if record.size < batch.min_bytes:
        findings.append(
            _finding(
                batch,
                "file_too_small",
                Severity.ERROR,
                f"file is {record.size} bytes; minimum is {batch.min_bytes}",
                relative_path,
                actual=record.size,
                minimum=batch.min_bytes,
            )
        )
    if batch.max_bytes is not None and record.size > batch.max_bytes:
        findings.append(
            _finding(
                batch,
                "file_too_large",
                Severity.ERROR,
                f"file is {record.size} bytes; maximum is {batch.max_bytes}",
                relative_path,
                actual=record.size,
                maximum=batch.max_bytes,
            )
        )
    if batch.fresh_after is not None and record.modified_at < batch.fresh_after:
        findings.append(
            _finding(
                batch,
                "stale_file",
                Severity.ERROR,
                f"file predates fresh_after ({batch.fresh_after.isoformat()})",
                relative_path,
                modified_at=record.modified_at.isoformat(),
                fresh_after=batch.fresh_after.isoformat(),
            )
        )

    try:
        _validate_candidate(root, record.path)
    except OSError:
        findings.append(
            _finding(
                batch,
                "file_changed_during_scan",
                Severity.ERROR,
                "file is no longer a safe regular file inside project.root",
                relative_path,
            )
        )
        return findings

    try:
        record.media = probe_media(record.path, batch.kind)
    except MediaProbeError as exc:
        findings.append(
            _finding(
                batch,
                "media_probe_failed",
                Severity.ERROR,
                str(exc),
                relative_path,
            )
        )
        return findings

    try:
        current_stat = record.path.stat()
    except OSError:
        findings.append(
            _finding(
                batch,
                "file_changed_during_scan",
                Severity.ERROR,
                "file became unavailable during inspection",
                relative_path,
            )
        )
        return findings
    current_modified = datetime.fromtimestamp(current_stat.st_mtime, tz=timezone.utc)
    if current_stat.st_size != record.size or current_modified != record.modified_at:
        findings.append(
            _finding(
                batch,
                "file_changed_during_scan",
                Severity.ERROR,
                "file size or modification time changed during inspection",
                relative_path,
            )
        )

    inferred_kind = classify_extension(record.path)
    if batch.kind not in {"auto", "file"} and record.media.kind != batch.kind:
        findings.append(
            _finding(
                batch,
                "media_kind_mismatch",
                Severity.ERROR,
                f"expected {batch.kind}; inspected as {record.media.kind}",
                relative_path,
                expected=batch.kind,
                actual=record.media.kind,
                extension_kind=inferred_kind,
            )
        )
    if batch.width is not None and record.media.width != batch.width:
        findings.append(
            _finding(
                batch,
                "width_mismatch",
                Severity.ERROR,
                f"expected width {batch.width}; got {record.media.width}",
                relative_path,
                expected=batch.width,
                actual=record.media.width,
            )
        )
    if batch.height is not None and record.media.height != batch.height:
        findings.append(
            _finding(
                batch,
                "height_mismatch",
                Severity.ERROR,
                f"expected height {batch.height}; got {record.media.height}",
                relative_path,
                expected=batch.height,
                actual=record.media.height,
            )
        )
    if batch.min_duration is not None and (
        record.media.duration is None or record.media.duration < batch.min_duration
    ):
        findings.append(
            _finding(
                batch,
                "duration_too_short",
                Severity.ERROR,
                f"minimum duration is {batch.min_duration}s; got {record.media.duration}",
                relative_path,
                expected_min=batch.min_duration,
                actual=record.media.duration,
            )
        )
    if batch.max_duration is not None and (
        record.media.duration is None or record.media.duration > batch.max_duration
    ):
        findings.append(
            _finding(
                batch,
                "duration_too_long",
                Severity.ERROR,
                f"maximum duration is {batch.max_duration}s; got {record.media.duration}",
                relative_path,
                expected_max=batch.max_duration,
                actual=record.media.duration,
            )
        )
    if batch.require_audio and record.media.has_audio is not True:
        findings.append(
            _finding(
                batch,
                "audio_stream_missing",
                Severity.ERROR,
                "required audio stream is missing",
                relative_path,
            )
        )
    return findings


def _check_sequences(batch: BatchConfig, result: BatchResult) -> None:
    sequence_regex = batch.compiled_sequence_regex
    if sequence_regex is None:
        return
    by_number: DefaultDict[int, List[FileRecord]] = defaultdict(list)
    for record in result.records:
        if record.sequence_number is None:
            result.findings.append(
                _finding(
                    batch,
                    "sequence_number_missing",
                    Severity.ERROR,
                    "filename does not match sequence_regex",
                    record.relative_path,
                )
            )
        else:
            by_number[record.sequence_number].append(record)

    for number, records in by_number.items():
        if len(records) > 1:
            paths = [record.relative_path for record in records]
            for path in paths:
                result.findings.append(
                    _finding(
                        batch,
                        "sequence_number_duplicate",
                        Severity.ERROR,
                        f"sequence number {number} appears {len(records)} times",
                        path,
                        sequence_number=number,
                        paths=paths,
                    )
                )

    if batch.sequence_start is None or batch.sequence_end is None:
        return
    expected = set(range(batch.sequence_start, batch.sequence_end + 1))
    actual = set(by_number)
    result.missing_sequence_numbers = sorted(expected - actual)
    for number in result.missing_sequence_numbers:
        result.findings.append(
            _finding(
                batch,
                "sequence_item_missing",
                Severity.ERROR,
                f"expected sequence number {number} is missing",
                sequence_number=number,
            )
        )
    for number in sorted(actual - expected):
        result.findings.append(
            _finding(
                batch,
                "sequence_item_out_of_range",
                Severity.WARNING,
                f"sequence number {number} is outside the expected range",
                sequence_number=number,
            )
        )


def _check_duplicates(batch: BatchConfig, result: BatchResult) -> None:
    if batch.duplicates == "ignore":
        return
    by_hash: DefaultDict[str, List[FileRecord]] = defaultdict(list)
    for record in result.records:
        by_hash[record.sha256].append(record)
    severity = Severity.ERROR if batch.duplicates == "error" else Severity.WARNING
    for digest, records in by_hash.items():
        if len(records) < 2:
            continue
        paths = [record.relative_path for record in records]
        for path in paths:
            result.findings.append(
                _finding(
                    batch,
                    "exact_duplicate",
                    severity,
                    f"{len(records)} files have identical content",
                    path,
                    sha256=digest,
                    paths=paths,
                )
            )


def scan_batch(root: Path, batch: BatchConfig, exclude_dir: Optional[Path] = None) -> BatchResult:
    result = BatchResult(batch_id=batch.id, matched_glob=batch.glob)
    try:
        paths, blocked_symlinks = _safe_glob(root, batch.glob)
        if exclude_dir is not None:
            excluded = exclude_dir

            def outside_report(path: Path) -> bool:
                try:
                    path.relative_to(excluded)
                    return False
                except ValueError:
                    return True

            paths = [path for path in paths if outside_report(path)]
            blocked_symlinks = [path for path in blocked_symlinks if outside_report(path)]
    except (OSError, ValueError) as exc:
        raise ScanError(f"cannot expand glob for batch {batch.id}") from exc

    if batch.expected_count is not None and len(paths) != batch.expected_count:
        result.findings.append(
            _finding(
                batch,
                "count_mismatch",
                Severity.ERROR,
                f"expected {batch.expected_count} files; found {len(paths)}",
                expected=batch.expected_count,
                actual=len(paths),
            )
        )

    failed_paths: Set[str] = set()
    for path in blocked_symlinks:
        relative_path = path.relative_to(root).as_posix()
        result.findings.append(
            _finding(
                batch,
                "symlink_not_allowed",
                Severity.ERROR,
                "symbolic links are not inspected",
                relative_path,
            )
        )
        failed_paths.add(relative_path)

    for path in paths:
        try:
            relative_path = _validate_candidate(root, path)
        except OSError:
            relative_path = path.relative_to(root).as_posix()
            result.findings.append(
                _finding(
                    batch,
                    "unsafe_path",
                    Severity.ERROR,
                    "path is no longer a safe regular file inside project.root",
                    relative_path,
                )
            )
            failed_paths.add(relative_path)
            continue
        try:
            record = _record_file(root, path, batch)
            result.records.append(record)
            findings = _check_record(root, record, batch)
            result.findings.extend(findings)
            if any(finding.severity is Severity.ERROR for finding in findings):
                failed_paths.add(record.relative_path)
        except OSError:
            result.findings.append(
                _finding(
                    batch,
                    "file_read_failed",
                    Severity.ERROR,
                    "file could not be read safely",
                    relative_path,
                )
            )
            failed_paths.add(relative_path)

    _check_sequences(batch, result)
    _check_duplicates(batch, result)
    for finding in result.findings:
        if finding.severity is Severity.ERROR and finding.path:
            failed_paths.add(finding.path)
    result.retry_paths = sorted(failed_paths)
    return result


def scan_contract(contract: Contract) -> ScanResult:
    root = contract.project.root
    if not root.exists():
        raise ScanError(f"project.root does not exist: {root}")
    if not root.is_dir():
        raise ScanError(f"project.root is not a directory: {root}")
    exclude_dir: Optional[Path] = None
    try:
        contract.project.report_dir.relative_to(root)
        exclude_dir = contract.project.report_dir
    except ValueError:
        pass
    batches: Sequence[BatchResult] = tuple(
        scan_batch(root, batch, exclude_dir) for batch in contract.batches
    )
    return ScanResult(
        project_name=contract.project.name,
        config_path=contract.config_path,
        root=root,
        generated_at=datetime.now(timezone.utc),
        batches=list(batches),
    )
