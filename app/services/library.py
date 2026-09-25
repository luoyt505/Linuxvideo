"""媒体库统计与聚合。"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models

_SIZE_UNITS = ["B", "KB", "MB", "GB", "TB", "PB", "EB"]


def human_size(num: float) -> str:
    """字节数转为人类可读字符串。"""
    value = float(num or 0)
    for unit in _SIZE_UNITS:
        if abs(value) < 1024.0:
            return f"{int(value)} B" if unit == "B" else f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{value:.2f} EB"


def human_duration(seconds: float) -> str:
    """秒数转为 ``1h 2m 3s`` 形式。"""
    total = int(seconds or 0)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def library_stats(db: Session) -> Dict[str, Any]:
    """汇总媒体库统计信息。"""
    total = db.query(func.count(models.MediaItem.id)).scalar() or 0

    by_type_rows = (
        db.query(models.MediaItem.media_type, func.count(models.MediaItem.id))
        .group_by(models.MediaItem.media_type)
        .all()
    )
    by_type = {str(k or "other"): int(v) for k, v in by_type_rows}

    total_size = db.query(func.coalesce(func.sum(models.MediaItem.size), 0)).scalar() or 0
    total_duration = db.query(func.coalesce(func.sum(models.MediaItem.duration), 0.0)).scalar() or 0.0

    by_year = [
        {"year": int(year), "count": int(count)}
        for year, count in (
            db.query(models.MediaItem.year, func.count(models.MediaItem.id))
            .filter(models.MediaItem.year.isnot(None))
            .group_by(models.MediaItem.year)
            .order_by(models.MediaItem.year.desc())
            .all()
        )
    ]

    by_container = [
        {"container": container or "unknown", "count": int(count)}
        for container, count in (
            db.query(models.MediaItem.container, func.count(models.MediaItem.id))
            .group_by(models.MediaItem.container)
            .order_by(func.count(models.MediaItem.id).desc())
            .limit(10)
            .all()
        )
    ]

    dir_counter: Counter = Counter()
    dir_sizes: Dict[str, int] = defaultdict(int)
    for directory, size in db.query(models.MediaItem.directory, models.MediaItem.size).all():
        key = directory or "unknown"
        dir_counter[key] += 1
        dir_sizes[key] += int(size or 0)

    top_directories: List[Dict[str, Any]] = [
        {"directory": directory, "count": count, "size": dir_sizes[directory]}
        for directory, count in dir_counter.most_common(10)
    ]

    thumbnail_count = (
        db.query(func.count(models.MediaItem.id))
        .filter(models.MediaItem.has_thumbnail.is_(True))
        .scalar() or 0
    )

    recent_items = (
        db.query(models.MediaItem)
        .order_by(models.MediaItem.created_at.desc())
        .limit(5)
        .all()
    )

    return {
        "total_items": int(total),
        "by_type": {key: by_type.get(key, 0) for key in ("video", "audio", "image", "other")},
        "total_size": int(total_size),
        "total_size_human": human_size(total_size),
        "total_duration": round(float(total_duration), 3),
        "total_duration_human": human_duration(total_duration),
        "thumbnail_count": int(thumbnail_count),
        "by_year": by_year,
        "by_container": by_container,
        "top_directories": top_directories,
        "recent_items": [item.to_dict(include_path=False) for item in recent_items],
    }
