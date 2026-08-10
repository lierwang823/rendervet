"""Deterministic media probes with no network access or file mutation."""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
import zlib
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from rendervet.models import MediaInfo

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}


class MediaProbeError(ValueError):
    """Raised when a media file is malformed or cannot be inspected."""


def classify_extension(path: Path) -> str:
    extension = path.suffix.lower()
    if extension in IMAGE_EXTENSIONS:
        return "image"
    if extension in VIDEO_EXTENSIONS:
        return "video"
    if extension in AUDIO_EXTENSIONS:
        return "audio"
    return "file"


def _probe_png(path: Path) -> Tuple[int, int]:
    signature = b"\x89PNG\r\n\x1a\n"
    with path.open("rb") as handle:
        if handle.read(8) != signature:
            raise MediaProbeError("invalid PNG signature")
        width: Optional[int] = None
        height: Optional[int] = None
        saw_end = False
        while True:
            length_bytes = handle.read(4)
            if not length_bytes:
                break
            if len(length_bytes) != 4:
                raise MediaProbeError("truncated PNG chunk length")
            length = struct.unpack(">I", length_bytes)[0]
            chunk_type = handle.read(4)
            chunk_data = handle.read(length)
            crc_bytes = handle.read(4)
            if len(chunk_type) != 4 or len(chunk_data) != length or len(crc_bytes) != 4:
                raise MediaProbeError("truncated PNG chunk")
            expected_crc = struct.unpack(">I", crc_bytes)[0]
            actual_crc = zlib.crc32(chunk_type)
            actual_crc = zlib.crc32(chunk_data, actual_crc) & 0xFFFFFFFF
            if actual_crc != expected_crc:
                chunk_name = chunk_type.decode("ascii", "replace")
                raise MediaProbeError(f"PNG CRC mismatch in {chunk_name}")
            if chunk_type == b"IHDR":
                if length != 13:
                    raise MediaProbeError("invalid PNG IHDR")
                width, height = struct.unpack(">II", chunk_data[:8])
                if width <= 0 or height <= 0:
                    raise MediaProbeError("invalid PNG dimensions")
            elif chunk_type == b"IEND":
                saw_end = True
                break
        if width is None or height is None:
            raise MediaProbeError("PNG has no IHDR")
        if not saw_end:
            raise MediaProbeError("PNG has no IEND")
        return width, height


def _probe_jpeg(path: Path) -> Tuple[int, int]:
    data = path.read_bytes()
    if len(data) < 4 or not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
        raise MediaProbeError("invalid or truncated JPEG")
    offset = 2
    sof_markers = {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
    while offset < len(data) - 1:
        if data[offset] != 0xFF:
            offset += 1
            continue
        while offset < len(data) and data[offset] == 0xFF:
            offset += 1
        if offset >= len(data):
            break
        marker = data[offset]
        offset += 1
        if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            continue
        if offset + 2 > len(data):
            break
        segment_length = struct.unpack(">H", data[offset : offset + 2])[0]
        if segment_length < 2 or offset + segment_length > len(data):
            raise MediaProbeError("truncated JPEG segment")
        if marker in sof_markers:
            if segment_length < 7:
                raise MediaProbeError("invalid JPEG SOF segment")
            height, width = struct.unpack(">HH", data[offset + 3 : offset + 7])
            if width <= 0 or height <= 0:
                raise MediaProbeError("invalid JPEG dimensions")
            return width, height
        offset += segment_length
    raise MediaProbeError("JPEG dimensions not found")


def _probe_gif(path: Path) -> Tuple[int, int]:
    data = path.read_bytes()
    if len(data) < 14 or data[:6] not in {b"GIF87a", b"GIF89a"} or data[-1:] != b";":
        raise MediaProbeError("invalid or truncated GIF")
    width, height = struct.unpack("<HH", data[6:10])
    if width <= 0 or height <= 0:
        raise MediaProbeError("invalid GIF dimensions")
    return width, height


def _probe_bmp(path: Path) -> Tuple[int, int]:
    data = path.read_bytes()[:32]
    if len(data) < 26 or data[:2] != b"BM":
        raise MediaProbeError("invalid BMP header")
    width, height = struct.unpack("<ii", data[18:26])
    if width <= 0 or height == 0:
        raise MediaProbeError("invalid BMP dimensions")
    return width, abs(height)


def _probe_webp(path: Path) -> Tuple[int, int]:
    data = path.read_bytes()[:64]
    if len(data) < 30 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise MediaProbeError("invalid WebP header")
    chunk = data[12:16]
    if chunk == b"VP8X":
        width = 1 + int.from_bytes(data[24:27], "little")
        height = 1 + int.from_bytes(data[27:30], "little")
        return width, height
    if chunk == b"VP8L":
        if data[20] != 0x2F:
            raise MediaProbeError("invalid lossless WebP header")
        bits = int.from_bytes(data[21:25], "little")
        width = (bits & 0x3FFF) + 1
        height = ((bits >> 14) & 0x3FFF) + 1
        return width, height
    if chunk == b"VP8 ":
        marker = data.find(b"\x9d\x01\x2a", 20)
        if marker < 0 or marker + 7 > len(data):
            raise MediaProbeError("invalid lossy WebP header")
        width, height = struct.unpack("<HH", data[marker + 3 : marker + 7])
        return width & 0x3FFF, height & 0x3FFF
    raise MediaProbeError("unsupported WebP chunk")


def probe_image(path: Path) -> MediaInfo:
    extension = path.suffix.lower()
    probes = {
        ".png": ("png", _probe_png),
        ".jpg": ("jpeg", _probe_jpeg),
        ".jpeg": ("jpeg", _probe_jpeg),
        ".gif": ("gif", _probe_gif),
        ".webp": ("webp", _probe_webp),
        ".bmp": ("bmp", _probe_bmp),
    }
    selected = probes.get(extension)
    if selected is None:
        raise MediaProbeError(f"unsupported image extension: {extension or '(none)'}")
    format_name, probe = selected
    try:
        width, height = probe(path)
    except OSError as exc:
        raise MediaProbeError("image file could not be read") from exc
    return MediaInfo(kind="image", format=format_name, width=width, height=height, probe="native")


def _parse_frame_rate(value: Any) -> Optional[float]:
    if not isinstance(value, str) or value in {"", "0/0"}:
        return None
    try:
        numerator, denominator = value.split("/", 1)
        if float(denominator) == 0:
            return None
        return float(numerator) / float(denominator)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def find_ffprobe() -> Optional[str]:
    return shutil.which("ffprobe")


def probe_av(path: Path, ffprobe: Optional[str] = None) -> MediaInfo:
    executable = ffprobe or find_ffprobe()
    if executable is None:
        raise MediaProbeError("ffprobe is required for audio/video checks")
    command = [
        executable,
        "-v",
        "error",
        "-show_streams",
        "-show_format",
        "-of",
        "json",
        str(path),
    ]
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaProbeError("ffprobe timed out after 30 seconds") from exc
    except OSError as exc:
        raise MediaProbeError("ffprobe could not be started") from exc
    if completed.returncode != 0:
        raise MediaProbeError(f"ffprobe rejected the media file (exit code {completed.returncode})")
    try:
        payload: Dict[str, Any] = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise MediaProbeError("ffprobe returned invalid JSON") from exc

    streams = payload.get("streams", [])
    if not isinstance(streams, list):
        raise MediaProbeError("ffprobe returned invalid streams")
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    if video_stream is None and audio_stream is None:
        raise MediaProbeError("no audio or video stream found")

    format_data = payload.get("format", {})
    duration_value = format_data.get("duration")
    try:
        duration = float(duration_value) if duration_value is not None else None
    except (TypeError, ValueError):
        duration = None
    if duration is None:
        stream_duration = (video_stream or audio_stream or {}).get("duration")
        try:
            duration = float(stream_duration) if stream_duration is not None else None
        except (TypeError, ValueError):
            duration = None

    kind = "video" if video_stream is not None else "audio"
    return MediaInfo(
        kind=kind,
        format=format_data.get("format_name"),
        width=video_stream.get("width") if video_stream else None,
        height=video_stream.get("height") if video_stream else None,
        duration=duration,
        frame_rate=_parse_frame_rate(video_stream.get("avg_frame_rate")) if video_stream else None,
        video_codec=video_stream.get("codec_name") if video_stream else None,
        audio_codec=audio_stream.get("codec_name") if audio_stream else None,
        has_audio=audio_stream is not None,
        probe="ffprobe",
    )


def probe_media(path: Path, requested_kind: str = "auto") -> MediaInfo:
    inferred_kind = classify_extension(path)
    kind = inferred_kind if requested_kind == "auto" else requested_kind
    if kind == "image":
        return probe_image(path)
    if kind in {"audio", "video"}:
        return probe_av(path)
    return MediaInfo(kind=inferred_kind, format=path.suffix.lower().lstrip("."), probe="none")
