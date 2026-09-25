"""ffmpeg / ffprobe 封装。

对外提供：
- 媒体类型判定与探测（``probe`` / ``probe_info``）
- 封面生成（``generate_thumbnail``）
- 转码（``transcode``）、抽音轨（``extract_audio``）、截图（``capture_frame``）
- 带进度回调与取消检查的命令执行（``run_ffmpeg``）
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from app.config import settings

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# 扩展名分类
# --------------------------------------------------------------------------- #
VIDEO_EXTS = {
    ".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".webm", ".m4v",
    ".mpg", ".mpeg", ".ts", ".m2ts", ".3gp", ".rmvb", ".vob", ".ogv",
}
AUDIO_EXTS = {
    ".mp3", ".flac", ".wav", ".aac", ".m4a", ".ogg", ".oga", ".wma",
    ".opus", ".ape", ".alac", ".aiff", ".aif", ".amr",
}
IMAGE_EXTS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif", ".heic",
}
MEDIA_EXTS = VIDEO_EXTS | AUDIO_EXTS | IMAGE_EXTS

_YEAR_RE = re.compile(r"(19|20)\d{2}")

# 所有 ffmpeg 调用共用的全局参数（-progress 输出机器可读的进度行）
GLOBAL_ARGS = ["-hide_banner", "-nostats", "-progress", "pipe:1", "-loglevel", "error"]


class TaskCancelled(Exception):
    """任务被用户取消时抛出。"""


# --------------------------------------------------------------------------- #
# 基础判定
# --------------------------------------------------------------------------- #
def classify(path: Any) -> Optional[str]:
    """按扩展名返回 ``video`` / ``audio`` / ``image``，非媒体返回 ``None``。"""
    ext = Path(str(path)).suffix.lower()
    if ext in VIDEO_EXTS:
        return "video"
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in IMAGE_EXTS:
        return "image"
    return None


def is_media(path: Any) -> bool:
    return classify(path) is not None


def ffmpeg_available() -> bool:
    return shutil.which(settings.ffmpeg_bin) is not None


def ffprobe_available() -> bool:
    return shutil.which(settings.ffprobe_bin) is not None


def _run(cmd: List[str], timeout: float = 120) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def get_tool_versions() -> Dict[str, Dict[str, Any]]:
    """返回 ffmpeg / ffprobe 的可用性与版本号。"""
    info: Dict[str, Dict[str, Any]] = {
        "ffmpeg": {"available": False, "version": None},
        "ffprobe": {"available": False, "version": None},
    }
    for key, binary, flag in (
        ("ffmpeg", settings.ffmpeg_bin, ffmpeg_available),
        ("ffprobe", settings.ffprobe_bin, ffprobe_available),
    ):
        if not flag():
            continue
        try:
            result = _run([binary, "-version"], timeout=15)
            first_line = (result.stdout or "").splitlines()
            info[key] = {
                "available": True,
                "version": first_line[0].strip() if first_line else "unknown",
                "path": shutil.which(binary),
            }
        except Exception as exc:  # pragma: no cover - 环境相关
            info[key] = {"available": True, "version": f"unknown ({exc})"}
    return info


# --------------------------------------------------------------------------- #
# 数值 / 时间解析
# --------------------------------------------------------------------------- #
def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, "", "N/A"):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, "", "N/A"):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def parse_fraction(value: Any) -> float:
    """把 ``"30000/1001"`` 这类分数字符串解析为浮点数。"""
    if not value:
        return 0.0
    text = str(value)
    if "/" in text:
        numerator, _, denominator = text.partition("/")
        try:
            den = float(denominator)
            return float(numerator) / den if den else 0.0
        except ValueError:
            return 0.0
    return _safe_float(text)


def _parse_timecode(text: str) -> Optional[float]:
    """把 ``"00:01:23.456"`` 解析为秒。"""
    parts = str(text).split(":")
    if len(parts) != 3:
        return None
    try:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except ValueError:
        return None


_TIME_IN_LINE_RE = re.compile(r"time=(\d{1,3}:\d{2}:\d{2}(?:\.\d+)?)")


def parse_time_from_line(text: str) -> Optional[float]:
    """从 ffmpeg 输出行中解析 ``time=HH:MM:SS.xx``；未命中或为 ``N/A`` 时返回 ``None``。"""
    if not text:
        return None
    match = _TIME_IN_LINE_RE.search(str(text))
    if not match:
        return None
    return _parse_timecode(match.group(1))


def percent_from_time(current: float, total: float) -> int:
    """把已处理时长换算成 0~100 的整数百分比（``total`` 未知时返回 0）。"""
    try:
        current_value = float(current)
        total_value = float(total)
    except (TypeError, ValueError):
        return 0
    if total_value <= 0:
        return 0
    return max(0, min(100, int(current_value / total_value * 100)))


def extract_year(data: Dict[str, Any], path: Any) -> Optional[int]:
    """从元数据标签或文件名中提取年份。"""
    fmt_tags = (data.get("format") or {}).get("tags") or {}
    for key in ("creation_time", "date", "year", "DATE", "com.apple.quicktime.creationdate"):
        value = fmt_tags.get(key)
        if value:
            match = _YEAR_RE.search(str(value))
            if match:
                return int(match.group(0))
    for stream in data.get("streams") or []:
        tags = stream.get("tags") or {}
        for key in ("creation_time", "date"):
            value = tags.get(key)
            if value:
                match = _YEAR_RE.search(str(value))
                if match:
                    return int(match.group(0))
    match = _YEAR_RE.search(Path(str(path)).stem)
    return int(match.group(0)) if match else None


# --------------------------------------------------------------------------- #
# ffprobe
# --------------------------------------------------------------------------- #
def probe(path: Any) -> Dict[str, Any]:
    """调用 ffprobe 返回原始 JSON。"""
    if not ffprobe_available():
        raise RuntimeError("未找到 ffprobe，请先安装 ffmpeg（sudo apt install -y ffmpeg）")
    cmd = [
        settings.ffprobe_bin,
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    result = _run(cmd, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe 探测失败：{(result.stderr or '').strip()[:300]}")
    try:
        return json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ffprobe 输出解析失败：{exc}") from exc


def parse_probe(data: Dict[str, Any], path: Any) -> Dict[str, Any]:
    """把 ffprobe 原始输出规范化为入库字段。"""
    fmt = data.get("format") or {}
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    file_path = Path(str(path))

    media_type = classify(file_path) or ("video" if video else "audio" if audio else "other")

    duration = _safe_float(fmt.get("duration"))
    if not duration and video is not None:
        duration = _safe_float(video.get("duration"))
    if not duration and audio is not None:
        duration = _safe_float(audio.get("duration"))
    if media_type == "image":
        duration = 0.0

    tags = fmt.get("tags") or {}
    return {
        "media_type": media_type,
        "container": fmt.get("format_name") or file_path.suffix.lstrip(".").lower() or None,
        "duration": round(duration, 3),
        "size": _safe_int(fmt.get("size")),
        "bit_rate": _safe_int(fmt.get("bit_rate")),
        "width": _safe_int(video.get("width")) if video else 0,
        "height": _safe_int(video.get("height")) if video else 0,
        "video_codec": (video or {}).get("codec_name"),
        "audio_codec": (audio or {}).get("codec_name"),
        "frame_rate": round(
            parse_fraction((video or {}).get("avg_frame_rate") or (video or {}).get("r_frame_rate")), 3
        ) if video else 0.0,
        "sample_rate": _safe_int((audio or {}).get("sample_rate")) if audio else 0,
        "channels": _safe_int((audio or {}).get("channels")) if audio else 0,
        "stream_count": len(streams),
        "subtitle_count": len([s for s in streams if s.get("codec_type") == "subtitle"]),
        "year": extract_year(data, file_path),
        "title": tags.get("title") or file_path.stem,
        "streams": [
            {
                "index": s.get("index"),
                "codec_type": s.get("codec_type"),
                "codec_name": s.get("codec_name"),
                "width": s.get("width"),
                "height": s.get("height"),
                "sample_rate": s.get("sample_rate"),
                "channels": s.get("channels"),
                "bit_rate": _safe_int(s.get("bit_rate")),
                "language": (s.get("tags") or {}).get("language"),
            }
            for s in streams
        ],
    }


def probe_info(path: Any) -> Dict[str, Any]:
    """探测并规范化，一步到位。"""
    return parse_probe(probe(path), path)


# --------------------------------------------------------------------------- #
# 命令执行（带进度 / 取消）
# --------------------------------------------------------------------------- #
def run_ffmpeg(
    cmd: List[str],
    duration: float = 0.0,
    on_progress: Optional[Callable[[int], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    timeout: Optional[float] = None,
) -> None:
    """执行 ffmpeg 命令，解析 ``-progress`` 输出回调百分比进度。

    :raises TaskCancelled: 当 ``cancel_check()`` 返回 True
    :raises RuntimeError:  ffmpeg 返回非零码或超时
    """
    if not ffmpeg_available():
        raise RuntimeError("未找到 ffmpeg，请先安装 ffmpeg（sudo apt install -y ffmpeg）")

    full_cmd = [cmd[0], "-hide_banner", "-nostats", "-loglevel", "error",
                "-progress", "pipe:1"] + list(cmd[1:])
    logger.debug("执行 ffmpeg：%s", " ".join(full_cmd))

    process = subprocess.Popen(
        full_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    stderr_chunks: List[str] = []

    def _drain_stderr() -> None:
        if process.stderr is None:
            return
        for line in process.stderr:
            stderr_chunks.append(line)

    drain_thread = threading.Thread(target=_drain_stderr, daemon=True)
    drain_thread.start()

    last_reported = -1
    try:
        if process.stdout is not None:
            for raw_line in process.stdout:
                line = raw_line.strip()
                if cancel_check is not None and cancel_check():
                    process.kill()
                    raise TaskCancelled("任务已取消")
                if line.startswith("out_time="):
                    seconds = _parse_timecode(line.split("=", 1)[1])
                    if seconds is not None and duration > 0 and on_progress is not None:
                        percent = max(0, min(99, int(seconds / duration * 100)))
                        if percent != last_reported:
                            last_reported = percent
                            on_progress(percent)
        process.wait(timeout=timeout or 3600)
    except TaskCancelled:
        raise
    except subprocess.TimeoutExpired as exc:
        process.kill()
        raise RuntimeError("ffmpeg 执行超时") from exc
    finally:
        if process.poll() is None:
            process.kill()
        drain_thread.join(timeout=5)

    if process.returncode != 0:
        stderr_text = "".join(stderr_chunks).strip()
        raise RuntimeError(f"ffmpeg 执行失败（code={process.returncode}）：{stderr_text[:500]}")

    if on_progress is not None:
        on_progress(100)


# --------------------------------------------------------------------------- #
# 缩略图 / 截图
# --------------------------------------------------------------------------- #
def thumbnail_path_for(media_id: int) -> Path:
    return settings.cache_dir / "thumbnails" / f"{media_id}.jpg"


def capture_frame(src: Any, dest: Any, at: Optional[float] = None, width: Optional[int] = None) -> Path:
    """在指定时间点截取一帧，输出图片。"""
    src_path = Path(src)
    dest_path = Path(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    seek = 0.0 if at is None else max(0.0, float(at))

    args = [
        settings.ffmpeg_bin, "-y",
        "-ss", f"{seek}",
        "-i", str(src_path),
        "-frames:v", "1",
        "-q:v", "2",
    ]
    if width:
        args += ["-vf", f"scale={int(width)}:-1"]
    args.append(str(dest_path))

    result = _run(args, timeout=120)
    if result.returncode != 0 or not dest_path.exists():
        raise RuntimeError(f"截图失败：{(result.stderr or '').strip()[:300]}")
    return dest_path


def generate_thumbnail(src: Any, dest: Any, at: Optional[float] = None,
                       width: Optional[int] = None) -> Path:
    """生成封面；若指定时间点超出时长则回退到第 0 秒。"""
    seek = 3.0 if at is None else float(at)
    target_width = width or settings.thumbnail_width
    try:
        return capture_frame(src, dest, at=seek, width=target_width)
    except RuntimeError:
        if seek > 0:
            return capture_frame(src, dest, at=0.0, width=target_width)
        raise


# --------------------------------------------------------------------------- #
# 转码 / 抽音轨
# --------------------------------------------------------------------------- #
def build_transcode_cmd(
    src: Any,
    dest: Any,
    vcodec: str = "libx264",
    acodec: str = "aac",
    crf: Optional[int] = None,
    preset: Optional[str] = None,
    scale: Optional[str] = None,
    audio_bitrate: str = "192k",
    extra_args: Optional[List[str]] = None,
) -> List[str]:
    """构造转码命令（``-progress`` 等全局参数由 :func:`run_ffmpeg` 自动追加，此处不含）。"""
    quality = settings.default_transcode_crf if crf is None else int(crf)
    encoder_preset = preset or settings.default_transcode_preset

    args: List[str] = [settings.ffmpeg_bin, "-y", "-i", str(Path(src))]

    if vcodec == "copy":
        args += ["-c:v", "copy"]
    else:
        args += ["-c:v", vcodec]
        if vcodec in ("libx264", "libx265", "libvpx-vp9", "libsvtav1"):
            args += ["-preset", encoder_preset, "-crf", str(quality)]
        else:
            args += ["-crf", str(quality)]

    if scale:
        args += ["-vf", f"scale={scale}"]

    if acodec == "copy":
        args += ["-c:a", "copy"]
    else:
        args += ["-c:a", acodec, "-b:a", audio_bitrate]

    dest_path = Path(dest)
    if dest_path.suffix.lower() in (".mp4", ".m4v", ".mov"):
        args += ["-movflags", "+faststart"]

    if extra_args:
        args += [str(item) for item in extra_args]

    args.append(str(dest_path))
    return args


def build_extract_audio_cmd(
    src: Any,
    dest: Any,
    acodec: str = "libmp3lame",
    bitrate: str = "192k",
    extra_args: Optional[List[str]] = None,
) -> List[str]:
    """构造抽音轨命令（``-progress`` 等全局参数由 :func:`run_ffmpeg` 自动追加，此处不含）。"""
    args: List[str] = [settings.ffmpeg_bin, "-y", "-i", str(Path(src)), "-vn"]
    if acodec == "copy":
        args += ["-c:a", "copy"]
    else:
        args += ["-c:a", acodec, "-b:a", bitrate]
    if extra_args:
        args += [str(item) for item in extra_args]
    args.append(str(Path(dest)))
    return args


def transcode(
    src: Any,
    dest: Any,
    vcodec: str = "libx264",
    acodec: str = "aac",
    crf: Optional[int] = None,
    preset: Optional[str] = None,
    scale: Optional[str] = None,
    audio_bitrate: str = "192k",
    duration: float = 0.0,
    on_progress: Optional[Callable[[int], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    extra_args: Optional[List[str]] = None,
) -> Path:
    """转码视频 / 音频文件。``vcodec`` / ``acodec`` 为 ``copy`` 时表示直接复用流。"""
    src_path = Path(src)
    dest_path = Path(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    args = build_transcode_cmd(
        src_path,
        dest_path,
        vcodec=vcodec,
        acodec=acodec,
        crf=crf,
        preset=preset,
        scale=scale,
        audio_bitrate=audio_bitrate,
        extra_args=extra_args,
    )
    run_ffmpeg(args, duration=duration, on_progress=on_progress, cancel_check=cancel_check)
    return dest_path


def extract_audio(
    src: Any,
    dest: Any,
    acodec: str = "libmp3lame",
    bitrate: str = "192k",
    duration: float = 0.0,
    on_progress: Optional[Callable[[int], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> Path:
    """从视频中抽取音轨。"""
    src_path = Path(src)
    dest_path = Path(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    args = build_extract_audio_cmd(src_path, dest_path, acodec=acodec, bitrate=bitrate)
    run_ffmpeg(args, duration=duration, on_progress=on_progress, cancel_check=cancel_check)
    return dest_path
