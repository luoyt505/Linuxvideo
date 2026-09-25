"""Pydantic 请求 / 响应模型。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# 媒体库
# --------------------------------------------------------------------------- #
class ScanRequest(BaseModel):
    directory: Optional[str] = Field(
        default=None, description="指定单个目录；留空则扫描配置中的全部媒体目录"
    )
    recursive: Optional[bool] = Field(
        default=None, description="是否递归子目录；留空则使用 .env 中的 SCAN_RECURSIVE"
    )


class MediaItemOut(BaseModel):
    id: int
    path: Optional[str] = None
    filename: str
    title: Optional[str] = None
    media_type: str = "other"
    container: Optional[str] = None
    size: int = 0
    duration: float = 0.0
    width: int = 0
    height: int = 0
    video_codec: Optional[str] = None
    audio_codec: Optional[str] = None
    bit_rate: int = 0
    frame_rate: float = 0.0
    sample_rate: int = 0
    channels: int = 0
    stream_count: int = 0
    year: Optional[int] = None
    has_thumbnail: bool = False
    directory: Optional[str] = None
    mtime: float = 0.0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    thumbnail_url: Optional[str] = None
    stream_url: Optional[str] = None
    download_url: Optional[str] = None


class MediaListOut(BaseModel):
    total: int
    page: int
    page_size: int
    pages: int
    items: List[MediaItemOut]


# --------------------------------------------------------------------------- #
# 任务
# --------------------------------------------------------------------------- #
class TranscodeRequest(BaseModel):
    media_id: Optional[int] = Field(default=None, description="媒体库中的条目 ID")
    path: Optional[str] = Field(default=None, description="或直接指定源文件绝对路径")
    vcodec: str = Field(default="libx264", description="视频编码器，如 libx264 / libx265 / copy")
    acodec: str = Field(default="aac", description="音频编码器，如 aac / libmp3lame / copy")
    crf: int = Field(default=23, ge=0, le=51, description="质量参数，越小越清晰")
    preset: str = Field(default="medium", description="x264/x265 预设")
    scale: Optional[str] = Field(default=None, description="缩放，如 1280:-2")
    audio_bitrate: str = Field(default="192k", description="音频码率")
    output_name: Optional[str] = Field(default=None, description="输出文件名（可选）")


class ExtractAudioRequest(BaseModel):
    media_id: Optional[int] = None
    path: Optional[str] = None
    acodec: str = Field(default="libmp3lame", description="音频编码器，如 libmp3lame / aac / copy")
    bitrate: str = Field(default="192k")
    output_name: Optional[str] = None


class ScreenshotRequest(BaseModel):
    media_id: Optional[int] = None
    path: Optional[str] = None
    at: float = Field(default=3.0, ge=0.0, description="截取时间点（秒）")
    width: Optional[int] = Field(default=None, description="输出宽度，留空使用原尺寸")
    output_name: Optional[str] = None


class TaskOut(BaseModel):
    id: int
    task_type: str
    status: str
    progress: int = 0
    source_path: Optional[str] = None
    output_path: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class TaskListOut(BaseModel):
    total: int
    items: List[TaskOut]


# --------------------------------------------------------------------------- #
# 其它
# --------------------------------------------------------------------------- #
class MessageOut(BaseModel):
    ok: bool = True
    message: str = ""


class ErrorOut(BaseModel):
    detail: str
