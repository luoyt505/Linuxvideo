"""媒体目录扫描与入库（增量）。"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.utils import ffmpeg_utils
from app.utils.ffmpeg_utils import TaskCancelled

logger = logging.getLogger(__name__)


def iter_media_files(directories: List[str], recursive: bool = True) -> List[Path]:
    """遍历媒体目录，返回所有受支持的媒体文件路径（绝对路径、已去重）。"""
    found: List[Path] = []
    for directory in directories:
        base = Path(directory).expanduser()
        if not base.is_absolute():
            base = (settings.base_dir / base).resolve()
        if not base.exists():
            logger.warning("媒体目录不存在，已跳过：%s", base)
            continue
        if base.is_file():
            if ffmpeg_utils.is_media(base):
                found.append(base)
            continue
        try:
            for item in base.glob("**/*" if recursive else "*"):
                try:
                    if item.is_file() and ffmpeg_utils.is_media(item):
                        found.append(item)
                except OSError:
                    continue
        except OSError as exc:
            logger.warning("遍历目录失败 %s：%s", base, exc)

    unique: Dict[str, Path] = {}
    for item in found:
        unique[str(item)] = item
    return list(unique.values())


def _build_thumbnail(db: Session, item: models.MediaItem, source: Path) -> None:
    """为视频 / 图片生成封面；失败不阻断扫描。"""
    if not settings.scan_thumbnails or item.media_type not in ("video", "image"):
        return
    try:
        dest = ffmpeg_utils.thumbnail_path_for(item.id)
        ffmpeg_utils.generate_thumbnail(source, dest, width=settings.thumbnail_width)
        item.thumbnail_path = str(dest)
        item.has_thumbnail = True
    except Exception as exc:  # noqa: BLE001 - 封面失败不应影响入库
        logger.debug("生成封面失败 %s：%s", source, exc)
        item.has_thumbnail = False


def scan_directory(
    db: Session,
    directory: Optional[str] = None,
    recursive: Optional[bool] = None,
    on_progress: Optional[Callable[[int], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> Dict[str, object]:
    """扫描目录并入库。

    :param directory: 指定单个目录；为空则使用配置中的全部媒体目录
    :param recursive: 是否递归；为空则使用 ``SCAN_RECURSIVE``
    :return: 统计字典
    """
    directories = [directory] if directory else list(settings.media_dirs)
    if not directories:
        raise ValueError("未配置任何媒体目录，请在 .env 中设置 MEDIA_DIRS 或指定 directory 参数")
    recursive = settings.scan_recursive if recursive is None else bool(recursive)

    if on_progress:
        on_progress(1)

    files = iter_media_files(directories, recursive=recursive)
    total = len(files)
    stats: Dict[str, object] = {
        "directories": directories,
        "recursive": recursive,
        "total": total,
        "added": 0,
        "updated": 0,
        "skipped": 0,
        "failed": 0,
        "degraded": 0,
        "removed": 0,
        "errors": [],
    }
    seen: set = set()

    for index, file_path in enumerate(files, start=1):
        if cancel_check is not None and cancel_check():
            raise TaskCancelled("扫描任务已取消")

        key = str(file_path)
        seen.add(key)

        try:
            stat = file_path.stat()
        except OSError as exc:
            stats["failed"] += 1
            stats["errors"].append({"path": key, "error": str(exc)})
            continue

        existing = db.query(models.MediaItem).filter(models.MediaItem.path == key).first()
        unchanged = (
            existing is not None
            and abs((existing.mtime or 0.0) - stat.st_mtime) < 1.0
            and int(existing.size or 0) == stat.st_size
        )

        if unchanged:
            stats["skipped"] += 1
        else:
            try:
                info = ffmpeg_utils.probe_info(file_path)
            except Exception as exc:  # noqa: BLE001 - 缺 ffmpeg 或文件损坏时降级
                logger.warning("探测失败，降级为基础信息：%s（%s）", file_path, exc)
                info = {
                    "media_type": ffmpeg_utils.classify(file_path) or "other",
                    "container": file_path.suffix.lstrip(".").lower() or None,
                    "duration": 0.0,
                    "size": stat.st_size,
                    "bit_rate": 0,
                    "width": 0,
                    "height": 0,
                    "video_codec": None,
                    "audio_codec": None,
                    "frame_rate": 0.0,
                    "sample_rate": 0,
                    "channels": 0,
                    "stream_count": 0,
                    "year": None,
                    "title": file_path.stem,
                    "streams": [],
                }
                stats["degraded"] += 1
                stats["errors"].append({"path": key, "error": str(exc)})

            if existing is None:
                item = models.MediaItem(path=key)
                db.add(item)
                stats["added"] += 1
            else:
                item = existing
                stats["updated"] += 1

            item.filename = file_path.name
            item.title = info.get("title") or file_path.stem
            item.media_type = info.get("media_type") or "other"
            item.container = info.get("container")
            item.size = stat.st_size
            item.duration = float(info.get("duration") or 0.0)
            item.width = int(info.get("width") or 0)
            item.height = int(info.get("height") or 0)
            item.video_codec = info.get("video_codec")
            item.audio_codec = info.get("audio_codec")
            item.bit_rate = int(info.get("bit_rate") or 0)
            item.frame_rate = float(info.get("frame_rate") or 0.0)
            item.sample_rate = int(info.get("sample_rate") or 0)
            item.channels = int(info.get("channels") or 0)
            item.stream_count = int(info.get("stream_count") or 0)
            item.year = info.get("year")
            item.directory = str(file_path.parent)
            item.mtime = stat.st_mtime

            db.flush()
            _build_thumbnail(db, item, file_path)
            db.commit()

        if on_progress and total:
            on_progress(min(99, int(index / total * 100)))

    # 清理源文件已消失的记录（仅限本次扫描覆盖的目录）
    try:
        for item in db.query(models.MediaItem).all():
            if item.path in seen:
                continue
            if any(item.path.startswith(d) for d in directories) and not Path(item.path).exists():
                db.delete(item)
                stats["removed"] += 1
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("清理失效记录失败：%s", exc)
        db.rollback()

    if on_progress:
        on_progress(100)

    logger.info(
        "扫描完成：共 %s 个文件，新增 %s，更新 %s，跳过 %s，失败 %s，移除 %s",
        stats["total"], stats["added"], stats["updated"],
        stats["skipped"], stats["failed"], stats["removed"],
    )
    return stats
