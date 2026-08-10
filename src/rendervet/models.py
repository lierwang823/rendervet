"""Shared data models for RenderVet scans and reports."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class Finding:
    code: str
    severity: Severity
    message: str
    batch_id: str
    path: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        value = asdict(self)
        value["severity"] = self.severity.value
        return value


@dataclass
class MediaInfo:
    kind: str = "unknown"
    format: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    duration: Optional[float] = None
    frame_rate: Optional[float] = None
    video_codec: Optional[str] = None
    audio_codec: Optional[str] = None
    has_audio: Optional[bool] = None
    probe: str = "none"

    def summary(self) -> str:
        parts: List[str] = []
        if self.width is not None and self.height is not None:
            parts.append(f"{self.width}x{self.height}")
        if self.duration is not None:
            parts.append(f"{self.duration:.2f}s")
        if self.frame_rate is not None:
            parts.append(f"{self.frame_rate:.2f}fps")
        if self.format:
            parts.append(self.format)
        return " · ".join(parts) or self.kind


@dataclass
class FileRecord:
    path: Path
    relative_path: str
    size: int
    modified_at: datetime
    extension: str
    sha256: str
    sequence_number: Optional[int] = None
    media: MediaInfo = field(default_factory=MediaInfo)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "size": self.size,
            "modified_at": self.modified_at.isoformat(),
            "extension": self.extension,
            "sha256": self.sha256,
            "sequence_number": self.sequence_number,
            "media": asdict(self.media),
        }


@dataclass
class BatchResult:
    batch_id: str
    matched_glob: str
    records: List[FileRecord] = field(default_factory=list)
    findings: List[Finding] = field(default_factory=list)
    missing_sequence_numbers: List[int] = field(default_factory=list)
    retry_paths: List[str] = field(default_factory=list)

    @property
    def errors(self) -> int:
        return sum(item.severity is Severity.ERROR for item in self.findings)

    @property
    def warnings(self) -> int:
        return sum(item.severity is Severity.WARNING for item in self.findings)

    @property
    def passed(self) -> bool:
        return self.errors == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.batch_id,
            "glob": self.matched_glob,
            "passed": self.passed,
            "errors": self.errors,
            "warnings": self.warnings,
            "missing_sequence_numbers": self.missing_sequence_numbers,
            "retry_paths": self.retry_paths,
            "files": [record.to_dict() for record in self.records],
            "findings": [finding.to_dict() for finding in self.findings],
        }


@dataclass
class ScanResult:
    project_name: str
    config_path: Path
    root: Path
    generated_at: datetime
    batches: List[BatchResult]

    @property
    def files(self) -> int:
        return sum(len(batch.records) for batch in self.batches)

    @property
    def errors(self) -> int:
        return sum(batch.errors for batch in self.batches)

    @property
    def warnings(self) -> int:
        return sum(batch.warnings for batch in self.batches)

    @property
    def passed(self) -> bool:
        return self.errors == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": 1,
            "project": self.project_name,
            "config_path": self.config_path.name,
            "root": ".",
            "generated_at": self.generated_at.isoformat(),
            "passed": self.passed,
            "summary": {
                "batches": len(self.batches),
                "files": self.files,
                "errors": self.errors,
                "warnings": self.warnings,
            },
            "batches": [batch.to_dict() for batch in self.batches],
        }
