"""应用配置。

优先从项目根目录的 ``.env`` 读取，其次读环境变量；所有相对路径均基于项目根目录解析。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List

try:  # python-dotenv 为可选依赖，缺失时退回纯环境变量
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None  # type: ignore[assignment]

BASE_DIR = Path(__file__).resolve().parent.parent

if load_dotenv is not None:
    load_dotenv(BASE_DIR / ".env")

_TRUE_VALUES = {"1", "true", "yes", "on", "y"}


def _as_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in _TRUE_VALUES


def _resolve_dir(value: str, default: Path) -> Path:
    """把配置里的目录字符串解析为绝对路径（相对路径基于项目根目录）。"""
    if not value:
        return default
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (BASE_DIR / path).resolve()
    return path


class Settings:
    """全局配置对象。"""

    def __init__(self) -> None:
        self.app_name: str = os.getenv("APP_NAME", "mediahub")
        self.version: str = "1.0.0"
        self.host: str = os.getenv("HOST", "0.0.0.0")
        self.port: int = int(os.getenv("PORT", "8000") or 8000)
        self.log_level: str = os.getenv("LOG_LEVEL", "info")

        self.base_dir: Path = BASE_DIR
        self.data_dir: Path = _resolve_dir(os.getenv("DATA_DIR", ""), BASE_DIR / "data")
        self.cache_dir: Path = _resolve_dir(os.getenv("CACHE_DIR", ""), self.data_dir / "cache")
        self.transcode_dir: Path = _resolve_dir(os.getenv("TRANSCODE_DIR", ""), self.data_dir / "transcoded")

        self.database_url: str = self._normalize_database_url(
            os.getenv("DATABASE_URL", "sqlite:///./data/mediahub.db")
        )

        self.media_dirs: List[str] = [
            _resolve_dir(part.strip(), Path(part.strip())).as_posix()
            for part in os.getenv("MEDIA_DIRS", "").split(",")
            if part.strip()
        ]

        self.ffmpeg_bin: str = os.getenv("FFMPEG_BIN", "ffmpeg")
        self.ffprobe_bin: str = os.getenv("FFPROBE_BIN", "ffprobe")

        self.scan_recursive: bool = _as_bool(os.getenv("SCAN_RECURSIVE", "true"), True)
        self.scan_thumbnails: bool = _as_bool(os.getenv("SCAN_THUMBNAILS", "true"), True)
        self.thumbnail_width: int = int(os.getenv("THUMBNAIL_WIDTH", "480") or 480)

        self.default_transcode_crf: int = int(os.getenv("TRANSCODE_CRF", "23") or 23)
        self.default_transcode_preset: str = os.getenv("TRANSCODE_PRESET", "medium")

        self.worker_count: int = max(1, int(os.getenv("WORKER_COUNT", "2") or 2))

    # ------------------------------------------------------------------ #
    def _normalize_database_url(self, url: str) -> str:
        """把 ``sqlite:///./data/x.db`` 这类相对路径转换为绝对路径。"""
        prefix = "sqlite:///"
        if url.startswith(prefix):
            raw = url[len(prefix):]
            path = Path(raw)
            if not path.is_absolute():
                path = (BASE_DIR / path).resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            return prefix + path.as_posix()
        if url.startswith("sqlite:////"):
            return url
        return url

    def ensure_dirs(self) -> None:
        """确保运行时目录存在。"""
        for directory in (self.data_dir, self.cache_dir, self.transcode_dir,
                          self.cache_dir / "thumbnails"):
            directory.mkdir(parents=True, exist_ok=True)

    def as_dict(self) -> Dict[str, object]:
        return {
            "app_name": self.app_name,
            "version": self.version,
            "host": self.host,
            "port": self.port,
            "database_url": self.database_url,
            "media_dirs": self.media_dirs,
            "data_dir": str(self.data_dir),
            "cache_dir": str(self.cache_dir),
            "transcode_dir": str(self.transcode_dir),
            "ffmpeg_bin": self.ffmpeg_bin,
            "ffprobe_bin": self.ffprobe_bin,
            "scan_recursive": self.scan_recursive,
            "scan_thumbnails": self.scan_thumbnails,
            "thumbnail_width": self.thumbnail_width,
            "worker_count": self.worker_count,
        }


settings = Settings()
settings.ensure_dirs()
