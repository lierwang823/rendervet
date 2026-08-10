from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from rendervet.demo import png_bytes
from rendervet.media import MediaProbeError, probe_av, probe_image


def test_native_png_probe_validates_dimensions_and_crc(tmp_path: Path) -> None:
    path = tmp_path / "image.png"
    path.write_bytes(png_bytes(23, 17, (10, 20, 30)))
    media = probe_image(path)
    assert media.kind == "image"
    assert media.format == "png"
    assert (media.width, media.height) == (23, 17)


def test_native_png_probe_rejects_corrupt_crc(tmp_path: Path) -> None:
    path = tmp_path / "image.png"
    payload = bytearray(png_bytes(8, 8, (10, 20, 30)))
    payload[-5] ^= 1
    path.write_bytes(payload)
    with pytest.raises(MediaProbeError, match="CRC mismatch"):
        probe_image(path)


def test_ffprobe_json_is_normalized(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    payload = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1080,
                "height": 1920,
                "avg_frame_rate": "30000/1001",
            },
            {"codec_type": "audio", "codec_name": "aac"},
        ],
        "format": {"format_name": "mov,mp4", "duration": "12.5"},
    }

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(payload), stderr=""
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    media = probe_av(tmp_path / "clip.mp4", ffprobe="/usr/bin/ffprobe")
    assert media.kind == "video"
    assert media.has_audio is True
    assert media.duration == 12.5
    assert media.frame_rate == pytest.approx(29.970, abs=0.001)


def test_ffprobe_failure_becomes_probe_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="Invalid data found"
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(MediaProbeError, match="rejected the media file") as error:
        probe_av(tmp_path / "clip.mp4", ffprobe="/usr/bin/ffprobe")
    assert str(tmp_path) not in str(error.value)
    assert "Invalid data found" not in str(error.value)


def test_probe_errors_do_not_expose_absolute_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    image_path = tmp_path / "private-image.png"

    def deny_read(path: Path) -> tuple[int, int]:
        raise PermissionError(f"permission denied: {path}")

    monkeypatch.setattr("rendervet.media._probe_png", deny_read)
    with pytest.raises(MediaProbeError, match="could not be read") as image_error:
        probe_image(image_path)
    assert str(tmp_path) not in str(image_error.value)

    def deny_start(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise OSError(f"cannot execute for {tmp_path / 'private-video.mp4'}")

    monkeypatch.setattr(subprocess, "run", deny_start)
    with pytest.raises(MediaProbeError, match="could not be started") as video_error:
        probe_av(tmp_path / "private-video.mp4", ffprobe="/usr/bin/ffprobe")
    assert str(tmp_path) not in str(video_error.value)
