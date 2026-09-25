"""ORM 模型：媒体条目与后台任务。"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
)

from app.database import Base


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


class MediaItem(Base):
    """一个媒体文件（视频 / 音频 / 图片）。"""

    __tablename__ = "media_items"

    id = Column(Integer, primary_key=True, index=True)
    path = Column(String(1024), unique=True, nullable=False, index=True)
    filename = Column(String(512), nullable=False)
    title = Column(String(512), index=True)
    media_type = Column(String(16), index=True, default="other")  # video / audio / image / other
    container = Column(String(64))
    size = Column(BigInteger, default=0)
    duration = Column(Float, default=0.0)
    width = Column(Integer, default=0)
    height = Column(Integer, default=0)
    video_codec = Column(String(64))
    audio_codec = Column(String(64))
    bit_rate = Column(BigInteger, default=0)
    frame_rate = Column(Float, default=0.0)
    sample_rate = Column(Integer, default=0)
    channels = Column(Integer, default=0)
    stream_count = Column(Integer, default=0)
    year = Column(Integer, index=True)
    has_thumbnail = Column(Boolean, default=False)
    thumbnail_path = Column(String(1024))
    directory = Column(String(1024), index=True)
    mtime = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # ------------------------------------------------------------------ #
    def to_dict(self, include_path: bool = True) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "id": self.id,
            "filename": self.filename,
            "title": self.title or self.filename,
            "media_type": self.media_type or "other",
            "container": self.container,
            "size": int(self.size or 0),
            "duration": round(float(self.duration or 0.0), 3),
            "width": int(self.width or 0),
            "height": int(self.height or 0),
            "video_codec": self.video_codec,
            "audio_codec": self.audio_codec,
            "bit_rate": int(self.bit_rate or 0),
            "frame_rate": float(self.frame_rate or 0.0),
            "sample_rate": int(self.sample_rate or 0),
            "channels": int(self.channels or 0),
            "stream_count": int(self.stream_count or 0),
            "year": self.year,
            "has_thumbnail": bool(self.has_thumbnail),
            "directory": self.directory,
            "mtime": float(self.mtime or 0.0),
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
            "thumbnail_url": f"/api/media/{self.id}/thumbnail" if self.has_thumbnail else None,
            "stream_url": f"/api/stream/{self.id}",
            "download_url": f"/api/media/{self.id}/download",
        }
        if include_path:
            data["path"] = self.path
            data["thumbnail_path"] = self.thumbnail_path
        return data

    def __repr__(self) -> str:  # pragma: no cover
        return f"<MediaItem id={self.id} type={self.media_type} name={self.filename!r}>"


class Task(Base):
    """后台任务（扫描 / 转码 / 抽音轨 / 截图）。"""

    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    task_type = Column(String(32), index=True, nullable=False)  # scan/transcode/extract_audio/screenshot
    status = Column(String(16), index=True, default="pending")   # pending/running/success/failed/canceled
    progress = Column(Integer, default=0)
    source_path = Column(String(1024))
    output_path = Column(String(1024))
    params = Column(Text)   # JSON 字符串
    result = Column(Text)   # JSON 字符串
    error = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _loads(raw: Optional[str]) -> Optional[Dict[str, Any]]:
        if not raw:
            return None
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            return None
        return value if isinstance(value, dict) else {"value": value}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "task_type": self.task_type,
            "status": self.status,
            "progress": int(self.progress or 0),
            "source_path": self.source_path,
            "output_path": self.output_path,
            "params": self._loads(self.params),
            "result": self._loads(self.result),
            "error": self.error,
            "created_at": _iso(self.created_at),
            "started_at": _iso(self.started_at),
            "finished_at": _iso(self.finished_at),
        }

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Task id={self.id} type={self.task_type} status={self.status} progress={self.progress}>"
