"""Load and validate RenderVet TOML contracts."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

try:
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.9/3.10
    import tomli as tomllib  # type: ignore[no-redef]


class ConfigError(ValueError):
    """Raised when a RenderVet contract is invalid."""


@dataclass(frozen=True)
class ProjectConfig:
    name: str
    root: Path
    report_dir: Path
    fresh_after: Optional[datetime] = None


@dataclass(frozen=True)
class BatchConfig:
    id: str
    glob: str
    kind: str = "auto"
    expected_count: Optional[int] = None
    sequence_regex: Optional[str] = None
    sequence_start: Optional[int] = None
    sequence_end: Optional[int] = None
    allowed_extensions: Sequence[str] = field(default_factory=tuple)
    min_bytes: int = 1
    max_bytes: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    min_duration: Optional[float] = None
    max_duration: Optional[float] = None
    require_audio: bool = False
    duplicates: str = "error"
    fresh_after: Optional[datetime] = None

    @property
    def compiled_sequence_regex(self) -> Optional[re.Pattern[str]]:
        if not self.sequence_regex:
            return None
        return re.compile(self.sequence_regex)


@dataclass(frozen=True)
class Contract:
    version: int
    config_path: Path
    project: ProjectConfig
    batches: Sequence[BatchConfig]


def _parse_datetime(value: Any, field_name: str) -> Optional[datetime]:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ConfigError(f"{field_name} must be an ISO-8601 string")
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ConfigError(f"{field_name} is not valid ISO-8601: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _positive_int(value: Any, field_name: str, *, allow_zero: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{field_name} must be an integer")
    minimum = 0 if allow_zero else 1
    if value < minimum:
        raise ConfigError(f"{field_name} must be >= {minimum}")
    return value


def _optional_positive_int(value: Any, field_name: str) -> Optional[int]:
    if value is None:
        return None
    return _positive_int(value, field_name)


def _optional_nonnegative_int(value: Any, field_name: str) -> Optional[int]:
    if value is None:
        return None
    return _positive_int(value, field_name, allow_zero=True)


def _optional_float(value: Any, field_name: str) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{field_name} must be a number")
    if value < 0:
        raise ConfigError(f"{field_name} must be >= 0")
    return float(value)


def _absolute_from_config(config_path: Path, value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = config_path.parent / path
    return Path(os.path.abspath(os.fspath(path)))


def _resolve_from_config(config_path: Path, value: str) -> Path:
    return _absolute_from_config(config_path, value).resolve()


def _normalize_extensions(value: Any, field_name: str) -> Sequence[str]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"{field_name} must be an array of strings")
    extensions: List[str] = []
    for item in value:
        extension = item.strip().lower()
        if not extension:
            raise ConfigError(f"{field_name} contains an empty extension")
        if not extension.startswith("."):
            extension = f".{extension}"
        extensions.append(extension)
    return tuple(dict.fromkeys(extensions))


def _reject_unknown(raw: Dict[str, Any], allowed: Sequence[str], location: str) -> None:
    unknown = sorted(set(raw) - set(allowed))
    if unknown:
        raise ConfigError(f"unknown {location} key(s): {', '.join(unknown)}")


def _parse_batch(
    raw: Dict[str, Any],
    index: int,
    project_fresh_after: Optional[datetime],
) -> BatchConfig:
    prefix = f"batch[{index}]"
    _reject_unknown(
        raw,
        (
            "id",
            "glob",
            "kind",
            "expected_count",
            "sequence_regex",
            "sequence_start",
            "sequence_end",
            "allowed_extensions",
            "min_bytes",
            "max_bytes",
            "width",
            "height",
            "min_duration",
            "max_duration",
            "require_audio",
            "duplicates",
            "fresh_after",
        ),
        prefix,
    )
    batch_id = raw.get("id")
    pattern = raw.get("glob")
    if not isinstance(batch_id, str) or not batch_id.strip():
        raise ConfigError(f"{prefix}.id must be a non-empty string")
    if not isinstance(pattern, str) or not pattern.strip():
        raise ConfigError(f"{prefix}.glob must be a non-empty string")
    pattern_path = Path(pattern)
    if pattern_path.is_absolute() or ".." in pattern_path.parts:
        raise ConfigError(f"{prefix}.glob must stay inside project.root")

    kind = raw.get("kind", "auto")
    if kind not in {"auto", "image", "audio", "video", "file"}:
        raise ConfigError(f"{prefix}.kind must be auto, image, audio, video, or file")

    duplicates = raw.get("duplicates", "error")
    if duplicates not in {"error", "warning", "ignore"}:
        raise ConfigError(f"{prefix}.duplicates must be error, warning, or ignore")

    sequence_regex = raw.get("sequence_regex")
    if sequence_regex is not None:
        if not isinstance(sequence_regex, str) or not sequence_regex:
            raise ConfigError(f"{prefix}.sequence_regex must be a non-empty string")
        try:
            compiled = re.compile(sequence_regex)
        except re.error as exc:
            raise ConfigError(f"{prefix}.sequence_regex is invalid: {exc}") from exc
        if compiled.groups < 1:
            raise ConfigError(f"{prefix}.sequence_regex must contain a capture group")

    sequence_start = _optional_nonnegative_int(
        raw.get("sequence_start"), f"{prefix}.sequence_start"
    )
    sequence_end = _optional_nonnegative_int(raw.get("sequence_end"), f"{prefix}.sequence_end")
    if (sequence_start is None) != (sequence_end is None):
        raise ConfigError(f"{prefix} must set both sequence_start and sequence_end")
    if sequence_start is not None and sequence_end is not None:
        if sequence_end < sequence_start:
            raise ConfigError(f"{prefix}.sequence_end must be >= sequence_start")
        if not sequence_regex:
            raise ConfigError(f"{prefix} needs sequence_regex when sequence bounds are set")

    expected_count = _optional_positive_int(raw.get("expected_count"), f"{prefix}.expected_count")
    min_bytes = _positive_int(raw.get("min_bytes", 1), f"{prefix}.min_bytes", allow_zero=True)
    max_bytes = _optional_positive_int(raw.get("max_bytes"), f"{prefix}.max_bytes")
    if max_bytes is not None and max_bytes < min_bytes:
        raise ConfigError(f"{prefix}.max_bytes must be >= min_bytes")

    min_duration = _optional_float(raw.get("min_duration"), f"{prefix}.min_duration")
    max_duration = _optional_float(raw.get("max_duration"), f"{prefix}.max_duration")
    if min_duration is not None and max_duration is not None and max_duration < min_duration:
        raise ConfigError(f"{prefix}.max_duration must be >= min_duration")

    fresh_after = _parse_datetime(raw.get("fresh_after"), f"{prefix}.fresh_after")
    require_audio = raw.get("require_audio", False)
    if not isinstance(require_audio, bool):
        raise ConfigError(f"{prefix}.require_audio must be true or false")
    return BatchConfig(
        id=batch_id.strip(),
        glob=pattern.strip(),
        kind=kind,
        expected_count=expected_count,
        sequence_regex=sequence_regex,
        sequence_start=sequence_start,
        sequence_end=sequence_end,
        allowed_extensions=_normalize_extensions(
            raw.get("allowed_extensions"), f"{prefix}.allowed_extensions"
        ),
        min_bytes=min_bytes,
        max_bytes=max_bytes,
        width=_optional_positive_int(raw.get("width"), f"{prefix}.width"),
        height=_optional_positive_int(raw.get("height"), f"{prefix}.height"),
        min_duration=min_duration,
        max_duration=max_duration,
        require_audio=require_audio,
        duplicates=duplicates,
        fresh_after=fresh_after or project_fresh_after,
    )


def load_contract(path: Path) -> Contract:
    config_path = path.expanduser().resolve()
    if not config_path.is_file():
        raise ConfigError(f"contract not found: {config_path}")
    try:
        with config_path.open("rb") as handle:
            raw = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"cannot read contract: {exc}") from exc

    _reject_unknown(raw, ("version", "project", "batch"), "top-level")
    version = raw.get("version")
    if version != 1:
        raise ConfigError("version must be 1")

    project_raw = raw.get("project")
    if not isinstance(project_raw, dict):
        raise ConfigError("[project] table is required")
    _reject_unknown(
        project_raw,
        ("name", "root", "report_dir", "fresh_after"),
        "project",
    )
    name = project_raw.get("name")
    root = project_raw.get("root", ".")
    report_dir = project_raw.get("report_dir", ".rendervet")
    if not isinstance(name, str) or not name.strip():
        raise ConfigError("project.name must be a non-empty string")
    if not isinstance(root, str) or not root.strip():
        raise ConfigError("project.root must be a non-empty string")
    if not isinstance(report_dir, str) or not report_dir.strip():
        raise ConfigError("project.report_dir must be a non-empty string")

    fresh_after = _parse_datetime(project_raw.get("fresh_after"), "project.fresh_after")
    resolved_root = _resolve_from_config(config_path, root)
    absolute_report_dir = _absolute_from_config(config_path, report_dir)
    if absolute_report_dir == resolved_root:
        raise ConfigError("project.report_dir must not equal project.root")
    project = ProjectConfig(
        name=name.strip(),
        root=resolved_root,
        report_dir=absolute_report_dir,
        fresh_after=fresh_after,
    )

    batches_raw = raw.get("batch")
    if not isinstance(batches_raw, list) or not batches_raw:
        raise ConfigError("at least one [[batch]] table is required")
    batches = tuple(
        _parse_batch(item, index, fresh_after) for index, item in enumerate(batches_raw)
    )
    ids = [batch.id for batch in batches]
    if len(ids) != len(set(ids)):
        raise ConfigError("batch ids must be unique")
    return Contract(version=version, config_path=config_path, project=project, batches=batches)
