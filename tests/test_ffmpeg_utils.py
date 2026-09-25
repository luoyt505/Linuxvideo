"""ffmpeg / ffprobe 工具层单元测试。

不依赖系统安装 ffmpeg：无法执行时自动跳过需要真实二进制的用例。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.utils import ffmpeg_utils


def _ffmpeg_present() -> bool:
    return ffmpeg_utils.ffmpeg_available() and ffmpeg_utils.ffprobe_available()


def test_classify_by_extension():
    assert ffmpeg_utils.classify("movie.MP4") == "video"
    assert ffmpeg_utils.classify(Path("/data/song.flac")) == "audio"
    assert ffmpeg_utils.classify(Path("/data/pic.webp")) == "image"
    assert ffmpeg_utils.classify(Path("/data/readme.md")) is None


def test_is_media():
    assert ffmpeg_utils.is_media("clip.mp4") is True
    assert ffmpeg_utils.is_media("clip.txt") is False


def test_parse_progress_line():
    line = "frame=  120 fps= 30 q=28.0 size=    1024kB time=00:00:12.34 bitrate= 680.1kbits/s speed=1.2x"
    seconds = ffmpeg_utils.parse_time_from_line(line)
    assert seconds == pytest.approx(12.34, abs=0.01)

    assert ffmpeg_utils.parse_time_from_line("frame=1 fps=0.0 q=0.0 size=0kB time=N/A") is None
    assert ffmpeg_utils.parse_time_from_line("无关内容") is None


def test_percent_from_time():
    assert ffmpeg_utils.percent_from_time(0, 100) == 0
    assert ffmpeg_utils.percent_from_time(50, 100) == 50
    assert ffmpeg_utils.percent_from_time(200, 100) == 100
    assert ffmpeg_utils.percent_from_time(10, 0) == 0


def test_human_helpers():
    from app.services import library

    assert library.human_size(0) == "0 B"
    assert library.human_size(1024) == "1.00 KB"
    assert library.human_size(1024 ** 3) == "1.00 GB"
    assert library.human_duration(65) == "1m 5s"
    assert library.human_duration(3661) == "1h 1m 1s"


def test_build_transcode_cmd(tmp_path):
    source = tmp_path / "in.mp4"
    target = tmp_path / "out.mp4"
    cmd = ffmpeg_utils.build_transcode_cmd(
        source, target, vcodec="libx264", acodec="aac", crf=20, preset="fast",
        scale="1280:-2", audio_bitrate="128k",
    )
    from app.config import settings

    assert cmd[0] == settings.ffmpeg_bin
    assert "-progress" not in cmd          # -progress 由 run_ffmpeg 在执行时统一追加
    assert cmd[cmd.index("-crf") + 1] == "20"
    assert cmd[cmd.index("-preset") + 1] == "fast"
    assert cmd[-1] == str(target)
    assert cmd[cmd.index("-i") + 1] == str(source)


def test_build_extract_audio_cmd(tmp_path):
    cmd = ffmpeg_utils.build_extract_audio_cmd(tmp_path / "in.mp4", tmp_path / "out.mp3")
    assert "-vn" in cmd
    assert cmd[cmd.index("-c:a") + 1] == "libmp3lame"


@pytest.mark.skipif(not _ffmpeg_present(), reason="系统未安装 ffmpeg/ffprobe")
def test_probe_and_generate(tmp_path):
    """真实调用 ffmpeg 生成测试素材，再探测元数据与生成封面。"""
    # 生成 2 秒测试视频
    sample = tmp_path / "sample.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=15",
         "-t", "2", "-pix_fmt", "yuv420p", str(sample)],
        check=True, capture_output=True,
    )

    info = ffmpeg_utils.probe_info(sample)
    assert info["media_type"] == "video"
    assert info["duration"] > 0
    assert info["width"] == 320
    assert info["height"] == 240

    thumb = tmp_path / "thumb.jpg"
    result = ffmpeg_utils.generate_thumbnail(sample, thumb, at=1, width=160)
    assert Path(result) == thumb
    assert thumb.exists() and thumb.stat().st_size > 0


@pytest.mark.skipif(not _ffmpeg_present(), reason="系统未安装 ffmpeg/ffprobe")
def test_transcode_real(tmp_path):
    sample = tmp_path / "src.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10",
         "-t", "1", "-pix_fmt", "yuv420p", str(sample)],
        check=True, capture_output=True,
    )
    target = tmp_path / "dst.mp4"
    progress = []
    ffmpeg_utils.transcode(sample, target, duration=1.0, on_progress=progress.append)
    assert target.exists() and target.stat().st_size > 0
    assert progress, "应至少收到一次进度回调"
